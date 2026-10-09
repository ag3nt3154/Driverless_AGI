"""One agent in the GUI: its bridge, conversation, slash commands, worker and turn state.

The main window owns several sessions and shows the *active* one. A session keeps the
attribute names that ``_dispatch`` (and the steer queue / Esc stop helpers) expect of the
window, so submission routing and the worker run unchanged against a session.

Everything a session renders into its own ``ConversationView`` happens whether or not it is
active, so a background agent's transcript is complete when the user switches to it. Shared
window chrome (prompt, running label, right sidebar, file viewer) is only touched while the
session is active; the window re-applies the session's state when it becomes active.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QMetaObject, QObject, Q_ARG, Qt, Signal, Slot

from agent.loop import AgentConfig

from pyside_gui import _dispatch
from pyside_gui.bridge import AgentBridge
from pyside_gui.commands import SlashCommandHandler, UIWidgets
from pyside_gui.conversation import ConversationView
from pyside_gui.overlays import CopyPicker
from pyside_gui.steer_queue import SteerQueue
from pyside_gui.utils import idle_emote_path
from agent import DAGI_ROOT


class AgentSession(QObject):
    """Per-agent state and the slots that drive its conversation."""

    state_changed = Signal(object)  # self — status, waiting flag or folder changed

    def __init__(self, win, config: AgentConfig, project_path: Path, handle: str) -> None:
        super().__init__(win)
        self.win = win
        self.handle = handle
        self._config = config
        self._project_path = project_path
        self._active_loop = None
        self._worker: threading.Thread | None = None
        self._current_loop_ref: list = []
        self._run_start_time: float | None = None
        self._restore_initial_messages: list | None = None
        self._restore_initial_affect = None
        self._pending_ask: object = None  # threading.Event; answer sink below
        self._pending_ask_container: list | None = None
        self._stream_had_content = False
        self._stream_had_reasoning = False
        self._streaming_active = False
        self._submission_seq = 0
        self._board_session = None
        self.agent_wakes = 0  # consecutive board mentions from agents (see agents_controller)
        self.status = "idle"
        self.running = False
        self._last_tokens: tuple | None = None
        self._last_context: dict | None = None
        self._model_name = config.display_name
        self._bridge = AgentBridge()
        self._conversation = ConversationView(win._verbose)
        self._copy_picker = CopyPicker(self._conversation)
        self._build_commands()
        self._connect_signals()

    # ── window chrome, reached through the session ─────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return getattr(self.win, "_active", None) is self

    @property
    def waiting(self) -> bool:
        """True while an ask_user question is waiting for the user's answer."""
        return self._pending_ask is not None

    @property
    def busy(self) -> bool:
        return bool(self._worker and self._worker.is_alive())

    @property
    def _prompt(self):
        return self.win._prompt

    @property
    def _right_sidebar(self):
        return self.win._right_sidebar

    @property
    def _left_sidebar(self):
        return self.win._left_sidebar

    @property
    def _compose_mode(self) -> bool:
        return self.win._compose_mode

    def _toggle_compose(self) -> None:
        self.win._toggle_compose()

    def close(self) -> None:
        """``exit``/``quit`` typed into any agent closes the window, as before."""
        self.win.close()

    def isActiveWindow(self) -> bool:  # noqa: N802 - mirrors QWidget for _dispatch.notify
        return self.is_active and self.win.isActiveWindow()

    # ── construction ───────────────────────────────────────────────────────────────────

    def _build_commands(self) -> None:
        widgets = UIWidgets(
            conversation=self._conversation,
            right_sidebar=self.win._right_sidebar,
            left_sidebar=self.win._left_sidebar,
        )
        handler = self._cmd_handler = SlashCommandHandler(
            widgets, self._config, self._project_path,
        )
        handler.set_worker_alive_check(lambda: self.busy)
        handler.set_on_config_changed(self._on_config_changed)
        handler.set_on_session_cleared(self._on_session_cleared)
        handler.set_desktop_pet(self.win._desktop_pet)
        handler.load_maps()
        handler.set_on_completions_changed(self._push_completions)

    def _push_completions(self) -> None:
        if self.is_active:
            self.win._prompt.set_completions(self._cmd_handler.completions())

    def _connect_signals(self) -> None:
        b, cv = self._bridge, self._conversation
        b.tool_started.connect(cv.append_tool_start)
        b.tool_ended.connect(cv.append_tool_end)
        b.assistant_text.connect(self._on_assistant_text)
        b.handoff_text.connect(cv.append_assistant)
        b.stream_started.connect(self._on_stream_started)
        b.reasoning_received.connect(self._on_reasoning)
        b.stream_text_delta.connect(lambda c: cv.stream_delta("text", c))
        b.stream_reasoning_delta.connect(lambda c: cv.stream_delta("reasoning", c))
        b.stream_ended.connect(self._on_stream_ended)
        b.token_update.connect(self._on_tokens)
        b.context_update.connect(self._on_context)
        b.compaction_started.connect(self._on_compaction_started)
        b.compaction_done.connect(self._on_compaction)
        b.model_switched.connect(self._on_model_switched)
        b.error_occurred.connect(cv.append_error)
        b.agent_done.connect(self._on_agent_done)
        b.agent_paused.connect(self._on_agent_paused)
        b.ask_user_requested.connect(self._on_ask_user)
        b.ask_user_expired.connect(self._clear_pending_ask_slot)
        b.process_state_changed.connect(self._on_process_state)
        b.continue_injected.connect(
            lambda c, m: cv.append_info(f"No exit flag — continue prompt injected ({c}/{m})")
        )
        b.subagent_event.connect(cv.append_subagent_event)
        b.show_file_requested.connect(self._on_show_file)
        b.notepad_flush_requested.connect(self.win._on_notepad_flush_requested)

    def show_welcome(self) -> None:
        subtitle = f"{self._project_path}\nType /help for commands"
        if self.handle and not self.handle.startswith("main"):
            subtitle = f"Agent {self.handle}\n{subtitle}\nUse /wd <folder> to choose its folder"
        self._conversation.show_welcome(
            f"Driverless AGI · {self._config.display_name}", subtitle,
            idle_emote_path(DAGI_ROOT),
        )

    # ── submission and worker (see _dispatch) ──────────────────────────────────────────

    def _on_input_submitted(self, submission: object) -> None:
        self.agent_wakes = 0
        _dispatch.on_input_submitted(self, submission)

    def deliver_mention(self, text: str) -> None:
        """A board @mention arrives as a user message: a new turn, or a steer while busy."""
        from agent.user_input import UserSubmission

        submission = UserSubmission(text=text)
        if self.busy:
            SteerQueue.for_window(self).submit(submission)
        else:
            self._dispatch_agent(submission)
        lines = text.splitlines()
        self._notify("Board mention", lines[1] if len(lines) > 1 else text)

    def _handle_special_command(self, result: str) -> None:
        _dispatch.handle_special_command(self, result)

    def _dispatch_agent(self, task: object) -> None:
        _dispatch.dispatch_agent(self, task)

    def _agent_work(self, task: object, callbacks: object, loop_ref: list) -> None:
        _dispatch.agent_work(self, task, callbacks, loop_ref)

    def _do_wtf(self, description: str | None) -> None:
        _dispatch.run_wtf(self, description)

    def _do_compact(self) -> None:
        if self._active_loop is None:
            self._conversation.append_info("Nothing to compact — no active conversation.")
            return
        self._conversation.append_info("Compacting context...")
        loop = self._active_loop

        def _work() -> None:
            with loop.turns.side_turn(source="gui_compact"):
                try:
                    r = loop.compact(force=True)
                except Exception as exc:
                    self._bridge.error_occurred.emit(f"Compact failed: {exc}"); return
            if r.did_compact:
                self._bridge.compaction_done.emit(len(loop.messages), r.removed_count)
        threading.Thread(target=_work, daemon=True).start()

    def stop(self) -> bool:
        """Interrupt a running turn (Esc); False when there is nothing to stop."""
        loop = self._current_loop_ref[0] if self._current_loop_ref else None
        if not self.busy or loop is None or self._pending_ask is not None:
            return False
        if not loop.interrupt():
            return False
        if self._streaming_active:
            self._streaming_active = False
            self._conversation.interrupt_stream()
        self._set_status("paused")
        self._conversation.append_info("Interrupted — type a message to continue")
        self._enable_input()
        return True

    # ── config and history ─────────────────────────────────────────────────────────────

    def _on_config_changed(self, config: AgentConfig, project_path: Path) -> None:
        self._config, self._project_path = config, project_path
        self._model_name = config.display_name
        self._active_loop = None
        if self.is_active:
            self.win._on_active_config_changed()
        self.state_changed.emit(self)

    def _on_session_cleared(self) -> None:
        self._active_loop = None; self._bridge.reset_stats()
        self._restore_initial_messages = None
        self._restore_initial_affect = None
        self._last_tokens = self._last_context = None

    def restore(self, session_data: dict) -> None:
        """Load a saved session's messages; the next prompt continues it."""
        if self.busy:
            self._conversation.append_info(
                "Cannot restore while a task is running — stop it first (Escape)."
            )
            return
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
        self._enable_input()

    # ── running state (applied to the window only while active) ────────────────────────

    def _set_status(self, status: str) -> None:
        self.status = status
        if self.is_active:
            self.win._right_sidebar.set_status(status)
        self.state_changed.emit(self)

    def _show_running(self) -> None:
        self.running = True
        self._run_start_time = time.monotonic()
        if self.is_active:
            self.win._apply_running(self)

    def _hide_running(self) -> None:
        self.running = False
        self._run_start_time = None
        if self.is_active:
            self.win._apply_running(self)

    def _enable_input(self) -> None:
        self._hide_running()
        if self.is_active:
            self.win._prompt.setDisabled(False); self.win._prompt.setFocus()

    def _notify(self, title: str, message: str) -> None:
        if not self.is_active:
            title = f"{title} ({self.handle})"
        _dispatch.notify(self, title, message)

    # ── bridge slots ───────────────────────────────────────────────────────────────────

    @Slot()
    def _on_stream_started(self) -> None:
        self._stream_had_content = False
        self._stream_had_reasoning = False
        self._streaming_active = True
        self._conversation.stream_start()

    @Slot(str, str)
    def _on_stream_ended(self, stream_text: str, stream_reasoning: str) -> None:
        _dispatch.on_stream_ended(self, stream_text, stream_reasoning)

    @Slot(str)
    def _on_reasoning(self, text: str) -> None:
        _dispatch.on_reasoning(self, text)

    @Slot(str)
    def _on_assistant_text(self, markdown: str) -> None:
        if self._stream_had_content:
            self._stream_had_content = False
            return
        self._conversation.append_assistant(markdown)

    def _on_tokens(self, *values) -> None:
        self._last_tokens = values
        if self.is_active:
            self.win._right_sidebar.update_stats(*values)

    def _on_context(self, buckets: object) -> None:
        self._last_context = buckets
        if self.is_active:
            self.win._right_sidebar.update_context(buckets)

    def _on_process_state(self, snapshot: object) -> None:
        if self.is_active:
            self.win._right_sidebar.expression_widget.update_process(snapshot)

    def _on_show_file(self, path: str, line: object) -> None:
        if self.is_active:
            self.win._left_sidebar.open_file(path, line)

    @Slot()
    def _on_compaction_started(self) -> None:
        self._set_status("compacting")

    @Slot(int, int)
    def _on_compaction(self, kept: int, removed: int) -> None:
        self._conversation.append_info(
            f"Context compacted — removed {removed} messages, kept {kept}"
        )

    @Slot(str, str)
    def _on_model_switched(self, from_name: str, to_name: str) -> None:
        self._conversation.append_info(f"Model switch: {from_name} → {to_name}")
        self._model_name = to_name
        if self.is_active:
            self.win._right_sidebar.update_model(to_name)

    @Slot(str)
    def _on_agent_done(self, result: str) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._conversation.append_info("— turn complete —")
        if result: self._notify("DAGI is done", result)
        self._enable_input()
        self.state_changed.emit(self)

    @Slot()
    def _on_agent_paused(self) -> None:
        self._pending_ask = self._pending_ask_container = None
        self._set_status("paused")
        self._conversation.append_info("Server error — session paused. Send a message to retry.")
        self._enable_input()

    @Slot(str, object, object)
    def _on_ask_user(self, question: str, data: object, _unused: object) -> None:
        options, timeout, event, container = data
        self._pending_ask, self._pending_ask_container = event, container
        self._notify("DAGI has a question", question)
        self._conversation.append_question(question, options, timeout); self._enable_input()
        self.state_changed.emit(self)

    # ── worker → main thread ───────────────────────────────────────────────────────────

    @Slot(str)
    def _set_status_slot(self, s: str) -> None: self._set_status(s)

    @Slot()
    def _enable_input_slot(self) -> None: self._enable_input()

    @Slot()
    def _clear_pending_ask_slot(self) -> None:
        self._pending_ask = self._pending_ask_container = None
        self.state_changed.emit(self)

    def _invoke_on_main(self, slot: str, arg: str | None = None) -> None:
        c = Qt.ConnectionType.QueuedConnection
        if arg is not None:
            QMetaObject.invokeMethod(self, slot, c, Q_ARG(str, arg))
        else:
            QMetaObject.invokeMethod(self, slot, c)
