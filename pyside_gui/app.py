from __future__ import annotations
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from agent import DAGI_ROOT
from agent.loop import AgentConfig

from pyside_gui import esc_stop, recent_folders
from pyside_gui.agent_session import AgentSession
from pyside_gui.agents_controller import AgentsController
from pyside_gui.bridge import init_worker_logger
from pyside_gui.board_controller import BoardController
from pyside_gui.header import ConversationHeader
from pyside_gui.left_sidebar import LeftSidebar, _RAIL_WIDTH, panel_sizes
from pyside_gui.menu import build_main_menu, choose_theme
from pyside_gui.prompt_input import PromptInput
from pyside_gui.desktop_pet import DesktopPetWindow
from pyside_gui.right_sidebar import RightSidebar
from pyside_gui.theme import SCROLLBAR_QSS, qss
from pyside_gui.utils import format_elapsed

_WINDOW_CSS = qss("""
QMainWindow { background: @app_bg; }
QSplitter::handle { background: @border; }
QWidget#main-column { background: @chat_bg; }
QLabel#running-label {
    color: @fg_tertiary; font-family: @font_ui; font-size: 12.5px; padding: 0 0 6px 0;
}
""")

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_NARROW_VIEWS = ("board", "agents")  # left panels sized from the right sidebar's width
_NARROW_EXTRA = 80  # ...plus this much, so the board composer has room


