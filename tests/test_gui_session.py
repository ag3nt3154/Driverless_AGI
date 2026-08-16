from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from agent.loop import AgentConfig
from dagi_gui.interaction import QuestionBroker
from dagi_gui.protocol import ProtocolError
from dagi_gui.session import SessionController


class RecordingWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def write(self, event_type: str, **payload: object) -> None:
        self.events.append({"type": event_type, **payload})


class FakeCompactTool:
    def __init__(self) -> None:
        self.forced = False

    def compact(self, force: bool = False) -> object:
        self.forced = force
        return SimpleNamespace(did_compact=False)


class FakeBash:
    def __init__(self) -> None:
        self.killed = False

    def force_kill(self) -> None:
        self.killed = True


class FakeLoop:
    def __init__(self, config, callbacks, initial_messages, tracker, block: bool = False, fail: bool = False):
        self.callbacks = callbacks
        self.initial_messages = initial_messages
        self.tracker = tracker or object()
        self._messages = initial_messages or [{"role": "system", "content": "fresh"}]
        self.bash = FakeBash()
        self.registry = SimpleNamespace(_tools={"bash": self.bash})
        self.compact_tool = FakeCompactTool()
        self.paused = False
        self.finished = 0
        self.injected: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block
        self.fail = fail

    def compact(self, force: bool = False) -> object:
        """Mirrors AgentLoop.compact — the funnel that also logs the replace."""
        return self.compact_tool.compact(force=force)

    def run(self, task: str) -> str:
        self.started.set()
        if self.fail:
            raise RuntimeError("loop failed")
        if self.block:
            self.release.wait(timeout=1)
        self._messages.append({"role": "assistant", "content": "saved"})
        return "saved"

    def pause(self) -> None:
        self.paused = True

    def inject_and_resume(self, message: str) -> None:
        self.injected.append(message)
        self.release.set()

    def finish(self) -> None:
        self.finished += 1


class FakeLoopFactory:
    def __init__(self, **kwargs: bool) -> None:
        self.kwargs = kwargs
        self.calls: list[FakeLoop] = []

    def __call__(self, config, callbacks, initial_messages, tracker) -> FakeLoop:
        loop = FakeLoop(config, callbacks, initial_messages, tracker, **self.kwargs)
        self.calls.append(loop)
        return loop


@pytest.fixture
def setup_controller(tmp_path):
    writer = RecordingWriter()
    broker = QuestionBroker(writer)
    factory = FakeLoopFactory()
    controller = SessionController(AgentConfig(project_path=tmp_path), writer, broker, factory)
    return controller, writer, broker, factory


def test_second_turn_receives_previous_messages(setup_controller) -> None:
    controller, _, _, factory = setup_controller

    controller.handle({"type": "run", "task": "first"})
    assert controller.wait_until_idle(1)
    controller.handle({"type": "run", "task": "second"})
    assert controller.wait_until_idle(1)

    assert factory.calls[1].initial_messages[-1] == {"role": "assistant", "content": "saved"}


def test_rejects_second_run_while_agent_is_active(tmp_path) -> None:
    writer = RecordingWriter()
    factory = FakeLoopFactory(block=True)
    controller = SessionController(AgentConfig(project_path=tmp_path), writer, QuestionBroker(writer), factory)

    controller.handle({"type": "run", "task": "first"})
    assert factory.calls[0].started.wait(1)
    with pytest.raises(ProtocolError, match="agent is already running"):
        controller.handle({"type": "run", "task": "second"})

    factory.calls[0].release.set()
    assert controller.wait_until_idle(1)


def test_pause_kills_active_bash_and_resumes(tmp_path, monkeypatch) -> None:
    writer = RecordingWriter()
    factory = FakeLoopFactory(block=True)
    controller = SessionController(AgentConfig(project_path=tmp_path), writer, QuestionBroker(writer), factory)
    killed_subagents: list[bool] = []
    monkeypatch.setattr("dagi_gui.session.force_kill_active_subagents", lambda: killed_subagents.append(True))

    controller.handle({"type": "run", "task": "first"})
    assert factory.calls[0].started.wait(1)
    controller.handle({"type": "pause"})

    assert factory.calls[0].bash.killed is True
    assert factory.calls[0].paused is True
    assert killed_subagents == [True]
    controller.handle({"type": "resume", "message": "continue"})
    assert factory.calls[0].injected == ["continue"]
    assert controller.wait_until_idle(1)


def test_pause_is_ignored_while_question_is_pending(tmp_path) -> None:
    writer = RecordingWriter()
    broker = QuestionBroker(writer)
    factory = FakeLoopFactory(block=True)
    controller = SessionController(AgentConfig(project_path=tmp_path), writer, broker, factory)
    controller.handle({"type": "run", "task": "first"})
    assert factory.calls[0].started.wait(1)
    broker._pending = SimpleNamespace(question_id="q", default_answer="", answer=None)

    controller.handle({"type": "pause"})

    assert factory.calls[0].paused is False
    factory.calls[0].release.set()
    assert controller.wait_until_idle(1)


def test_loop_exception_emits_error_and_finishes_once(tmp_path) -> None:
    writer = RecordingWriter()
    factory = FakeLoopFactory(fail=True)
    controller = SessionController(AgentConfig(project_path=tmp_path), writer, QuestionBroker(writer), factory)

    controller.handle({"type": "run", "task": "first"})
    assert controller.wait_until_idle(1)

    assert {"type": "error", "message": "loop failed"} in writer.events
    assert factory.calls[0].finished == 1


def test_clear_and_compact_require_idle(setup_controller) -> None:
    controller, _, _, factory = setup_controller

    controller.handle({"type": "run", "task": "first"})
    assert controller.wait_until_idle(1)
    controller.handle({"type": "compact"})
    deadline = time.monotonic() + 1
    while not factory.calls[0].compact_tool.forced and time.monotonic() < deadline:
        time.sleep(0.005)
    assert factory.calls[0].compact_tool.forced is True
    controller.handle({"type": "clear"})
    assert controller.active_loop is None
