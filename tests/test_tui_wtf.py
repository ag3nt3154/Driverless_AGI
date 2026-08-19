"""TUI behavior for the inherited, read-only ``/wtf`` diagnostic."""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from tui.app import DagiApp
from tui.commands import SlashCommandsMixin
from tui.conversation import ConversationPane
from tui.prompt_input import PromptInput
from tui.sidebar import Sidebar
from tui.utils import _SLASH_HELP


class _Conversation:
    def __init__(self) -> None:
        self.info: list[str] = []
        self.errors: list[str] = []

    def append_info(self, message: str) -> None:
        self.info.append(message)

    def append_error(self, message: str) -> None:
        self.errors.append(message)


class _Sidebar:
    def __init__(self) -> None:
        self.statuses: list[str] = []

    def set_status(self, status: str) -> None:
        self.statuses.append(status)


class _Prompt:
    disabled = False


class _Thread:
    def __init__(self, target, daemon: bool) -> None:
        self._target = target
        self.daemon = daemon
        self.started = False
        self._alive = False

    def start(self) -> None:
        self.started = True
        self._alive = True
        self._target()
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive


class _ParentWorker:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _Loop:
    def __init__(self, *, paused: bool, checkpoint: bool = True, result=None, error=None) -> None:
        self._pause_event = threading.Event()
        if not paused:
            self._pause_event.set()
        self.checkpoint = checkpoint
        self.result = result
        self.error = error
        self.waited_for: list[float] = []
        self.run_calls: list[str | None] = []

    def wait_for_pause_checkpoint(self, timeout: float) -> bool:
        self.waited_for.append(timeout)
        return self.checkpoint

    def run_wtf(self, description: str | None):
        self.run_calls.append(description)
        if self.error:
            raise self.error
        return self.result


class _App(SlashCommandsMixin):
    def __init__(self, loop=None, *, worker_alive: bool = False) -> None:
        self.conv = _Conversation()
        self.sidebar = _Sidebar()
        self.prompt = _Prompt()
        self._active_loop = loop
        self._worker = _ParentWorker(worker_alive) if worker_alive else None
        self._current_loop_ref = [loop] if loop is not None else []
        self._wtf_running = False
        self._wtf_worker = None
        self.running_shown = 0
        self.running_hidden = 0
        self.input_enabled = 0
        self._skill_map = {}
        self._workflow_map = {}

    def query_one(self, selector, *_args):
        if selector is ConversationPane:
            return self.conv
        if selector is Sidebar:
            return self.sidebar
        if selector == "#prompt" or selector is PromptInput:
            return self.prompt
        raise AssertionError(f"Unexpected query: {selector!r}")

    def call_from_thread(self, callback, *args) -> None:
        callback(*args)

    def _show_running_indicator(self) -> None:
        self.running_shown += 1

    def _hide_running_indicator(self) -> None:
        self.running_hidden += 1

    def _enable_input(self) -> None:
        self.input_enabled += 1
        self.prompt.disabled = False


def test_slash_dispatches_wtf_with_and_without_a_description() -> None:
    """Dropping the argument would make a specific diagnostic hint unusable."""
    app = _App()
    received: list[str | None] = []
    app._cmd_wtf = received.append

    app._handle_slash("/wtf")
    app._handle_slash("/wtf inspect the failed startup")

    assert received == [None, "inspect the failed startup"]


def test_prompt_intercepts_paused_wtf_without_resuming_parent() -> None:
    """Routing a paused ``/wtf`` through injected input would resume the parent loop."""
    loop = SimpleNamespace(_pause_event=threading.Event(), inject_and_resume=lambda _raw: None)
    app = SimpleNamespace(
        _input_expanded=False,
        _pending_ask=None,
        _worker=_ParentWorker(True),
        _current_loop_ref=[loop],
        handled=[],
    )
    app._handle_slash = app.handled.append
    app.action_toggle_compose = lambda: None

    DagiApp.on_prompt_input_submitted(app, SimpleNamespace(value="/wtf\tinspect this"))

    assert app.handled == ["/wtf\tinspect this"]


def test_wtf_without_an_active_loop_does_not_start_a_worker(monkeypatch) -> None:
    """A header-only TUI has no parent context for a diagnostic child."""
    app = _App()
    started: list[bool] = []
    monkeypatch.setattr("tui.commands.threading.Thread", lambda **_kwargs: started.append(True))

    app._cmd_wtf(None)

    assert started == []
    assert "Nothing to diagnose" in app.conv.info[-1]


