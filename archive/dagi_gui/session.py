"""Python-owned session lifecycle for the desktop GUI sidecar."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from tools._subagent_runner import force_kill_active_subagents

from .callbacks import build_gui_callbacks
from .interaction import QuestionBroker
from .protocol import EventWriter as EventSink
from .protocol import ProtocolError


class LoopFactory(Protocol):
    """Construct an AgentLoop-compatible object for a GUI turn."""

    def __call__(
        self,
        config: AgentConfig,
        callbacks: AgentCallbacks,
        initial_messages: list | None,
        tracker: object | None,
    ) -> AgentLoop:
        """Create the next loop."""


class SessionController:
    """Coordinate one resumable AgentLoop for a desktop window."""

    def __init__(
        self,
        config: AgentConfig,
        writer: EventSink,
        broker: QuestionBroker | None = None,
        loop_factory: LoopFactory | None = None,
    ) -> None:
        self.config = config
        self.writer = writer
        self.broker = broker or QuestionBroker(writer)
        self._loop_factory = loop_factory or self._create_loop
        self._lock = threading.RLock()
        self._active_loop: AgentLoop | None = None
        self._worker: threading.Thread | None = None
        self._restore_messages: list | None = None
        self._state = "idle"
        self._finished_loops: set[int] = set()
        self.callbacks = build_gui_callbacks(writer, self.broker)
        base_on_pause = self.callbacks.on_pause

        def on_pause() -> None:
            self._set_state("paused")
            base_on_pause()

        self.callbacks.on_pause = on_pause

    @property
    def active_loop(self) -> AgentLoop | None:
        """Return the loop holding the current conversation context."""
        with self._lock:
            return self._active_loop

    @property
    def state(self) -> str:
        """Return the current lifecycle state."""
        with self._lock:
            return self._state

    def handle(self, command: dict[str, object]) -> object:
        """Dispatch one already-validated sidecar command."""
        command_type = command.get("type")
        handlers: dict[str, Callable[[dict[str, object]], object]] = {
            "run": self._handle_run,
            "cancel": self._handle_cancel,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "answer_question": self._handle_answer,
            "clear": self._handle_clear,
            "compact": self._handle_compact,
            "shutdown": self._handle_shutdown,
        }
        handler = handlers.get(command_type) if isinstance(command_type, str) else None
        if handler is None:
            raise ProtocolError(f"unsupported session command: {command_type}")
        return handler(command)

    def wait_until_idle(self, timeout: float) -> bool:
        """Wait for the active worker to finish without holding the state lock."""
        with self._lock:
            worker = self._worker
        if worker is None:
            return self.state == "idle"
        worker.join(timeout)
        return not worker.is_alive() and self.state == "idle"

    def shutdown(self) -> None:
        """Stop active work and finalize the active loop once."""
        self._handle_shutdown({"type": "shutdown"})

    def _handle_run(self, command: dict[str, object]) -> dict[str, str]:
        task = command.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ProtocolError("run task must be a non-empty string")
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ProtocolError("agent is already running")
            initial_messages = self._restore_messages
            tracker = None
            if initial_messages is None and self._active_loop is not None:
                initial_messages = self._active_loop._messages
                tracker = self._active_loop.tracker
            self._restore_messages = None
            loop = self._loop_factory(self.config, self.callbacks, initial_messages, tracker)
            self._active_loop = loop
            self._state = "running"
            self._worker = threading.Thread(target=self._run_loop, args=(loop, task), daemon=True)
            self._worker.start()
        self.writer.write("status", status="running")
        return {"status": "running"}

    def _handle_cancel(self, _command: dict[str, object]) -> dict[str, str]:
        with self._lock:
            loop = self._active_loop
            if loop is None or self._state not in ("running", "paused"):
                return {"status": self._state}
            self._kill_active_work(loop)
            loop.pause()
            self._state = "idle"
        self.writer.write("task_complete")
        return {"status": "idle"}

    def _handle_answer(self, command: dict[str, object]) -> dict[str, str]:
        qid = command.get("question_id")
        answer = command.get("answer")
        if not isinstance(qid, str) or not isinstance(answer, str):
            raise ProtocolError("answer_question needs question_id and answer")
        self.broker.answer(qid, answer)
        return {"status": "running"}

    def _handle_pause(self, _command: dict[str, object]) -> dict[str, str]:
        with self._lock:
            loop = self._active_loop
            if self._state != "running" or loop is None or self.broker.has_pending:
                return {"status": self._state}
            self._kill_active_work(loop)
            loop.pause()
            self._state = "paused"
        self.writer.write("status", status="paused")
        return {"status": "paused"}

    def _handle_resume(self, command: dict[str, object]) -> dict[str, str]:
        message = command.get("message")
        if not isinstance(message, str):
            raise ProtocolError("resume message must be a string")
        with self._lock:
            loop = self._active_loop
            if self._state != "paused" or loop is None:
                raise ProtocolError("agent is not paused")
            loop.inject_and_resume(message)
            self._state = "running"
        self.writer.write("status", status="running")
        return {"status": "running"}

    def _handle_clear(self, _command: dict[str, object]) -> dict[str, str]:
        self._require_idle()
        with self._lock:
            self._active_loop = None
            self._restore_messages = None
            self._state = "idle"
        self.writer.write("session_cleared")
        return {"status": "idle"}

    def _handle_compact(self, _command: dict[str, object]) -> dict[str, str]:
        self._require_idle()
        with self._lock:
            loop = self._active_loop
        if loop is None:
            raise ProtocolError("no active session")
        threading.Thread(target=self._compact_loop, args=(loop,), daemon=True).start()
        return {"status": "compacting"}

    def _handle_shutdown(self, _command: dict[str, object]) -> dict[str, str]:
        with self._lock:
            loop = self._active_loop
            self._state = "stopping"
            if loop is not None:
                self._kill_active_work(loop)
                loop.pause()
                self._resolve_pending_question()
                self._finish_loop(loop)
            worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        with self._lock:
            self._state = "idle"
        self.writer.write("shutdown_complete")
        return {"status": "idle"}

    def _run_loop(self, loop: AgentLoop, task: str) -> None:
        try:
            loop.run(task)
        except Exception as exc:
            self.callbacks.on_error(exc)
        finally:
            self._finish_loop(loop)
            with self._lock:
                if self._state != "stopping":
                    self._state = "idle"
            self.writer.write("status", status="idle")

    def _compact_loop(self, loop: AgentLoop) -> None:
        try:
            loop.compact(force=True)
        except Exception as exc:
            self.callbacks.on_error(exc)

    def _create_loop(
        self,
        config: AgentConfig,
        callbacks: AgentCallbacks,
        initial_messages: list | None,
        tracker: object | None,
    ) -> AgentLoop:
        return AgentLoop(config, callbacks, initial_messages=initial_messages, _tracker=tracker)

    def _require_idle(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise ProtocolError("agent is already running")

    def _kill_active_work(self, loop: AgentLoop) -> None:
        bash_tool = loop.registry._tools.get("bash")
        if bash_tool is not None:
            bash_tool.force_kill()
        force_kill_active_subagents()

    def _resolve_pending_question(self) -> None:
        self.broker.resolve_default()

    def _finish_loop(self, loop: AgentLoop) -> None:
        loop_id = id(loop)
        with self._lock:
            if loop_id in self._finished_loops:
                return
            self._finished_loops.add(loop_id)
        loop.finish()

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
