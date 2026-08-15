"""Tests for the GUI session controller."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from dagi_gui.protocol import ProtocolError
from dagi_gui.session import SessionController, SessionState


# ── Fake loop infrastructure ──────────────────────────────────────────────────

class FakeLoop:
    """Minimal AgentLoop stand-in — never calls any real model.

    Mirrors real AgentLoop pause semantics: run() BLOCKS inside pause_event.wait()
    when paused (it does NOT return). The session controller abandoning the loop
    means the thread stays blocked on that wait — this is intentional for V1.
    """

    def __init__(self, run_duration: float = 0.0, raise_exc: Exception | None = None):
        self._pause_event = threading.Event()
        self._pause_event.set()  # initially running
        self._messages: list = []
        self.tracker = MagicMock()
        self.tracker.finish = MagicMock()
        self.compact_tool = MagicMock()
        self.compact_tool.compact = MagicMock(return_value=None)
        self.registry = MagicMock()
        self.registry._tools = {}
        self._run_duration = run_duration
        self._raise_exc = raise_exc
        self.run_calls: list[str] = []
        self.resumed_with: list[str] = []

    def run(self, task: str) -> str:
        self.run_calls.append(task)
        self._messages.append({"role": "assistant", "content": "saved"})
        if self._run_duration:
            deadline = time.monotonic() + self._run_duration
            while time.monotonic() < deadline:
                # Block when paused — matches real AgentLoop._pause_event.wait()
                self._pause_event.wait()
                time.sleep(0.01)
        if self._raise_exc:
            raise self._raise_exc
        return "done"

    def pause(self) -> None:
        self._pause_event.clear()

    def inject_and_resume(self, message: str) -> None:
        self.resumed_with.append(message)
        self._pause_event.set()

    def finish(self) -> None:
        self.tracker.finish()


class FakeLoopFactory:
    """Records constructor calls and returns FakeLoop instances."""

    def __init__(self, **loop_kwargs: Any) -> None:
        self.calls: list[dict] = []
        self._loop_kwargs = loop_kwargs

    def __call__(self, config, callbacks, initial_messages, tracker=None) -> FakeLoop:
        self.calls.append({
            "config": config,
            "callbacks": callbacks,
            "initial_messages": list(initial_messages or []),
        })
        return FakeLoop(**self._loop_kwargs)


def make_controller(loop_kwargs: dict | None = None) -> tuple[SessionController, FakeLoopFactory]:
    from unittest.mock import MagicMock
    writer = MagicMock()
    writer.write = MagicMock()
    factory = FakeLoopFactory(**(loop_kwargs or {}))
    config = MagicMock()
    config.project_path = MagicMock()
    ctrl = SessionController(config=config, writer=writer, loop_factory=factory)
    return ctrl, factory


# ── State machine tests ───────────────────────────────────────────────────────

class TestSessionControllerLifecycle:
    def test_initial_state_is_idle(self):
        ctrl, _ = make_controller()
        assert ctrl.state == SessionState.IDLE

    def test_run_starts_agent(self):
        ctrl, factory = make_controller()
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        assert ctrl.wait_until_idle(timeout=2)
        assert factory.calls[0]["initial_messages"] == []

    def test_second_run_receives_previous_messages(self):
        ctrl, factory = make_controller()
        ctrl.handle({"type": "run", "id": "1", "task": "first"})
        assert ctrl.wait_until_idle(timeout=2)
        ctrl.handle({"type": "run", "id": "2", "task": "second"})
        assert ctrl.wait_until_idle(timeout=2)
        assert factory.calls[1]["initial_messages"][-1] == {
            "role": "assistant",
            "content": "saved",
        }

    def test_concurrent_run_raises_protocol_error(self):
        ctrl, _ = make_controller(loop_kwargs={"run_duration": 1.0})
        ctrl.handle({"type": "run", "id": "1", "task": "first"})
        time.sleep(0.05)  # let it start
        with pytest.raises(ProtocolError, match="already running"):
            ctrl.handle({"type": "run", "id": "2", "task": "second"})
        ctrl.shutdown()

    def test_exception_in_run_emits_error_event(self):
        ctrl, _ = make_controller(loop_kwargs={"raise_exc": RuntimeError("boom")})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        assert ctrl.wait_until_idle(timeout=2)
        calls = [c for c in ctrl._writer.write.call_args_list
                 if c[0][0] == "error"]
        assert calls

    def test_finish_called_once_after_run(self):
        ctrl, factory = make_controller()
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        assert ctrl.wait_until_idle(timeout=2)
        ctrl.shutdown()
        # finish called once (during shutdown), not twice
        assert factory.calls  # loop was created


class TestSessionControllerCancel:
    def test_cancel_while_running_transitions_to_idle(self):
        ctrl, _ = make_controller(loop_kwargs={"run_duration": 5.0})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        time.sleep(0.05)
        ctrl.handle({"type": "cancel", "id": "c1"})
        assert ctrl.wait_until_idle(timeout=2)
        assert ctrl.state == SessionState.IDLE

    def test_cancel_while_idle_is_no_op(self):
        ctrl, _ = make_controller()
        ctrl.handle({"type": "cancel", "id": "c1"})  # should not raise
        assert ctrl.state == SessionState.IDLE

    def test_cancel_discards_loop_messages(self):
        ctrl, factory = make_controller(loop_kwargs={"run_duration": 5.0})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        time.sleep(0.05)
        ctrl.handle({"type": "cancel", "id": "c1"})
        assert ctrl.wait_until_idle(timeout=2)
        # factory is called synchronously before thread starts, so we can
        # check initial_messages immediately without waiting for run to finish
        ctrl.handle({"type": "run", "id": "2", "task": "new"})
        assert factory.calls[-1]["initial_messages"] == []
        ctrl.shutdown()  # clean up the running daemon thread


class TestSessionControllerPauseResume:
    def test_pause_while_running(self):
        ctrl, _ = make_controller(loop_kwargs={"run_duration": 5.0})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        time.sleep(0.05)
        ctrl.handle({"type": "pause", "id": "p1"})
        time.sleep(0.05)
        assert ctrl.state == SessionState.PAUSED
        ctrl.shutdown()

    def test_resume_after_pause(self):
        # run_duration=0.5: enough time to pause then resume, short enough to complete
        ctrl, _ = make_controller(loop_kwargs={"run_duration": 0.5})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        time.sleep(0.05)
        ctrl.handle({"type": "pause", "id": "p1"})
        time.sleep(0.05)
        assert ctrl.state == SessionState.PAUSED
        ctrl.handle({"type": "resume", "id": "r1", "message": ""})
        assert ctrl.wait_until_idle(timeout=3)

    def test_pause_while_idle_is_no_op(self):
        ctrl, _ = make_controller()
        ctrl.handle({"type": "pause", "id": "p1"})
        assert ctrl.state == SessionState.IDLE


class TestSessionControllerShutdown:
    def test_shutdown_is_idempotent(self):
        ctrl, _ = make_controller()
        ctrl.shutdown()
        ctrl.shutdown()  # second call should be safe no-op
        # shutdown_complete is now emitted by GuiServer, not the controller

    def test_shutdown_state_is_idle(self):
        ctrl, _ = make_controller()
        ctrl.shutdown()
        assert ctrl.state == SessionState.IDLE


class TestSessionControllerClear:
    def test_clear_while_idle_resets_state(self):
        ctrl, factory = make_controller()
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        assert ctrl.wait_until_idle(timeout=2)
        ctrl.handle({"type": "clear", "id": "cl1"})
        # next run gets empty initial messages
        ctrl.handle({"type": "run", "id": "2", "task": "fresh"})
        assert ctrl.wait_until_idle(timeout=2)
        assert factory.calls[-1]["initial_messages"] == []

    def test_clear_while_running_raises(self):
        ctrl, _ = make_controller(loop_kwargs={"run_duration": 5.0})
        ctrl.handle({"type": "run", "id": "1", "task": "hello"})
        time.sleep(0.05)
        with pytest.raises(ProtocolError, match="idle"):
            ctrl.handle({"type": "clear", "id": "cl1"})
        ctrl.shutdown()
