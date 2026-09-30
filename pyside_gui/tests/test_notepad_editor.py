from __future__ import annotations

import sys

import pytest
import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pyside_gui.notepad_editor import NotepadEditor, open_external

_app = QApplication.instance() or QApplication(sys.argv)


def _wait(signal, timeout_ms: int = 15000) -> bool:
    loop = QEventLoop()
    fired = []
    signal.connect(lambda *a: (fired.append(a), loop.quit()))
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    loop.exec()
    timer.stop()
    return bool(fired)


def _fetch(editor: NotepadEditor):
    loop = QEventLoop()
    out = []
    editor.fetch_markdown(lambda v: (out.append(v), loop.quit()))
    if not out:
        QTimer.singleShot(10000, loop.quit)
        loop.exec()
    assert out, "fetch_markdown callback timed out"
    return out[0]


@pytest.fixture(scope="module")
def editor():
    widget = NotepadEditor()
    widget.resize(360, 420)
    widget.show()
    assert _wait(widget.ready), "Vditor failed to initialise"
    yield widget
    widget.close()
    widget.deleteLater()
    _app.processEvents()


def test_math_and_markdown_round_trip(editor):
    text = (
        "# Title\n\n"
        "Euler: $e^{i\\pi}+1=0$\n\n"
        "$$\n\\int_0^1 x\\,dx\n$$\n\n"
        "- [ ] task\n"
    )
    editor.set_markdown(text)
    out = _fetch(editor)
    assert "# Title" in out
    assert "$e^{i\\pi}+1=0$" in out
    assert "\\int_0^1 x\\,dx" in out
    assert "- [ ]" in out and "task" in out


def test_normalisation_is_idempotent(editor):
    # Lute normalises markdown once (e.g. "- [ ]  task", "[X]"); saving
    # repeatedly must not drift further.
    text = "- [ ] task\n- [x] done\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n"
    editor.set_markdown(text)
    once = _fetch(editor)
    editor.set_markdown(once)
    assert _fetch(editor) == once


def test_math_renders_with_katex(editor):
    editor.set_markdown("$$\n\\frac{a}{b}\n$$\n")
    loop = QEventLoop()
    found = []

    def poll():
        editor.page().runJavaScript(
            "document.querySelectorAll('.katex').length",
            0,
            lambda n: (found.append(n), loop.quit()) if n else QTimer.singleShot(200, poll),
        )

    QTimer.singleShot(0, poll)
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    assert found and found[-1] > 0, "KaTeX did not render the formula"


def _poll_js(editor: NotepadEditor, script: str, timeout_ms: int = 20000):
    loop = QEventLoop()
    found = []

    def poll():
        editor.page().runJavaScript(
            script, 0,
            lambda v: (found.append(v), loop.quit()) if v else QTimer.singleShot(200, poll),
        )

    QTimer.singleShot(0, poll)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return found[-1] if found else None


def test_mermaid_renders_with_strict_security(editor):
    editor.set_markdown("```mermaid\ngraph TD\n  A --> B\n```\n")
    assert _poll_js(editor, "!!document.querySelector('.language-mermaid svg')"), \
        "mermaid diagram was not drawn"
    level = _poll_js(editor, "window.mermaid && window.mermaid.mermaidAPI.getConfig().securityLevel")
    assert level == "strict"


def test_set_markdown_does_not_echo_content_changed(editor):
    echoed = []
    editor.content_changed.connect(echoed.append)
    editor.set_markdown("no echo")
    _fetch(editor)
    _app.processEvents()
    assert echoed == []


def test_fetch_before_ready_returns_pending_text():
    widget = NotepadEditor()
    widget.set_markdown("pending")
    out = []
    widget.fetch_markdown(out.append)
    assert out == ["pending"]
    widget.deleteLater()


@pytest.mark.parametrize("url", ["file:///C:/Windows/system32/calc.exe", "javascript:alert(1)", "notepad.html"])
def test_open_external_rejects_unsafe_schemes(url):
    assert open_external(url) is False


def _type(editor: NotepadEditor, keys) -> str:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    def pause(ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    editor.set_markdown("")
    pause(200)
    editor.focus_editor()
    pause(200)
    target = editor.focusProxy()
    for key in keys:
        if isinstance(key, str):
            QTest.keyClicks(target, key)
        else:
            shift = Qt.KeyboardModifier.ShiftModifier if key is _SHIFT_ENTER else Qt.KeyboardModifier.NoModifier
            QTest.keyClick(target, Qt.Key.Key_Return, shift)
        pause(80)
    pause(300)
    return _fetch(editor)


_ENTER, _SHIFT_ENTER = object(), object()


@pytest.mark.parametrize("keys, expected", [
    (["aa", _ENTER, "bb"], "aa\nbb\n"),               # Enter: single line break
    (["aa", _SHIFT_ENTER, "bb"], "aa\n\nbb\n"),       # Shift+Enter: new paragraph
    (["aa", _ENTER, _ENTER, "bb"], "aa\n\nbb\n"),     # blank line = paragraph
    (["- one", _ENTER, "two"], "- one\n- two\n"),     # lists keep Vditor's Enter
    (["# hh", _ENTER, "body"], "# hh\n\nbody\n"),     # headings too
], ids=["enter", "shift-enter", "double-enter", "list", "heading"])
def test_enter_key_behaviour(editor, keys, expected):
    assert _type(editor, keys) == expected
