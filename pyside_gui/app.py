from __future__ import annotations
import threading
import time
from pathlib import Path

from PySide6.QtCore import QMetaObject, Qt, QTimer, Q_ARG, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from agent import DAGI_ROOT
from agent.loop import AgentConfig, AgentLoop

from pyside_gui import _dispatch
from pyside_gui.bridge import AgentBridge, init_worker_logger
from pyside_gui.commands import SlashCommandHandler, UIWidgets
from pyside_gui.conversation import ConversationView
from pyside_gui.left_sidebar import LeftSidebar, _RAIL_WIDTH
from pyside_gui.markdown_renderer import render_markdown
from pyside_gui.menu import build_main_menu
from pyside_gui.overlays import CopyPicker
from pyside_gui.prompt_input import PromptInput
from pyside_gui.desktop_pet import DesktopPetWindow
from pyside_gui.right_sidebar import RightSidebar
from pyside_gui.utils import format_elapsed

_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class DagiMainWindow(QMainWindow):
    def __init__(
        self,
        config: AgentConfig,
        project_path: Path,
        verbose: bool,
    ) -> None:
        super().__init__()
        self._config = config
        self._project_path = project_path
        self._verbose = verbose
        self._active_loop: AgentLoop | None = None
        self._worker: threading.Thread | None = None
        self._current_loop_ref: list = []
        self._run_start_time: float | None = None
        self._spinner_idx = 0
        self._restore_initial_messages: list | None = None
        self._restore_initial_affect = None
        self._pending_ask: object = None  # threading.Event; answer sink below
        self._pending_ask_container: list | None = None
        self._compose_mode = False
        self._stream_had_content = False
        self._stream_had_reasoning = False
        self._streaming_active = False
        self._submission_seq = 0

        self.setWindowTitle(f"Driverless AGI — {config.display_name}")
        self.setMinimumSize(1200, 700)
        self.setStyleSheet("QMainWindow { background: #1e1e2e; }")
        _icon_path = Path(__file__).with_name("resources") / "icon.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))

        self._build_ui()
        self._bridge = AgentBridge()
        self._build_menu()
        self._build_commands()
        self._connect_signals()
        self._start_timers()
        self._show_welcome()
        init_worker_logger(config.project_path / ".dagi" / "logs")

    def _build_ui(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._left_sidebar = LeftSidebar(self._project_path)
        self._splitter.addWidget(self._left_sidebar)

        main_col = QWidget()
        col_layout = QVBoxLayout(main_col)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(0)

        self._conversation = ConversationView(self._verbose)
        col_layout.addWidget(self._conversation, stretch=1)

        self._running_label = QLabel()
        self._running_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._running_label.setStyleSheet(
            "color: #a6e3a1; font-size: 13px; padding: 4px;"
        )
        self._running_label.hide()
        col_layout.addWidget(self._running_label)

        self._prompt = PromptInput()
        col_layout.addWidget(self._prompt)
        self._splitter.addWidget(main_col)

        self._right_sidebar = RightSidebar(
            self._config.display_name,
            self._config.context_window,
            self._config.reserve_tokens,
            DAGI_ROOT,
            self._project_path,
            getattr(self._config, "memory_root", None),
        )
        self._right_sidebar.scroll_to_bottom_requested.connect(self._conversation.scroll_to_bottom)
        self._splitter.addWidget(self._right_sidebar)
        self._splitter.setSizes([40, 800, 300])
        self.setCentralWidget(self._splitter)

        self._desktop_pet = DesktopPetWindow()

        self._copy_picker = CopyPicker(self._conversation)

    def _build_menu(self) -> None:
        build_main_menu(
            self,
            on_new_session=lambda: self._cmd_handler.handle("/clear"),
            on_compact=lambda: self._handle_special_command("__COMPACT__"),
            on_compose=self._toggle_compose,
        )

    def _build_commands(self) -> None:
        widgets = UIWidgets(
            conversation=self._conversation,
            right_sidebar=self._right_sidebar,
            left_sidebar=self._left_sidebar,
        )
        self._cmd_handler = SlashCommandHandler(
            widgets, self._config, self._project_path
        )
        alive = lambda: bool(self._worker and self._worker.is_alive())  # noqa: E731
        self._cmd_handler.set_worker_alive_check(alive)
        self._cmd_handler.set_on_config_changed(self._on_config_changed)
        self._cmd_handler.set_on_session_cleared(self._on_session_cleared)
        self._cmd_handler.set_desktop_pet(self._desktop_pet)
        self._cmd_handler.load_maps()

    def _on_config_changed(self, config: AgentConfig, project_path: Path) -> None:
        self._config, self._project_path = config, project_path
        self._active_loop = None

    def _on_session_cleared(self) -> None:
        self._active_loop = None; self._bridge.reset_stats()

    def _connect_signals(self) -> None:
        self._prompt.submitted.connect(self._on_input_submitted)
        self._prompt.attachment_error.connect(self._conversation.append_error)
        self._left_sidebar.session_selected.connect(self._on_session_selected)
        self._left_sidebar.expansion_changed.connect(self._on_sidebar_expansion)
        b, cv, rs = self._bridge, self._conversation, self._right_sidebar
        b.tool_started.connect(cv.append_tool_start)
        b.tool_ended.connect(cv.append_tool_end)
        b.assistant_text.connect(self._on_assistant_text)
        b.handoff_text.connect(cv.append_assistant)
        b.stream_started.connect(self._on_stream_started)
        b.reasoning_received.connect(self._on_reasoning)
        b.stream_text_delta.connect(lambda c: cv.stream_delta("text", c))
        b.stream_reasoning_delta.connect(lambda c: cv.stream_delta("reasoning", c))
        b.stream_ended.connect(self._on_stream_ended)
        b.token_update.connect(rs.update_stats)
        b.context_update.connect(rs.update_context)
        b.compaction_done.connect(self._on_compaction)
        b.model_switched.connect(self._on_model_switched)
        b.error_occurred.connect(cv.append_error)
        b.agent_done.connect(self._on_agent_done)
        b.agent_paused.connect(self._on_agent_paused)
        b.ask_user_requested.connect(self._on_ask_user)
        b.process_state_changed.connect(rs.expression_widget.update_process)
        b.continue_injected.connect(
            lambda c, m: cv.append_info(f"No exit flag — continue prompt injected ({c}/{m})")
        )
        b.subagent_event.connect(cv.append_subagent_event)
        b.message_board_post.connect(self._left_sidebar.board_view.add_post)
        b.message_board_post.connect(
            lambda _author, name, path, text, ts: cv.append_emote(
                name, path, text, ts
            )
        )
        b.show_file_requested.connect(
            lambda path, line: self._left_sidebar.open_file(path, line)
        )

    def _start_timers(self) -> None:
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(100)
        self._plan_timer = QTimer(self)
        self._plan_timer.timeout.connect(self._poll_plan)
        self._plan_timer.start(2000)

    def _show_welcome(self) -> None:
        self._conversation.append_info(
            f"Driverless AGI · {self._config.display_name} · {self._project_path}"
            "\nType /help for commands"
        )

    @Slot(object)
    def _on_input_submitted(self, submission: object) -> None:
        _dispatch.on_input_submitted(self, submission)

    def _handle_special_command(self, result: str) -> None:
        _dispatch.handle_special_command(self, result)

    def _dispatch_agent(self, task: object) -> None:
        _dispatch.dispatch_agent(self, task)

    def _agent_work(self, task: object, callbacks: object, loop_ref: list) -> None:
        _dispatch.agent_work(self, task, callbacks, loop_ref)

    def closeEvent(self, event) -> None:
        self._desktop_pet.close()
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._action_pause()
            return
        super().keyPressEvent(event)

    def _on_sidebar_expansion(self, expanded: bool) -> None:
        s = self._splitter.sizes()
        if expanded:
            half = s[1] // 2
            self._splitter.setSizes([_RAIL_WIDTH + half, s[1] - half, s[2]])
        else:
            total = s[0] + s[1]
            self._splitter.setSizes([_RAIL_WIDTH, total - _RAIL_WIDTH, s[2]])

    def _action_pause(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            if self._left_sidebar.is_expanded(): self._left_sidebar.collapse()
            return
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        if not loop._pause_event.is_set():
            return
        bash = loop.registry._tools.get("bash")
        if bash is not None: bash.force_kill()
        from tools._subagent_runner import force_kill_active_subagents
        force_kill_active_subagents()
        loop.pause()
        self._right_sidebar.set_status("paused")
        self._conversation.append_info("Paused — type a message and press Enter to continue")
        self._hide_running(); self._enable_input()

    @Slot()
    def _on_stream_started(self) -> None:
        self._stream_had_content = False
        self._stream_had_reasoning = False
        self._streaming_active = True
        self._conversation.stream_start()

    @Slot(str, str)
    def _on_stream_ended(self, stream_text: str, stream_reasoning: str) -> None:
        text = stream_text.strip()
        if stream_reasoning.strip():
            self._stream_had_reasoning = True
        if text:
            self._stream_had_content = True
            self._conversation.stream_end(render_markdown(text, allow_html=False))
        else:
            self._conversation.stream_end("")
        self._streaming_active = False

    @Slot(str)
    def _on_reasoning(self, text: str) -> None:
        if not self._streaming_active and not self._stream_had_content and not self._stream_had_reasoning:
            self._conversation.append_reasoning(text)

    @Slot(str)
    def _on_assistant_text(self, html: str) -> None:
        if self._stream_had_content:
            return
        self._conversation.append_assistant(html)

    @Slot(int, int)
    def _on_compaction(self, kept: int, removed: int) -> None:
        self._conversation.append_info(f"Context compacted — removed {removed} messages, kept {kept}")

    @Slot(str, str)
    def _on_model_switched(self, from_name: str, to_name: str) -> None:
        self._conversation.append_info(f"Model switch: {from_name} → {to_name}")
        self._right_sidebar.update_model(to_name)

    @Slot(str)
    def _on_agent_done(self, result: str) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._conversation.append_info("— turn complete —")
        if result: self._notify("DAGI is done", result)
        self._enable_input()

    @Slot()
    def _on_agent_paused(self) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._right_sidebar.set_status("paused")
        self._conversation.append_info("Server error — session paused. Send a message to retry.")
        self._enable_input()

    @Slot(str, object, object)
    def _on_ask_user(self, question: str, data: object, _unused: object) -> None:
        options, timeout, event, container = data
        self._pending_ask, self._pending_ask_container = event, container
        self._notify("DAGI has a question", question)
        self._conversation.append_question(question, options, timeout); self._enable_input()

    @Slot(object)
    def _on_session_selected(self, session_data: dict) -> None:
        from agent.history import load_affect_restore, load_raw_messages
        path = Path(session_data["path"])
        raw = load_raw_messages(path)
        if not raw:
            self._conversation.append_error("Cannot restore — session has no raw_messages.")
            return
        self._active_loop = None
        self._current_loop_ref = []
        self._conversation.clear()
        self._restore_initial_messages = raw
        self._restore_initial_affect = load_affect_restore(path)
        msg = f"Restored {len(raw) - 1} messages from {path.name} — type next message"
        self._conversation.append_info(msg)
        self._left_sidebar.collapse()
        self._enable_input()

    def _do_compact(self) -> None:
        if self._active_loop is None:
            self._conversation.append_info("Nothing to compact — no active conversation.")
            return
        self._conversation.append_info("Compacting context...")
        loop = self._active_loop

        def _work() -> None:
            try:
                r = loop.compact(force=True)
            except Exception as exc:
                self._bridge.error_occurred.emit(f"Compact failed: {exc}"); return
            if r.did_compact:
                self._bridge.compaction_done.emit(len(loop._messages), r.removed_count)
        threading.Thread(target=_work, daemon=True).start()

    def _do_wtf(self, description: str | None) -> None:
        loop = self._active_loop
        if loop is None:
            self._conversation.append_info("Nothing to diagnose — no active conversation.")
            return

        def _work() -> None:
            try:
                r = loop.run_wtf(description)
            except Exception as exc:
                self._bridge.error_occurred.emit(f"/wtf failed: {exc}"); return
            rp = Path(r.report_path).resolve()
            self._bridge.assistant_text.emit(
                f"<p>Diagnosis: {r.description}</p><p>Report: {rp}</p>"
            )
        self._show_running()
        threading.Thread(target=_work, daemon=True).start()

    def _show_running(self) -> None:
        self._run_start_time = time.monotonic()
        self._running_label.setText(f"  {_SPINNER[0]} Running…  0s"); self._running_label.show()

    def _hide_running(self) -> None:
        self._run_start_time = None; self._running_label.hide()

    def _enable_input(self) -> None:
        self._hide_running(); self._prompt.setDisabled(False); self._prompt.setFocus()

    def _tick_spinner(self) -> None:
        if not self._running_label.isVisible():
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER)
        elapsed = format_elapsed(self._run_start_time)
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
        if self._worker and self._worker.is_alive():
            return
        self._compose_mode = not self._compose_mode
        self._conversation.setVisible(not self._compose_mode)
        self._prompt.set_compose_mode(self._compose_mode)
        self._prompt.setPlaceholderText(
            "COMPOSE — Enter to submit, Ctrl+O to collapse" if self._compose_mode
            else "Type a message… (Enter to send, Shift+Enter for newline)"
        )

    def _notify(self, title: str, message: str) -> None:
        if self.isActiveWindow():
            return
        try:
            from tui.notifications import notify; notify(title, message)
        except Exception:
            pass

    @Slot(str)
    def _set_status_slot(self, s: str) -> None: self._right_sidebar.set_status(s)

    @Slot()
    def _enable_input_slot(self) -> None: self._enable_input()

    @Slot()
    def _clear_pending_ask_slot(self) -> None:
        self._pending_ask = self._pending_ask_container = None

    def _invoke_on_main(self, slot: str, arg: str | None = None) -> None:
        c = Qt.ConnectionType.QueuedConnection
        if arg is not None:
            QMetaObject.invokeMethod(self, slot, c, Q_ARG(str, arg))
        else:
            QMetaObject.invokeMethod(self, slot, c)
