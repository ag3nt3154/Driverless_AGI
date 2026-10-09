from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pyside_gui  # noqa: F401 - import before PySide6 to register DLL paths

from PySide6.QtCore import Signal
from PySide6.QtQml import QJSEngine
from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton, QWidget

from pyside_gui.app import DagiMainWindow
from pyside_gui.conversation import ConversationView
from pyside_gui.right_sidebar import RightSidebar


_app = QApplication.instance() or QApplication(sys.argv)


def test_sidebar_button_emits_scroll_request(tmp_path) -> None:
    sidebar = RightSidebar("test", 1000, 100, tmp_path, tmp_path)
    received: list[bool] = []
    sidebar.scroll_to_bottom_requested.connect(lambda: received.append(True))

    button = sidebar.findChild(QPushButton, "scroll-to-bottom-button")
    assert button is not None
    assert sidebar._layout.itemAt(sidebar._layout.count() - 1).widget() is button
    button.click()

    assert received == [True]


def test_main_window_wires_scroll_request_to_conversation(
    monkeypatch, tmp_path
) -> None:
    class FakeLeftSidebar(QWidget):
        session_selected = Signal(object)
        expansion_changed = Signal(bool)

        def __init__(self, _project_path) -> None:
            super().__init__()

    class FakeConversation(QWidget):
        def __init__(self, _verbose) -> None:
            super().__init__()
            self.scroll_calls = 0

        def scroll_to_bottom(self) -> None:
            self.scroll_calls += 1

    class FakeRightSidebar(QWidget):
        scroll_to_bottom_requested = Signal()

        def __init__(self, *_args) -> None:
            super().__init__()

    monkeypatch.setattr("pyside_gui.app.LeftSidebar", FakeLeftSidebar)
    monkeypatch.setattr("pyside_gui.app.RightSidebar", FakeRightSidebar)

    window = DagiMainWindow.__new__(DagiMainWindow)
    QMainWindow.__init__(window)
    window._verbose = False
    config = SimpleNamespace(
        display_name="test",
        context_window=1000,
        reserve_tokens=100,
        memory_root=None,
    )
    DagiMainWindow._build_ui(window, config, tmp_path)
    first, second = FakeConversation(False), FakeConversation(False)
    window._active = SimpleNamespace(_conversation=first)
    window._right_sidebar.scroll_to_bottom_requested.emit()
    window._active = SimpleNamespace(_conversation=second)
    window._right_sidebar.scroll_to_bottom_requested.emit()

    # The button follows whichever agent is shown in the main chat.
    assert (first.scroll_calls, second.scroll_calls) == (1, 1)


def test_conversation_force_scroll_runs_unconditional_javascript() -> None:
    view = SimpleNamespace(_run_js=MagicMock())

    ConversationView.scroll_to_bottom(view)

    view._run_js.assert_called_once_with("scrollToBottom()")


# Minimal DOM: a 1000px document in a 600px viewport, sitting at the bottom.
# Scrolling to the sentinel moves to the bottom and fires a scroll event, as
# Chromium does; a viewport resize changes clientHeight without one.
_DOM_STUB = """
if (!String.prototype.matchAll) String.prototype.matchAll = function() { return []; };
var _listeners = {};
function _fire(type) { (_listeners[type] || []).forEach(function(f) { f({}); }); }
var window = {
    addEventListener: function(t, f) { (_listeners[t] = _listeners[t] || []).push(f); },
};
var _page = { scrollHeight: 1000, scrollTop: 400, clientHeight: 600 };
function _atBottom() { return _page.scrollTop === _page.scrollHeight - _page.clientHeight; }
function _scrollTo(top) { _page.scrollTop = top; _fire('scroll'); }
function _fakeEl() {
    return {
        className: '', innerHTML: '', textContent: '', dataset: {}, children: [],
        classList: { add: function() {}, remove: function() {}, toggle: function() {} },
        appendChild: function(c) { this.children.push(c); return c; },
        addEventListener: function() {},
        querySelector: function() { return null; },
        insertBefore: function(c) { _page.scrollHeight += 100; return c; },
    };
}
var _sentinel = _fakeEl();
_sentinel.parentNode = _fakeEl();
_sentinel.scrollIntoView = function() { _scrollTo(_page.scrollHeight - _page.clientHeight); };
var document = {
    scrollingElement: _page,
    addEventListener: function() {},
    createElement: _fakeEl,
    createTextNode: function(t) { return { textContent: t }; },
    getElementById: function(id) { return id === 'scroll-sentinel' ? _sentinel : null; },
};
"""


def _load_page() -> QJSEngine:
    engine = QJSEngine()
    engine.evaluate(_DOM_STUB)
    script_path = Path(__file__).parents[1] / "resources" / "conversation.js"
    evaluation = engine.evaluate(script_path.read_text(encoding="utf-8"))
    assert not evaluation.isError(), evaluation.toString()
    return engine


def _js(engine: QJSEngine, code: str):
    result = engine.evaluate(code)
    assert not result.isError(), result.toString()
    return result.toVariant()


def test_conversation_page_exports_scroll_to_bottom() -> None:
    engine = _load_page()

    assert _js(engine, "typeof scrollToBottom") == "function"


def test_new_content_follows_while_pinned_to_bottom() -> None:
    engine = _load_page()

    _js(engine, "appendInfo('hello')")

    assert _js(engine, "_atBottom()") is True


def test_scrolling_up_stops_auto_scroll() -> None:
    engine = _load_page()

    _js(engine, "_scrollTo(0); appendInfo('hello')")

    assert _js(engine, "_page.scrollTop") == 0


def test_scrolling_back_near_bottom_resumes_auto_scroll() -> None:
    engine = _load_page()

    _js(engine, "_scrollTo(0); _scrollTo(_page.scrollHeight - _page.clientHeight - 20)")
    _js(engine, "appendInfo('hello')")

    assert _js(engine, "_atBottom()") is True


def test_viewport_shrink_keeps_chat_pinned() -> None:
    # The composer growing shrinks the view without a scroll event; that must
    # not count as the user scrolling away from the bottom.
    engine = _load_page()

    _js(engine, "_page.clientHeight = 360; _fire('resize')")
    assert _js(engine, "_atBottom()") is True

    _js(engine, "_page.clientHeight = 300; appendInfo('hello')")
    assert _js(engine, "_atBottom()") is True


def test_sending_a_message_scrolls_to_bottom_even_when_scrolled_up() -> None:
    engine = _load_page()

    _js(engine, "_scrollTo(0); appendMessage('user', 'hi there')")
    assert _js(engine, "_atBottom()") is True

    _js(engine, "appendInfo('reply')")
    assert _js(engine, "_atBottom()") is True