class DagiMainWindow(QMainWindow):
    """Window chrome around one or more agent sessions; the active one fills the chat."""

    active_session_changed = Signal(object)  # AgentSession

    def __init__(
        self,
        config: AgentConfig,
        project_path: Path,
        verbose: bool,
    ) -> None:
        super().__init__()
        self._verbose = verbose
        self._sessions: list[AgentSession] = []
        self._active: AgentSession | None = None
        self._spinner_idx = 0
        self._compose_mode = False
        self._board_runtime = None
        self._board_listener = None

        self.setWindowTitle(f"Driverless AGI — {config.display_name}")
        self.setMinimumSize(1200, 700)
        self.setStyleSheet(_WINDOW_CSS + SCROLLBAR_QSS)
        _icon_path = Path(__file__).with_name("resources") / "icon.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))

        self._build_ui(config, project_path)
        main = self.add_session(config, project_path, "main")
        self._activate(main)
        recent_folders.push(project_path)
        self._esc = esc_stop.install(self)
        self._build_menu()
        self._connect_signals()
        self._start_timers()
        main.show_welcome()
        init_worker_logger(config.project_path / ".dagi" / "logs")
        self._board_controller = BoardController(self)
        self._agents = AgentsController(self)
        self._board_controller.start()

    # ── the active session, as the rest of the GUI sees it ─────────────────────────────

    @property
    def _main(self) -> AgentSession:
        return self._sessions[0]

    @property
    def _bridge(self):
        """The main agent's bridge; it also carries the message board's signals."""
        return self._main._bridge

    @property
    def _board_session(self):
        return self._main._board_session if self._sessions else None

    @_board_session.setter
    def _board_session(self, session) -> None:
        self._main._board_session = session

    @property
    def _config(self) -> AgentConfig:
        return self._active._config

    @property
    def _project_path(self) -> Path:
        return self._active._project_path

    @property
    def _conversation(self):
        return self._active._conversation

    @property
    def _cmd_handler(self):
        return self._active._cmd_handler

    @property
    def _worker(self):
        return self._active._worker

    @property
    def _current_loop_ref(self) -> list:
        return self._active._current_loop_ref

    @property
    def _pending_ask(self):
        return self._active._pending_ask

    @property
    def _active_loop(self):
        return self._active._active_loop

    # ── building ───────────────────────────────────────────────────────────────────────

    def _build_ui(self, config: AgentConfig, project_path: Path) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)

        self._left_sidebar = LeftSidebar(project_path)
        self._splitter.addWidget(self._left_sidebar)

        main_col = QWidget()
        main_col.setObjectName("main-column")
        col_layout = QVBoxLayout(main_col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)
        col_layout.addWidget(self._build_header())

        self._conversation_stack = QStackedWidget()
        col_layout.addWidget(self._conversation_stack, stretch=1)

        self._running_label = QLabel()
        self._running_label.setObjectName("running-label")
        self._running_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._running_label.hide()
        col_layout.addWidget(self._running_label)

        self._prompt = PromptInput()
        col_layout.addWidget(self._prompt)
        self._splitter.addWidget(main_col)

        self._right_sidebar = RightSidebar(
            config.display_name,
            config.context_window,
            config.reserve_tokens,
            DAGI_ROOT,
            project_path,
            getattr(config, "memory_root", None),
        )
        self._right_sidebar.scroll_to_bottom_requested.connect(
            lambda: self._conversation.scroll_to_bottom()
        )
        self._splitter.addWidget(self._right_sidebar)
        self._splitter.setSizes([40, 800, 300])
        self.setCentralWidget(self._splitter)

        self._desktop_pet = DesktopPetWindow()
        self._desktop_pet.set_save_dir(project_path)

    def _build_header(self) -> ConversationHeader:
        self._header = ConversationHeader()
        self._header.left_toggled.connect(self._toggle_left_sidebar)
        self._header.right_toggled.connect(self._toggle_right_sidebar)
        # Route through /wd so button and typed command share guards and side effects.
        self._header.folder_chosen.connect(lambda p: self._cmd_handler.handle(f"/wd {p}"))
        return self._header

    def _build_menu(self) -> None:
        build_main_menu(
            self,
            on_new_session=lambda: self._cmd_handler.handle("/clear"),
            on_compact=lambda: self._active._handle_special_command("__COMPACT__"),
            on_compose=self._toggle_compose,
            on_theme=lambda choice: choose_theme(
                self, choice, busy=any(session.busy for session in self._sessions)
            ),
        )

    def _connect_signals(self) -> None:
        self._prompt.submitted.connect(self._on_input_submitted)
        self._prompt.stop_requested.connect(self._action_pause)
        self._right_sidebar.model_selected.connect(self._on_model_selected)
        self._prompt.attachment_error.connect(lambda text: self._conversation.append_error(text))
        self._left_sidebar.session_selected.connect(self._on_session_selected)
        self._left_sidebar.expansion_changed.connect(self._on_sidebar_expansion)
        self._left_sidebar.view_changed.connect(self._on_left_view_changed)

    def _start_timers(self) -> None:
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(100)
        self._plan_timer = QTimer(self)
        self._plan_timer.timeout.connect(self._poll_plan)
        self._plan_timer.start(2000)

    # ── sessions ───────────────────────────────────────────────────────────────────────

    def add_session(self, config: AgentConfig, project_path: Path, handle: str) -> AgentSession:
        """Create an agent session with its own conversation view (not yet active)."""
        session = AgentSession(self, config, project_path, handle)
        self._sessions.append(session)
        self._conversation_stack.addWidget(session._conversation)
        return session

    def remove_session(self, session: AgentSession) -> None:
        """Drop a spawned agent from the window; the main agent is never removed."""
        if session is self._main or session not in self._sessions:
            return
        if session is self._active:
            self._activate(self._main)
        self._sessions.remove(session)
        self._conversation_stack.removeWidget(session._conversation)
        session._conversation.hide()

    def _on_board_ready(self) -> None:
        """Called by the board controller each time a board becomes the live one."""
        agents = getattr(self, "_agents", None)
        if agents is not None:
            agents.on_board_ready()

    def _on_board_mention(self, post: dict, user_handle: str) -> None:
        """A live board post mentions someone; agents it names get it as a user message."""
        agents = getattr(self, "_agents", None)
        if agents is not None:
            agents.on_board_mention(post, user_handle)

    def _activate(self, session: AgentSession) -> None:
        """Show ``session`` in the main chat and point the shared chrome at it."""
        self._active = session
        self._conversation_stack.setCurrentWidget(session._conversation)
        self._prompt.set_completions(session._cmd_handler.completions())
        self._apply_running(session)
        rs = self._right_sidebar
        rs.set_status(session.status)
        rs.update_stats(*(session._last_tokens or (0, 0, None, 0)))
        rs.update_context(session._last_context or {})
        self._on_active_config_changed()
        rs.update_model(session._model_name)
        self._left_sidebar.update_plan([], "")
        self.active_session_changed.emit(session)

    def _on_active_config_changed(self) -> None:
        """The active agent's model or folder changed (or another agent became active)."""
        path = self._project_path
        self._desktop_pet.set_save_dir(path)
        self._right_sidebar.set_project_path(path)
        self._left_sidebar.set_project_path(path)
        self._refresh_models()
        self._refresh_title()

    def _apply_running(self, session: AgentSession) -> None:
        if session.running:
            elapsed = format_elapsed(session._run_start_time)
            self._running_label.setText(f"  {_SPINNER[self._spinner_idx]} Running…  {elapsed}")
            self._running_label.show()
        else:
            self._running_label.hide()
        self._prompt.set_running(session.running)

    # ── chrome ─────────────────────────────────────────────────────────────────────────

    def _refresh_title(self) -> None:
        self._header.set_folder(self._project_path)
        title = self._config.display_name
        if len(self._sessions) > 1:
            title = f"{self._active.handle} · {title}"
        self._header.set_title(title)

    def _toggle_left_sidebar(self) -> None:
        self._left_sidebar.setVisible(not self._left_sidebar.isVisible())

    def _toggle_right_sidebar(self) -> None:
        self._right_sidebar.setVisible(not self._right_sidebar.isVisible())

    def _refresh_models(self) -> None:
        from agent.config_loader import list_model_ids
        try:
            ids = list_model_ids()
        except Exception:
            ids = []
        self._right_sidebar.set_models(ids, self._config.model_id, self._config.display_name)

    def _on_model_selected(self, model_id: str) -> None:
        if model_id != self._config.model_id:
            self._cmd_handler.handle(f"/model {model_id}")

    def _on_input_submitted(self, submission: object) -> None:
        self._active._on_input_submitted(submission)

    def _on_session_selected(self, session_data: dict) -> None:
        self._active.restore(session_data)
        self._left_sidebar.collapse()

    def _on_notepad_flush_requested(self, done: object) -> None:
        self._desktop_pet.flush_notepad_async(done.set)

    def closeEvent(self, event) -> None:
        self._board_controller.close()
        self._desktop_pet.close()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._action_pause()
            return
        super().keyPressEvent(event)

    def _on_sidebar_expansion(self, expanded: bool) -> None:
        s = self._splitter.sizes()
        if not expanded:
            self._splitter.setSizes([_RAIL_WIDTH, s[0] + s[1] - _RAIL_WIDTH, s[2]]); return
        self._left_narrow = self._left_sidebar.active_view() in _NARROW_VIEWS
        rs = self._right_sidebar
        width = (
            (rs.width() if rs.isVisible() else rs.maximumWidth()) + _NARROW_EXTRA
        ) if self._left_narrow else None
        self._splitter.setSizes(panel_sizes(s, width))

    def _on_left_view_changed(self, view: str) -> None:
        # Re-size only when switching to or from a narrow panel.
        if (view in _NARROW_VIEWS) != getattr(self, "_left_narrow", False):
            self._on_sidebar_expansion(True)

    def _action_pause(self) -> None:
        """Esc: stop the active agent's turn, or collapse the left panel when it is idle."""
        if not self._active.busy:
            if self._left_sidebar.is_expanded(): self._left_sidebar.collapse()
            return
        self._active.stop()

    def _tick_spinner(self) -> None:
        if not self._running_label.isVisible():
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER)
        elapsed = format_elapsed(self._active._run_start_time)
        self._running_label.setText(
            f"  {_SPINNER[self._spinner_idx]} Running…  {elapsed}"
        )

    def _poll_plan(self) -> None:
        if not self._current_loop_ref:
            return
        path = self._current_loop_ref[0].config.active_plan_file
        if not path:
            self._left_sidebar.update_plan([]); return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            self._left_sidebar.update_plan([]); return
        except OSError:
            return
        from tools._plan_parser import parse_subtask_statuses
        subtasks = parse_subtask_statuses(text)
        title = next((l.lstrip("# ").removeprefix("Plan — ").strip()
                      for l in text.splitlines() if l.startswith("# Plan")), "")
        self._left_sidebar.update_plan(subtasks, title)

    def _toggle_compose(self) -> None:
        if self._active.busy:
            return
        self._compose_mode = not self._compose_mode
        self._conversation_stack.setVisible(not self._compose_mode)
        self._prompt.set_compose_mode(self._compose_mode)
        self._prompt.setPlaceholderText(
            "COMPOSE — Enter to submit, Ctrl+O to collapse" if self._compose_mode
            else "Type a message… (Enter to send, Shift+Enter for newline)"
        )
