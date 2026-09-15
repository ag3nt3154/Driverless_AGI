from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest
import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from pyside_gui.conversation import ConversationView


_app = QApplication.instance() or QApplication(sys.argv)


def evaluate(view: ConversationView, script: str):
    """Wait for the real WebEngine DOM, including previously queued Python updates."""
    loop = QEventLoop()
    result = []

    def receive(value):
        result.append(value)
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(10000)
    view.page().runJavaScript(f"JSON.stringify((() => {{ {script} }})())", receive)
    loop.exec()
    timer.stop()
    assert result, "WebEngine JavaScript callback timed out"
    return json.loads(result[0])


@pytest.fixture
def view():
    widget = ConversationView()
    widget.resize(500, 700)
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    widget.loadFinished.connect(loop.quit)
    timer.start(10000)
    loop.exec()
    timer.stop()
    assert widget._ready, "Conversation page failed to load"
    yield widget
    widget.close()
    widget.deleteLater()
    _app.processEvents()


@pytest.mark.parametrize("text", [
    "First\nSecond\nThird\nFourth\nLatest\n",
    "A long reasoning sentence that wraps across the narrow conversation. " * 30,
], ids=["explicit-lines", "wrapped-line"])
def test_stream_preview_shows_last_three_visual_lines(view, text):
    view.stream_start()
    view.stream_delta("reasoning", text)
    state = evaluate(view, """
        const body = document.querySelector('.reasoning-preview');
        return {
            text: body.textContent,
            height: body.clientHeight,
            line: parseFloat(getComputedStyle(body).lineHeight),
            scroll: body.scrollTop,
            overflow: body.scrollHeight - body.clientHeight,
            answerVisible: document.getElementById('streaming-bubble').offsetHeight > 0
        };
    """)
    assert state["text"] == text.rstrip()
    assert state["height"] == pytest.approx(7 * state["line"], abs=1)
    assert state["scroll"] > 0
    assert state["scroll"] == pytest.approx(state["overflow"], abs=1)
    assert not state["answerVisible"]


def test_answer_start_expands_full_markdown_without_duplicate_on_stream_end(view):
    view.stream_start()
    view.stream_delta("reasoning", "## Approach\n\n**Check** `state`.\n\n- First\n")
    view.stream_delta("reasoning", "- Second\n\n```python\nprint('ok')\n```\n")
    view.stream_delta("text", "Answer")
    state = evaluate(view, """
        const body = document.querySelector('.reasoning-message .message-body');
        return {
            title: body.querySelector('h2').textContent,
            bold: body.querySelector('strong').textContent,
            items: body.querySelectorAll('li').length,
            code: body.querySelector('pre code').textContent,
            limit: getComputedStyle(body).maxHeight,
            previewCount: document.querySelectorAll('.reasoning-preview').length
        };
    """)
    assert state == {
        "title": "Approach", "bold": "Check", "items": 2,
        "code": "print('ok')\n", "limit": "none", "previewCount": 0,
    }
    view.stream_end("<p>Answer</p>")
    assert evaluate(view, """
        return [document.querySelectorAll('.reasoning-message').length,
                document.querySelectorAll('.assistant-message').length,
                document.querySelector('.assistant-message p').textContent];
    """) == [1, 1, "Answer"]


def test_reasoning_only_turn_finalizes_and_next_turn_is_independent(view):
    view.stream_start()
    view.stream_delta("reasoning", "**First thought**")
    view.stream_end("")
    view.stream_start()
    view.stream_delta("reasoning", "**Second thought**")
    view.stream_end("")
    assert evaluate(view, """
        return {
            thoughts: Array.from(document.querySelectorAll('.reasoning-message strong'),
                                 node => node.textContent),
            answers: document.querySelectorAll('.assistant-message').length,
            active: document.querySelectorAll('#streaming-reasoning, .reasoning-preview').length
        };
    """) == {"thoughts": ["First thought", "Second thought"], "answers": 0, "active": 0}


def test_nonstreaming_reasoning_renders_markdown_but_html_stays_literal(view):
    view.append_reasoning('**Visible** <img src=x onerror="window.injected=1">')
    assert evaluate(view, """
        const body = document.querySelector('.reasoning-message .message-body');
        return {bold: body.querySelector('strong').textContent,
                images: body.querySelectorAll('img').length, text: body.textContent.trim()};
    """) == {"bold": "Visible", "images": 0,
             "text": 'Visible <img src=x onerror="window.injected=1">'}


def test_clear_discards_preview_and_late_reasoning_preserves_all_text(view):
    view.stream_start()
    view.stream_delta("reasoning", "Discard me")
    view.clear()
    view.stream_start()
    view.stream_delta("reasoning", "**Kept**")
    view.stream_delta("text", "Answer")
    view.stream_delta("reasoning", " and *late tokens*")
    view.stream_end("<p>Answer</p>")
    assert evaluate(view, """
        const bodies = document.querySelectorAll('.reasoning-message .message-body');
        return [bodies.length, bodies[0].textContent.trim(),
                bodies[0].querySelector('em').textContent];
    """) == [1, "Kept and late tokens", "late tokens"]


@pytest.mark.parametrize("text", ["", "Plain answer"])
def test_turn_without_reasoning_does_not_create_thinking_block(view, text):
    view.stream_start()
    view.stream_delta("reasoning", " \n")
    view.stream_delta("text", text)
    view.stream_end(f"<p>{text}</p>" if text else "")
    assert evaluate(view, """
        return [document.querySelectorAll('.reasoning-message').length,
                document.querySelectorAll('.assistant-message').length];
    """) == [0, int(bool(text))]


def test_final_reasoning_callback_does_not_duplicate_streamed_thinking(view):
    from pyside_gui.app import DagiMainWindow

    window = SimpleNamespace(_conversation=view)
    DagiMainWindow._on_stream_started(window)
    view.stream_delta("reasoning", "**Only once**")
    DagiMainWindow._on_stream_ended(window, "", "**Only once**")
    DagiMainWindow._on_reasoning(window, "**Only once**")
    assert evaluate(view, """
        return Array.from(document.querySelectorAll('.reasoning-message strong'),
                          node => node.textContent);
    """) == ["Only once"]
