"""GUI session controller — owns one AgentLoop and its lifecycle."""

from __future__ import annotations

import threading
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable

from dagi_gui.callbacks import build_gui_callbacks
from dagi_gui.interaction import QuestionBroker
from dagi_gui.protocol import EventWriter, ProtocolError

if TYPE_CHECKING:
    from agent.config_loader import AgentConfig


class SessionState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    ERROR = auto()
    STOPPING = auto()


# Allowed state transitions
_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.IDLE: {SessionState.RUNNING, SessionState.STOPPING},
    SessionState.RUNNING: {SessionState.PAUSED, SessionState.IDLE, SessionState.ERROR},
    SessionState.PAUSED: {SessionState.RUNNING, SessionState.IDLE},
    SessionState.ERROR: {SessionState.IDLE},
    SessionState.STOPPING: set(),
}

_IDLE_ONLY_COMMANDS = {"compact", "clear", "set_model", "set_project", "shutdown"}


def _default_loop_factory(
    config: "AgentConfig",
    callbacks: Any,
    initial_messages: list,
    tracker: Any = None,
) -> Any:
    from agent.loop import AgentLoop
    return AgentLoop(config=config, callbacks=callbacks, initial_messages=initial_messages)


class SessionController:
    """Manages the lifecycle of a single AgentLoop for one desktop window.

    Thread safety: all state mutations are guarded by _lock (RLock).
    _lock is never held during loop.run() to avoid deadlocking callbacks.
    """

    def __init__(
        self,
        config: "AgentConfig",
        writer: EventWriter,
        loop_factory: Callable | None = None,
    ) -> None:
        self._config = config
        self._writer = writer
        self._loop_factory = loop_factory or _default_loop_factory
        self._lock = threading.RLock()
        self._idle_event = threading.Event()
        self._idle_event.set()

        self._state = SessionState.IDLE
        self._loop: Any | None = None
        self._run_thread: threading.Thread | None = None
        self._saved_messages: list = []
        self._broker = QuestionBroker(writer)
        self._shutdown_done = False

    @property
    def state(self) -> SessionState:
        with self._lock:
            return self._state

    def _transition(self, new_state: SessionState) -> None:
        allowed = _TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise ProtocolError(
                f"invalid transition {self._state.name} → {new_state.name}"
            )
        self._state = new_state
        if new_state == SessionState.IDLE:
            self._idle_event.set()
        else:
            self._idle_event.clear()

    def handle(self, command: dict) -> object:
        """Dispatch a validated protocol command. Returns the result payload."""
        cmd_type = command.get("type")
        with self._lock:
            if cmd_type in _IDLE_ONLY_COMMANDS and self._state != SessionState.IDLE:
                raise ProtocolError(
                    f"{cmd_type} requires idle state (currently {self._state.name})"
                )

        dispatch = {
            "run": self._handle_run,
            "cancel": self._handle_cancel,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "answer_question": self._handle_answer_question,
            "compact": self._handle_compact,
            "clear": self._handle_clear,
            "shutdown": self._handle_shutdown,
        }
        handler = dispatch.get(cmd_type)
        if handler:
            return handler(command)
        return {}

    # ── Command handlers ──────────────────────────────────────────────────────

    def _handle_run(self, command: dict) -> dict:
        task = command.get("task", "")
        with self._lock:
            if self._state == SessionState.RUNNING:
                raise ProtocolError("agent is already running")
            initial = list(self._saved_messages)
            callbacks = build_gui_callbacks(self._writer, self._broker)
            loop = self._loop_factory(
                self._config, callbacks, initial
            )
            self._loop = loop
            self._transition(SessionState.RUNNING)
            t = threading.Thread(
                target=self._run_agent, args=(loop, task), daemon=True
            )
            self._run_thread = t
        t.start()
        return {}

    def _run_agent(self, loop: Any, task: str) -> None:
        try:
            loop.run(task)
            with self._lock:
                # Preserve messages for next turn only if this loop is still current
                if self._loop is loop:
                    self._saved_messages = list(loop._messages)
                    self._transition(SessionState.IDLE)
        except Exception as exc:
            with self._lock:
                self._writer.write("error", message=str(exc))
                if self._loop is loop:
                    self._transition(SessionState.ERROR)
                    self._transition(SessionState.IDLE)
        finally:
            with self._lock:
                if self._loop is loop:
                    try:
                        loop.finish()
                    except Exception:
                        pass

    def _handle_cancel(self, command: dict) -> dict:
        with self._lock:
            if self._state not in (SessionState.RUNNING, SessionState.PAUSED):
                return {}
            self._kill_active_processes()
            if self._loop:
                self._loop.pause()
            # Abandon this loop — next run creates a fresh one
            self._loop = None
            self._saved_messages = []
            self._transition(SessionState.IDLE)
        return {}

    def _handle_pause(self, command: dict) -> dict:
        with self._lock:
            if self._state != SessionState.RUNNING:
                return {}
            if self._broker.has_pending():
                return {}
            self._kill_active_processes()
            if self._loop:
                self._loop.pause()
            self._transition(SessionState.PAUSED)
        return {}

    def _handle_resume(self, command: dict) -> dict:
        message = command.get("message", "")
        with self._lock:
            if self._state != SessionState.PAUSED:
                raise ProtocolError("agent is not paused")
            if self._loop:
                self._loop.inject_and_resume(message)
            self._transition(SessionState.RUNNING)
        return {}

    def _handle_answer_question(self, command: dict) -> dict:
        question_id = command.get("question_id", "")
        answer = command.get("answer", "")
        self._broker.answer(question_id, answer)
        return {}

    def _handle_compact(self, command: dict) -> dict:
        if self._loop:
            self._loop.compact_tool.compact(force=True)
        return {}

    def _handle_clear(self, command: dict) -> dict:
        self._saved_messages = []
        self._loop = None
        return {}

    def _handle_shutdown(self, command: dict) -> dict:
        self._shutdown()
        return {}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _kill_active_processes(self) -> None:
        """Kill running bash and subagents. Must be called with _lock held."""
        if self._loop:
            bash = getattr(self._loop.registry, "_tools", {}).get("bash")
            if bash is not None:
                try:
                    bash.force_kill()
                except Exception:
                    pass
        try:
            from tools._subagent_runner import force_kill_active_subagents
            force_kill_active_subagents()
        except Exception:
            pass

    def _shutdown(self) -> None:
        with self._lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
            self._broker.resolve_default()
            if self._state in (SessionState.RUNNING, SessionState.PAUSED):
                self._kill_active_processes()
                if self._loop:
                    self._loop.pause()
                self._loop = None
                self._saved_messages = []
                self._state = SessionState.IDLE
                self._idle_event.set()
            if self._loop:
                try:
                    self._loop.finish()
                except Exception:
                    pass

    def shutdown(self) -> None:
        """Public shutdown — safe to call multiple times."""
        self._shutdown()

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        """Block until state is IDLE or STOPPING. Returns True if idle reached."""
        return self._idle_event.wait(timeout=timeout)
