"""Typing while the agent runs: queued bubbles, delivery, cancel, leftovers."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from agent.user_input import UserSubmission
from pyside_gui import _dispatch
from pyside_gui.bridge import AgentBridge
from pyside_gui.steer_queue import SteerQueue, combine
from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401
from pyside_gui.tests.test_conversation_vditor import poll


class _Conversation(QObject):
    queued_cancel_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        if name.startswith(("append_", "mark_", "remove_")):
            return lambda *args: self.calls.append((name, *args))
        raise AttributeError(name)


class _Loop:
    def __init__(self, in_run=True) -> None:
        self._in_run = in_run
        self.steered: list = []

    @property
    def is_running(self) -> bool:
        return self._in_run

    def steer(self, submission) -> bool:
        if self._in_run:
            self.steered.append(submission)
        return self._in_run

    def cancel_steer(self, submission) -> bool:
        if submission in self.steered:
            self.steered.remove(submission)
            return True
        return False


def _win(loop=None, alive=True):
    worker = SimpleNamespace(is_alive=lambda: alive, join=lambda timeout=None: None)
    return SimpleNamespace(
        _bridge=AgentBridge(), _conversation=_Conversation(),
        _current_loop_ref=[loop] if loop else [], _worker=worker,
    )


def test_submit_shows_a_queued_bubble_and_steers_the_loop():
    loop = _Loop()
    win = _win(loop)
    queue = SteerQueue.for_window(win)
    submission = UserSubmission(text="also the tests")
    queue.submit(submission)
    assert win._conversation.calls == [("append_queued_message", "q1", "also the tests")]
    assert loop.steered == [submission]

    win._bridge.user_injected.emit(submission)
    assert win._conversation.calls[-1] == ("mark_queued_delivered", "q1")
    assert queue.pending == []


def test_cancel_before_delivery_withdraws_it():
    loop = _Loop()
    win = _win(loop)
    queue = SteerQueue.for_window(win)
    queue.submit(UserSubmission(text="never mind"))
    win._conversation.queued_cancel_requested.emit("q1")
    assert loop.steered == []
    assert queue.pending == []
    assert win._conversation.calls[-1] == ("remove_queued_message", "q1")


def test_leftovers_become_the_next_turn(monkeypatch):
    sent = []
    monkeypatch.setattr(_dispatch, "dispatch_agent", lambda win, task, show=True: sent.append((task, show)))
    win = _win(_Loop(in_run=False), alive=False)
    queue = SteerQueue.for_window(win)
    queue.submit(UserSubmission(text="first"))
    queue.submit(UserSubmission(text="second"))
    queue.turn_finished.emit()
    assert [(t.text, show) for t, show in sent] == [("first\n\nsecond", False)]
    assert ("mark_queued_delivered", "q2") in win._conversation.calls
    assert queue.pending == []


def test_combine_keeps_order_and_images():
    img = object()
    merged = combine([UserSubmission(text="a"), UserSubmission(text="", images=(img,)),
                      UserSubmission(text="b")])
    assert merged.text == "a\n\nb"
    assert merged.images == (img,)


def test_running_submission_is_queued_and_slash_commands_are_refused(monkeypatch):
    from pyside_gui.app import DagiMainWindow

    queued = []
    monkeypatch.setattr(SteerQueue, "for_window",
                        classmethod(lambda cls, win: SimpleNamespace(submit=queued.append)))
    restored = []
    loop = SimpleNamespace(is_paused=False)  # running, not paused
    win = SimpleNamespace(
        _compose_mode=False, _pending_ask=None, _pending_ask_container=None,
        _worker=SimpleNamespace(is_alive=lambda: True), _current_loop_ref=[loop],
        _conversation=_Conversation(), _prompt=SimpleNamespace(restore_draft=restored.append),
    )
    DagiMainWindow._on_input_submitted(win, "keep the old API")
    assert [s.text for s in queued] == ["keep the old API"]

    DagiMainWindow._on_input_submitted(win, "/model x")
    assert len(queued) == 1
    assert restored and restored[0].text == "/model x"
    assert win._conversation.calls[-1][0] == "append_info"


def test_queued_bubble_stays_pinned_then_joins_the_timeline(view):
    view.append_user_message("start")
    view.append_queued_message("q1", "also the tests")
    view.append_info("tool ran")  # the live turn keeps going above it
    order = """
        return Array.from(document.querySelectorAll('.user-message, .info-message'),
            e => (e.classList.contains('queued') ? 'Q:' : '') + e.textContent.replace(/✕|Queued.*step/g, '').trim());
    """
    assert evaluate(view, order) == ["start", "tool ran", "Q:also the tests"]
    view.mark_queued_delivered("q1")
    view.append_info("next step")
    assert evaluate(view, order) == ["start", "tool ran", "also the tests", "next step"]
    assert evaluate(view, "return !!document.getElementById('queued-area');") is False


def test_cancel_button_reaches_python_over_the_web_channel(view, qtbot):
    view.append_queued_message("q7", "oops")
    assert poll(view, "return !!window._dagi;", True) is True
    with qtbot.waitSignal(view.queued_cancel_requested) as blocker:
        evaluate(view, "document.querySelector('.queued-cancel').click(); return 1;")
    assert blocker.args == ["q7"]
