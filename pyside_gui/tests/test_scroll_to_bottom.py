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
    monkeypatch.setattr("pyside_gui.app.ConversationView", FakeConversation)
    monkeypatch.setattr("pyside_gui.app.RightSidebar", FakeRightSidebar)
    monkeypatch.setattr("pyside_gui.app.CopyPicker", lambda _view: object())

    window = DagiMainWindow.__new__(DagiMainWindow)
    QMainWindow.__init__(window)
    window._project_path = tmp_path
    window._verbose = False
    window._config = SimpleNamespace(
        display_name="test",
        context_window=1000,
        reserve_tokens=100,
        memory_root=None,
    )
    DagiMainWindow._build_ui(window)

    window._right_sidebar.scroll_to_bottom_requested.emit()

    assert window._conversation.scroll_calls == 1


def test_conversation_force_scroll_runs_unconditional_javascript() -> None:
    view = SimpleNamespace(_run_js=MagicMock())

    ConversationView.scroll_to_bottom(view)

    view._run_js.assert_called_once_with("scrollToBottom()")


def test_conversation_page_exports_scroll_to_bottom() -> None:
    engine = QJSEngine()
    engine.evaluate(
        "function IntersectionObserver() { this.observe = function() {}; }"
        "var document = { addEventListener: function() {} };"
    )
    script_path = Path(__file__).parents[1] / "resources" / "conversation.js"
    evaluation = engine.evaluate(script_path.read_text(encoding="utf-8"))

    assert not evaluation.isError(), evaluation.toString()
    assert engine.evaluate("typeof scrollToBottom").toString() == "function"
