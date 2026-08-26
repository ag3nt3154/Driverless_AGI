"""A pending ``ask_user`` question must never outlive the worker that raised it.

``_on_agent_done``/``_on_agent_paused`` already retire the answer sink, but a
turn can also end through ``on_error`` or an exception, and neither of those
fires either signal. The stale sink then swallows the next user message: the
running label is shown, the prompt is disabled, and no worker is started — a
hang with a ticking timer and a process state stuck at ``idle``.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pyside_gui  # noqa: F401 — must be imported before any PySide6 import

from pyside_gui.app import DagiMainWindow


class _Conversation:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.info: list[str] = []

    def append_user_message(self, text: str) -> None:
        self.messages.append(text)

    def append_info(self, text: str) -> None:
        self.info.append(text)


class _Prompt:
    def __init__(self) -> None:
        self.disabled = False

    def setDisabled(self, value: bool) -> None:  # noqa: N802 — Qt API name
        self.disabled = value

    def setFocus(self) -> None:  # noqa: N802 — Qt API name
        return None


class _Worker:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _submit_app(*, worker_alive: bool, pending, container) -> SimpleNamespace:
    app = SimpleNamespace(
        _pending_ask=pending,
        _pending_ask_container=container,
        _worker=_Worker(worker_alive),
        _current_loop_ref=[],
        _conversation=_Conversation(),
        _prompt=_Prompt(),
        dispatched=[],
        running_shown=0,
    )
    app._dispatch_agent = app.dispatched.append

    def _show_running() -> None:
        app.running_shown += 1

    app._show_running = _show_running
    return app


def test_stale_pending_ask_does_not_swallow_the_next_task() -> None:
    """Answering a dead question starts no worker — the timer runs over nothing."""
    evt, container = threading.Event(), []
    app = _submit_app(worker_alive=False, pending=evt, container=container)

    DagiMainWindow._on_input_submitted(app, "next task")

    assert app.dispatched == ["next task"]
    assert container == []
    assert not evt.is_set()
    assert app.running_shown == 0  # _dispatch_agent owns the label
    assert app._pending_ask is None
    assert app._pending_ask_container is None


def test_live_pending_ask_answers_the_question() -> None:
    """The worker is still blocked on the event — the reply must reach it."""
    evt, container = threading.Event(), []
    app = _submit_app(worker_alive=True, pending=evt, container=container)

    DagiMainWindow._on_input_submitted(app, "option b")

    assert container == ["option b"]
    assert evt.is_set()
    assert app.dispatched == []
    assert app.running_shown == 1
    assert app._prompt.disabled is True


class _StubLoop:
    def __init__(self, *_args, **_kwargs) -> None:
        self._messages: list = []
        self.tracker = SimpleNamespace()

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
        _pending_ask=threading.Event(),
        _pending_ask_container=[],
        _cmd_handler=SimpleNamespace(set_active_loop=lambda _loop: None),
        _prompt=_Prompt(),
        _right_sidebar=SimpleNamespace(set_status=lambda _s: None),
        errors=[],
        slots=[],
    )
    app._bridge = SimpleNamespace(
        stage_trace=SimpleNamespace(emit=lambda _msg: None),
        error_occurred=SimpleNamespace(emit=app.errors.append),
    )

    def _invoke_on_main(slot: str, arg: str | None = None) -> None:
        app.slots.append(slot)
        method = getattr(DagiMainWindow, slot)
        method(app, arg) if arg is not None else method(app)

    app._invoke_on_main = _invoke_on_main
    app._hide_running = lambda: None
    app._enable_input = lambda: DagiMainWindow._enable_input(app)
    return app


def test_worker_exit_clears_a_pending_ask(monkeypatch) -> None:
    """Every turn ending — however it ends — retires the question with it."""
    monkeypatch.setattr("pyside_gui.app.AgentLoop", _StubLoop)
    app = _work_app()

    DagiMainWindow._agent_work(app, "task", SimpleNamespace(), [])

    assert app._pending_ask is None
    assert app._pending_ask_container is None
    assert app._prompt.disabled is False


def test_worker_crash_clears_a_pending_ask(monkeypatch) -> None:
    """The error path is the one that never fires ``on_done`` — it must clear too."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr("pyside_gui.app.AgentLoop", _boom)
    app = _work_app()

    DagiMainWindow._agent_work(app, "task", SimpleNamespace(), [])

    assert app._pending_ask is None
    assert app.errors == ["provider exploded"]
