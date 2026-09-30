"""Global Esc: stops the agent from any widget, including web views."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QMenu, QVBoxLayout, QWidget

from pyside_gui.conversation import ConversationView
from pyside_gui.esc_stop import EscapeStop, claim_escape
from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


@pytest.fixture
def window(qtbot):
    win = QWidget()
    layout = QVBoxLayout(win)
    conversation = ConversationView()
    other = QListWidget()
    layout.addWidget(conversation)
    layout.addWidget(other)
    win.resize(500, 600)
    qtbot.addWidget(win)
    win.show()
    ready = QEventLoop()
    conversation.loadFinished.connect(ready.quit)
    QTimer.singleShot(10000, ready.quit)
    ready.exec()
    state = {"running": True, "stops": 0}

    def stop():
        state["stops"] += 1

    esc = EscapeStop(lambda: [win], lambda: state["running"], stop)
    QApplication.instance().installEventFilter(esc)
    yield win, conversation, other, state
    QApplication.instance().removeEventFilter(esc)


def _press_esc_in(widget) -> None:
    target = widget.focusProxy() or widget
    target.setFocus()
    _wait(100)
    QTest.keyClick(QApplication.focusWidget() or target, Qt.Key.Key_Escape)
    _wait(100)


def test_esc_in_a_focused_web_view_stops_the_agent(window):
    _win, conversation, _other, state = window
    _press_esc_in(conversation)
    assert state["stops"] == 1


def test_esc_passes_through_when_nothing_is_running(window):
    _win, _conversation, other, state = window
    state["running"] = False
    _press_esc_in(other)
    assert state["stops"] == 0


def test_a_visible_claiming_widget_gets_esc_first(window):
    win, _conversation, other, state = window
    picker = QWidget(win)
    claim_escape(picker)
    picker.show()
    _press_esc_in(other)
    assert state["stops"] == 0
    picker.hide()
    _press_esc_in(other)
    assert state["stops"] == 1


def test_open_menu_gets_esc_first(window, qtbot):
    win, _conversation, _other, state = window
    menu = QMenu(win)
    menu.addAction("item")
    menu.popup(win.mapToGlobal(win.rect().center()))
    qtbot.waitUntil(lambda: QApplication.activePopupWidget() is menu)
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    _wait(100)
    assert state["stops"] == 0
    assert not menu.isVisible()


def test_interrupt_freezes_the_stream_bubble_and_ignores_late_output(view):
    view.stream_start()
    view.stream_delta("reasoning", "planning")
    view.stream_delta("text", "Half an ans")
    view.interrupt_stream()
    view.stream_delta("text", "wer, then more")
    view.stream_end("Half an answer, then more")
    _wait(300)
    assert evaluate(view, """
        return {
            live: document.querySelectorAll('#streaming-bubble, #streaming-reasoning').length,
            text: document.querySelector('.assistant-message .message-body').textContent.trim(),
            thought: document.querySelector('.reasoning-message .thought-label').textContent,
        };
    """) == {"live": 0, "text": "Half an ans", "thought": "Thought for 1s"}


def _pause_window(streaming: bool, pending_ask=None, interrupted=True):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from pyside_gui.app import DagiMainWindow

    win = DagiMainWindow.__new__(DagiMainWindow)
    loop = MagicMock()
    loop.interrupt.return_value = interrupted
    win._worker = SimpleNamespace(is_alive=lambda: True)
    win._current_loop_ref = [loop]
    win._pending_ask = pending_ask
    win._streaming_active = streaming
    for name in ("_conversation", "_right_sidebar", "_left_sidebar", "_hide_running", "_enable_input"):
        setattr(win, name, MagicMock())
    DagiMainWindow._action_pause(win)
    return win, loop


def test_pause_action_interrupts_and_freezes_a_live_stream():
    win, loop = _pause_window(streaming=True)
    loop.interrupt.assert_called_once()
    win._conversation.interrupt_stream.assert_called_once()
    assert win._streaming_active is False
    win._right_sidebar.set_status.assert_called_once_with("paused")
    win._conversation.append_info.assert_called_once_with("Interrupted — type a message to continue")
    win._enable_input.assert_called_once()


def test_pause_action_leaves_a_pending_question_alone():
    win, loop = _pause_window(streaming=False, pending_ask=object())
    loop.interrupt.assert_not_called()
    win._right_sidebar.set_status.assert_not_called()


def test_pause_action_is_a_no_op_when_already_paused():
    win, _loop = _pause_window(streaming=True, interrupted=False)
    win._conversation.interrupt_stream.assert_not_called()
    win._conversation.append_info.assert_not_called()