def test_wtf_rejects_a_second_diagnosis_while_one_is_active(monkeypatch) -> None:
    """A second child could race the first to append incompatible parent references."""
    loop = _Loop(paused=False)
    app = _App(loop)
    app._wtf_running = True
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)

    app._cmd_wtf("repeat")

    assert loop.run_calls == []
    assert "already running" in app.conv.info[-1]


def test_wtf_requires_pause_before_diagnosing_a_running_parent(monkeypatch) -> None:
    """Forking a moving parent context would bind the report to the wrong state."""
    loop = _Loop(paused=False)
    app = _App(loop, worker_alive=True)
    started: list[bool] = []
    monkeypatch.setattr("tui.commands.threading.Thread", lambda **_kwargs: started.append(True))

    app._cmd_wtf("still moving")

    assert started == []
    assert loop.run_calls == []
    assert "press ESC" in app.conv.info[-1]


def test_paused_wtf_times_out_without_resuming_parent(monkeypatch) -> None:
    """A diagnosis before the pause checkpoint would fork an unsafe parent surface."""
    loop = _Loop(paused=True, checkpoint=False)
    app = _App(loop, worker_alive=True)
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)

    app._cmd_wtf("stuck")

    assert loop.waited_for
    assert loop.run_calls == []
    assert not loop._pause_event.is_set()
    assert app.sidebar.statuses == ["running", "paused"]
    assert app.prompt.disabled is False
    assert "checkpoint" in app.conv.errors[-1].lower()


def test_successful_paused_wtf_restores_the_paused_tui_state(monkeypatch, tmp_path: Path) -> None:
    """Finishing a child diagnosis must not make the parent loop look or act resumed."""
    result = SimpleNamespace(description="Paused safely.", report_path=tmp_path / "report.md")
    loop = _Loop(paused=True, result=result)
    app = _App(loop, worker_alive=True)
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)

    app._cmd_wtf(None)

    assert loop.waited_for
    assert not loop._pause_event.is_set()
    assert app.sidebar.statuses == ["running", "paused"]
    assert app.prompt.disabled is False


def test_wtf_renders_only_safe_result_fields(monkeypatch, tmp_path: Path) -> None:
    """Displaying the handoff body would leak unreviewed error and fix text into the TUI."""
    report = tmp_path / "nested" / "diagnosis.md"
    result = SimpleNamespace(
        description="The config path is missing.",
        report_path=report,
        error_report="private stack trace",
        suggested_fix="do not show this",
    )
    loop = _Loop(paused=False, result=result)
    app = _App(loop)
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)

    app._cmd_wtf("config failure")

    output = app.conv.info[-1]
    assert "The config path is missing." in output
    assert str(report.resolve()) in output
    assert "private stack trace" not in output
    assert "do not show this" not in output
    assert loop.run_calls == ["config failure"]
    assert app.sidebar.statuses == ["running", "idle"]


def test_wtf_failure_restores_the_idle_tui_state(monkeypatch) -> None:
    """A failed child must not leave an otherwise idle prompt disabled or marked running."""
    loop = _Loop(paused=False, error=RuntimeError("child failed"))
    app = _App(loop)
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)

    app._cmd_wtf(None)

    assert app.conv.errors == ["/wtf failed: child failed"]
    assert app.sidebar.statuses == ["running", "idle"]
    assert app.prompt.disabled is False
    assert app._wtf_running is False


def test_wtf_completion_hides_spinner_on_success_and_failure(monkeypatch, tmp_path) -> None:
    """Every terminal path must explicitly tear down the /wtf running indicator."""
    monkeypatch.setattr("tui.commands.threading.Thread", _Thread)
    success = _App(
        _Loop(
            paused=False,
            result=SimpleNamespace(description="done", report_path=tmp_path / "report.md"),
        )
    )
    failure = _App(_Loop(paused=False, error=RuntimeError("failed")))

    success._cmd_wtf(None)
    failure._cmd_wtf(None)

    assert success.running_hidden == 1
    assert failure.running_hidden == 1


def test_help_lists_wtf() -> None:
    """Without a help entry, the diagnostic command remains undiscoverable."""
    assert _SLASH_HELP["/wtf"] == "Diagnose the active conversation  (/wtf [description])"
