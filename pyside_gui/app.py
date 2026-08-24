from __future__ import annotations
import threading
import time
import traceback
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
from agent.loop import AgentConfig, AgentLoop, AWAIT_USER_FLAG, TASK_END_FLAG

_LOOP_SENTINELS = (AWAIT_USER_FLAG, TASK_END_FLAG)

from pyside_gui.bridge import AgentBridge, init_worker_logger, worker_log
from pyside_gui.commands import SlashCommandHandler, UIWidgets
from pyside_gui.conversation import ConversationView
from pyside_gui.left_sidebar import LeftSidebar, _RAIL_WIDTH
from pyside_gui.markdown_renderer import render_markdown
from pyside_gui.menu import build_main_menu
from pyside_gui.overlays import CopyPicker
from pyside_gui.prompt_input import PromptInput
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
        self._stream_had_content = False  # suppresses duplicate assistant_text after streaming

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
        self._splitter.addWidget(self._right_sidebar)
        self._splitter.setSizes([40, 800, 300])
        self.setCentralWidget(self._splitter)

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
        self._cmd_handler.load_maps()

    def _connect_signals(self) -> None:
        self._prompt.submitted.connect(self._on_input_submitted)
        self._left_sidebar.session_selected.connect(self._on_session_selected)
        self._left_sidebar.expansion_changed.connect(
            self._on_sidebar_expansion
        )

        b = self._bridge
        b.tool_started.connect(self._conversation.append_tool_start)
        b.tool_ended.connect(self._conversation.append_tool_end)
        b.assistant_text.connect(self._on_assistant_text)
        b.stream_started.connect(self._on_stream_started)
        b.reasoning_received.connect(self._on_reasoning)
        b.stream_text_delta.connect(
            lambda c: self._conversation.stream_delta("text", c)
        )
        b.stream_reasoning_delta.connect(
            lambda c: self._conversation.stream_delta("reasoning", c)
        )
        b.stream_ended.connect(self._on_stream_ended)
        b.token_update.connect(self._right_sidebar.update_stats)
        b.context_update.connect(self._right_sidebar.update_context)
        b.compaction_done.connect(self._on_compaction)
        b.model_switched.connect(self._on_model_switched)
        b.error_occurred.connect(self._conversation.append_error)
        b.agent_done.connect(self._on_agent_done)
        b.agent_paused.connect(self._on_agent_paused)
        b.ask_user_requested.connect(self._on_ask_user)
        b.affect_changed.connect(
            self._right_sidebar.expression_widget.update_affect
        )
        b.process_state_changed.connect(
            self._right_sidebar.expression_widget.update_process
        )
        b.continue_injected.connect(
            lambda c, m: self._conversation.append_info(
                f"No exit flag — continue prompt injected ({c}/{m})"
            )
        )
        b.subagent_event.connect(self._conversation.append_subagent_event)
        b.stage_trace.connect(self._conversation.append_info)

    def _start_timers(self) -> None:
        self._spinner_timer = QTimer(self)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_timer.start(100)
        self._plan_timer = QTimer(self)
        self._plan_timer.timeout.connect(self._poll_plan)
        self._plan_timer.start(2000)
        drift_ms = int(self._config.affect_drift_interval * 1000)
        if drift_ms > 0:
            self._drift_timer = QTimer(self)
            self._drift_timer.timeout.connect(self._tick_drift)
            self._drift_timer.start(drift_ms)

    @Slot()
    def _tick_drift(self) -> None:
        loop = self._active_loop
        if loop is None:
            return
        controller = loop.tracker.affect_controller
        if controller is None:
            return
        controller.drift()

    def _show_welcome(self) -> None:
        self._conversation.append_info(
            f"Driverless AGI · {self._config.display_name} · {self._project_path}"
            "\nType /help for commands"
        )

    @Slot(str)
    def _on_input_submitted(self, text: str) -> None:
        if text.lower() in ("exit", "quit", "q"):
            self.close()
            return
        if self._pending_ask is not None:
            if self._pending_ask_container is not None:
                self._pending_ask_container.append(text)
            self._pending_ask.set()
            self._pending_ask = None
            self._pending_ask_container = None
            self._conversation.append_user_message(text)
            self._prompt.setDisabled(True)
            self._show_running()
            return
        # Inject-and-resume while paused
        if (
            self._worker and self._worker.is_alive()
            and self._current_loop_ref
            and not self._current_loop_ref[0]._pause_event.is_set()
        ):
            loop = self._current_loop_ref[0]
            self._conversation.append_user_message(text)
            self._prompt.setDisabled(True)
            self._show_running()
            self._right_sidebar.set_status("running")
            loop.inject_and_resume(text)
            return
        if text.startswith("/"):
            result = self._cmd_handler.handle(text)
            if result == "__EXIT__":
                self.close()
            elif result is not None:
                self._handle_special_command(result)
                if not result.startswith("__"):
                    self._dispatch_agent(result)
            return
        self._dispatch_agent(text)

    def _handle_special_command(self, result: str) -> None:
        if result == "__COMPACT__":
            self._do_compact()
        elif result.startswith("__WTF__"):
            self._do_wtf(result[7:] or None)
        elif result == "__COPY__":
            msgs = list(self._active_loop._messages) if self._active_loop else []
            self._copy_picker.show_messages(msgs)

    def _dispatch_agent(self, task: str) -> None:
        if self._worker and self._worker.is_alive():
            self._conversation.append_info("Agent is already running.")
            return
        self._conversation.append_user_message(task)
        self._prompt.setDisabled(True)
        self._show_running()
        self._current_loop_ref = []
        callbacks = self._bridge.build_callbacks(self._current_loop_ref)
        self._worker = threading.Thread(
            target=self._agent_work, args=(task, callbacks, self._current_loop_ref), daemon=True)
        self._worker.start()

    def _agent_work(self, task: str, callbacks: object, loop_ref: list) -> None:
        trace = self._bridge.stage_trace.emit
        t0 = time.monotonic()
        def stage(msg: str) -> None:
            worker_log.info("[%.3fs] %s", time.monotonic() - t0, msg); trace(f"Stage: {msg}")
        self._invoke_on_main("_set_status_slot", "running"); stage("worker started")
        try:
            tracker = self._active_loop.tracker if self._active_loop else None
            if self._restore_initial_messages is not None:
                initial, self._restore_initial_messages = self._restore_initial_messages, None
                initial_affect, self._restore_initial_affect = self._restore_initial_affect, None
            else:
                initial = self._active_loop._messages if self._active_loop else None
                initial_affect = None
            stage(f"session captured (msgs={len(initial) if initial else 0})")
            stage("AgentLoop construction started")
            loop = AgentLoop(
                self._config, callbacks, initial_messages=initial,
                initial_affect=initial_affect, _tracker=tracker,
            )
            stage("AgentLoop constructed"); loop_ref.append(loop)
            self._active_loop = loop; self._cmd_handler.set_active_loop(loop)
            stage("agent run started")
            loop.run(task); stage("agent run completed")
        except Exception as exc:
            stage(f"EXCEPTION: {type(exc).__name__}: {exc}")
            worker_log.debug("".join(traceback.format_exception(exc)))
            self._bridge.error_occurred.emit(str(exc))
        finally:
            if loop_ref:
                try: loop_ref[0].finish()
                except Exception: pass
            stage("finally: idle"); self._invoke_on_main("_set_status_slot", "idle")
            self._invoke_on_main("_enable_input_slot")
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._action_pause()
            return
        super().keyPressEvent(event)

    def _on_sidebar_expansion(self, expanded: bool) -> None:
        right_w = self._splitter.sizes()[2]
        if expanded:
            conv_w = self._splitter.sizes()[1]
            half = conv_w // 2
            sidebar_w = _RAIL_WIDTH + half
            self._splitter.setSizes(
                [sidebar_w, conv_w - half, right_w]
            )
        else:
            total = self._splitter.sizes()[0] + self._splitter.sizes()[1]
            self._splitter.setSizes(
                [_RAIL_WIDTH, total - _RAIL_WIDTH, right_w]
            )

    def _action_pause(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            if self._left_sidebar.is_expanded():
                self._left_sidebar.collapse()
            return
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        if not loop._pause_event.is_set():
            return  # already paused
        bash_tool = loop.registry._tools.get("bash")
        if bash_tool is not None:
            bash_tool.force_kill()
        from tools._subagent_runner import force_kill_active_subagents
        force_kill_active_subagents()
        loop.pause()
        self._right_sidebar.set_status("paused")
        self._conversation.append_info(
            "Paused — type a message and press Enter to continue"
        )
        self._hide_running()
        self._enable_input()

    @Slot()
    def _on_stream_started(self) -> None:
        self._stream_had_content = False
        self._conversation.stream_start()

    @Slot()
    def _on_stream_ended(self) -> None:
        text = self._bridge._stream_text
        for s in _LOOP_SENTINELS:
            text = text.replace(s, "")
        text = text.strip()
        if text:
            self._stream_had_content = True
            self._conversation.stream_end(render_markdown(text))
        else:
            self._conversation.stream_end("")

    @Slot(str)
    def _on_reasoning(self, text: str) -> None:
        if not self._stream_had_content:
            self._conversation.append_reasoning(text)

    @Slot(str)
    def _on_assistant_text(self, html: str) -> None:
        if self._stream_had_content:
            self._stream_had_content = False
            return
        self._conversation.append_assistant(html)

    @Slot(int, int)
    def _on_compaction(self, kept: int, removed: int) -> None:
        self._conversation.append_info(
            f"Context compacted — removed {removed} messages, kept {kept}"
        )

    @Slot(str, str)
    def _on_model_switched(self, from_name: str, to_name: str) -> None:
        self._conversation.append_info(f"Model switch: {from_name} → {to_name}")
        self._right_sidebar.update_model(to_name)

    @Slot(str)
    def _on_agent_done(self, result: str) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._conversation.append_info("— turn complete —")
        if result:
            self._notify("DAGI is done", result)
        self._enable_input()

    @Slot()
    def _on_agent_paused(self) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._right_sidebar.set_status("paused")
        self._conversation.append_info(
            "Server error — session paused. Send a message to retry."
        )
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
                result = loop.compact(force=True)
            except Exception as exc:
                self._bridge.error_occurred.emit(f"Compact failed: {exc}")
                return
            if result.did_compact:
                self._bridge.compaction_done.emit(len(loop._messages), result.removed_count)

        threading.Thread(target=_work, daemon=True).start()

    def _do_wtf(self, description: str | None) -> None:
        loop = self._active_loop
        if loop is None:
            self._conversation.append_info("Nothing to diagnose — no active conversation.")
            return

        def _work() -> None:
            try:
                result = loop.run_wtf(description)
            except Exception as exc:
                self._bridge.error_occurred.emit(f"/wtf failed: {exc}")
                return
            rp = Path(result.report_path).resolve()
            self._bridge.assistant_text.emit(
                f"<p>Diagnosis: {result.description}</p><p>Report: {rp}</p>"
            )

        self._show_running()
        threading.Thread(target=_work, daemon=True).start()

    def _show_running(self) -> None:
        self._run_start_time = time.monotonic()
        self._running_label.setText(f"  {_SPINNER[0]} Running…  0s")
        self._running_label.show()

    def _hide_running(self) -> None:
        self._run_start_time = None
        self._running_label.hide()

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
        loop = self._current_loop_ref[0]
        path = loop.config.plan_file or loop.config.active_plan_file
        if not path:
            self._right_sidebar.update_plan([])
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            return
        from tools._plan_parser import parse_subtask_statuses
        subtasks = parse_subtask_statuses(text)
        title = next((l.lstrip("# ").removeprefix("Plan — ").strip()
                      for l in text.splitlines() if l.startswith("# Plan")), "")
        self._right_sidebar.update_plan(subtasks, title)

    def _toggle_compose(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._compose_mode = not self._compose_mode
        self._conversation.setVisible(not self._compose_mode)
        self._prompt.set_compose_mode(self._compose_mode)
        txt = ("COMPOSE — Enter to submit, Ctrl+O to collapse" if self._compose_mode
               else "Type a message… (Enter to send, Shift+Enter for newline)")
        self._prompt.setPlaceholderText(txt)

    def _notify(self, title: str, message: str) -> None:
        if self.isActiveWindow():
            return
        try:
            from tui.notifications import notify; notify(title, message)
        except Exception:
            pass

    @Slot(str)
    def _set_status_slot(self, status: str) -> None:
        self._right_sidebar.set_status(status)

    @Slot()
    def _enable_input_slot(self) -> None:
        self._enable_input()

    def _invoke_on_main(self, slot: str, arg: str | None = None) -> None:
        """Queue a Qt slot on the main thread from any thread."""
        conn = Qt.ConnectionType.QueuedConnection
        if arg is not None:
            QMetaObject.invokeMethod(self, slot, conn, Q_ARG(str, arg))
        else:
            QMetaObject.invokeMethod(self, slot, conn)
