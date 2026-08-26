"""A pending ``ask_user`` question must never outlive the worker that raised it.

An ``ask_user`` call whose safety timeout expires leaves the worker running
again while the TUI still holds the question's answer sink. If that sink
survives the end of the turn, the next thing the user types is posted into a
dead ``threading.Event`` instead of starting a task: the running indicator is
shown, the prompt is disabled, and no worker exists — a hang with a ticking
timer and a process state stuck at ``idle``.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

from tui.app import DagiApp
from tui.conversation import ConversationPane
from tui.prompt_input import PromptInput
from tui.sidebar import Sidebar


class _Conversation:
    def __init__(self) -> None:
        self.written: list = []
        self.errors: list[str] = []

    def write(self, renderable) -> None:
        self.written.append(renderable)

    def append_error(self, message: str) -> None:
        self.errors.append(message)


class _Prompt:
    disabled = False


class _Worker:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _submit_app(*, worker_alive: bool, pending) -> SimpleNamespace:
    app = SimpleNamespace(
        _input_expanded=False,
        _pending_ask=pending,
        _worker=_Worker(worker_alive),
        _wtf_worker=None,
        _current_loop_ref=[],
        conv=_Conversation(),
        prompt=_Prompt(),
        dispatched=[],
        slashed=[],
        running_shown=0,
    )
    app.query_one = lambda selector, *_a: (
        app.conv if selector is ConversationPane else app.prompt
    )
    app._dispatch_agent = app.dispatched.append
    app._handle_slash = app.slashed.append
    app.action_toggle_compose = lambda: None

    def _show_running() -> None:
        app.running_shown += 1

    app._show_running_indicator = _show_running
    app._ask_is_live = lambda: DagiApp._ask_is_live(app)
    return app


def test_stale_pending_ask_does_not_swallow_the_next_task() -> None:
    """Answering a dead question starts no worker — the timer runs over nothing."""
    evt, container = threading.Event(), []
    app = _submit_app(worker_alive=False, pending=(evt, container, [], None))

    DagiApp.on_prompt_input_submitted(app, SimpleNamespace(value="next task"))

    assert app.dispatched == ["next task"]
    assert container == []
    assert not evt.is_set()
    assert app.running_shown == 0  # _dispatch_agent owns the indicator
    assert app._pending_ask is None


def test_stale_pending_ask_still_routes_slash_commands() -> None:
    """A stale sink must not eat ``/`` commands either."""
    app = _submit_app(worker_alive=False, pending=(threading.Event(), [], [], None))

    DagiApp.on_prompt_input_submitted(app, SimpleNamespace(value="/help"))

    assert app.slashed == ["/help"]
    assert app.dispatched == []


def test_live_pending_ask_answers_the_question() -> None:
    """The worker is still blocked on the event — the reply must reach it."""
    evt, container = threading.Event(), []
    app = _submit_app(worker_alive=True, pending=(evt, container, [], None))

    DagiApp.on_prompt_input_submitted(app, SimpleNamespace(value="option b"))

    assert container == ["option b"]
    assert evt.is_set()
    assert app.dispatched == []
    assert app.running_shown == 1
    assert app.prompt.disabled is True


def test_pending_ask_stays_live_while_only_a_wtf_worker_runs() -> None:
    """``/wtf`` runs on its own thread; a question it raises is still answerable."""
    evt, container = threading.Event(), []
    app = _submit_app(worker_alive=False, pending=(evt, container, [], None))
    app._wtf_worker = _Worker(True)

    DagiApp.on_prompt_input_submitted(app, SimpleNamespace(value="yes"))

    assert container == ["yes"]
    assert evt.is_set()


class _StubLoop:
    def __init__(self, *_args, **kwargs) -> None:
        self._messages: list = []
        self.tracker = SimpleNamespace()
        self._raise = kwargs.pop("_raise", None)

    def run(self, _task: str) -> str:
        return ""

    def finish(self) -> None:
        return None


def _work_app() -> SimpleNamespace:
    app = SimpleNamespace(
        _active_loop=None,
        _restore_initial_messages=None,
        _restore_initial_affect=None,
        _config=SimpleNamespace(),
        _pending_ask=(threading.Event(), [], [], None),
        conv=_Conversation(),
        sidebar=SimpleNamespace(set_status=lambda _s: None),
        enabled=0,
    )
    app.query_one = lambda selector, *_a: (
        app.sidebar if selector is Sidebar else app.conv
    )
    app.call_from_thread = lambda fn, *a: fn(*a)

    def _enable() -> None:
        app.enabled += 1

    app._enable_input = _enable
    app._clear_pending_ask = lambda: DagiApp._clear_pending_ask(app)
    return app


def test_worker_exit_clears_a_pending_ask(monkeypatch) -> None:
    """Every turn ending — however it ends — retires the question with it."""
    monkeypatch.setattr("tui.app.AgentLoop", _StubLoop)
    app = _work_app()

    DagiApp._agent_work(app, "task", SimpleNamespace(), [])

    assert app._pending_ask is None
    assert app.enabled == 1


def test_worker_crash_clears_a_pending_ask(monkeypatch) -> None:
    """The error path is the one that never fires ``on_done`` — it must clear too."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr("tui.app.AgentLoop", _boom)
    app = _work_app()

    DagiApp._agent_work(app, "task", SimpleNamespace(), [])

    assert app._pending_ask is None
    assert app.conv.errors == ["provider exploded"]
