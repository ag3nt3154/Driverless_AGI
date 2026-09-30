"""Conversation pane rendered with Vditor (Lute + KaTeX + highlight.js)."""
from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from pyside_gui.conversation import ConversationView
from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401


def settle(ms: int = 1500) -> None:
    """Let Vditor's lazily loaded KaTeX / highlight.js scripts arrive."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def poll(view, script: str, expected, timeout_ms: int = 8000):
    """Re-evaluate ``script`` until it returns ``expected`` (async renderers)."""
    waited = 0
    value = evaluate(view, script)
    while value != expected and waited < timeout_ms:
        settle(200)
        waited += 200
        value = evaluate(view, script)
    return value


def test_theme_tokens_are_spliced_into_the_page(view):
    assert evaluate(view, """
        return getComputedStyle(document.documentElement)
            .getPropertyValue('--chat-bg').trim();
    """) == "#191919"


def test_math_renders_with_katex_for_all_delimiters(view):
    view.append_assistant(
        "Inline $E=mc^2$ and \\(a+b\\).\n\n$$\n\\int_0^1 x\\,dx\n$$\n\n\\[ \\frac12 \\]"
    )
    assert poll(view, "return document.querySelectorAll('.assistant-message .katex').length;", 4) == 4
    assert evaluate(view, """
        return document.querySelectorAll('.assistant-message div.language-math').length;
    """) == 2


def test_model_html_stays_literal_but_code_keeps_angle_brackets(view):
    view.append_assistant(
        'Use <div onclick="window.pwn=1">x</div> and `a < b`.\n\n'
        "```python\nprint('<b>')\n```"
    )
    state = evaluate(view, """
        const body = document.querySelector('.assistant-message .message-body');
        return {
            divs: body.querySelectorAll('div[onclick]').length,
            text: body.querySelector('p').textContent,
            code: body.querySelector('pre code').textContent.trim(),
        };
    """)
    assert state == {
        "divs": 0,
        "text": 'Use <div onclick="window.pwn=1">x</div> and a < b.',
        "code": "print('<b>')",
    }


def test_code_blocks_get_highlighting_and_english_copy_button(view):
    view.append_assistant("```python\ndef f():\n    return 1\n```")
    assert poll(view, "return !!document.querySelector('.assistant-message code.hljs');", True)
    assert evaluate(view, """
        return document.querySelector('.vditor-copy span').getAttribute('aria-label');
    """) == "Copy"


def test_callouts_render(view):
    view.append_assistant("> [!WARNING]\n> careful")
    assert evaluate(view, """
        const c = document.querySelector('.callout');
        return c && c.dataset.subtype;
    """) == "WARNING"


def test_streamed_answer_is_rendered_while_streaming(view):
    view.stream_start()
    view.stream_delta("text", "**bo")
    view.stream_delta("text", "ld** and $x^2$")
    assert poll(view, """
        const b = document.getElementById('streaming-bubble');
        return b && b.querySelector('strong') ? b.querySelector('strong').textContent : null;
    """, "bold") == "bold"
    view.stream_end("**bold** and $x^2$")
    assert evaluate(view, """
        return [document.querySelectorAll('#streaming-bubble').length,
                document.querySelectorAll('.assistant-message strong').length];
    """) == [0, 1]


def test_tool_call_is_a_quiet_line_that_expands(view):
    view.append_tool_start("read", json.dumps({"path": "agent/loop.py"}))
    view.append_tool_end("read", "one\ntwo")
    view.append_tool_start("bash", json.dumps({"command": "false"}))
    view.append_tool_end("bash", "Error: exit 1")
    state = evaluate(view, """
        const rows = document.querySelectorAll('.tool-call');
        const first = rows[0];
        const hiddenBefore = first.querySelector('.tool-detail').hidden;
        first.querySelector('.tool-head').click();
        return {
            labels: Array.from(rows, r => r.querySelector('.tool-label').textContent),
            status: Array.from(rows, r => r.querySelector('.tool-status').textContent),
            classes: Array.from(rows, r => r.classList.contains('failed')),
            hiddenBefore,
            hiddenAfter: first.querySelector('.tool-detail').hidden,
            result: first.querySelector('.tool-result').textContent,
        };
    """)
    assert state == {
        "labels": ["Read agent/loop.py", "Ran false"],
        "status": ["✓ 2 lines", "✕"],
        "classes": [False, True],
        "hiddenBefore": True,
        "hiddenAfter": False,
        "result": "one\ntwo",
    }


def test_streamed_reasoning_collapses_to_thought_summary(view):
    view.stream_start()
    view.stream_delta("reasoning", "**Plan** first")
    view.stream_delta("text", "Answer")
    view.stream_end("Answer")
    state = evaluate(view, """
        const r = document.querySelector('.reasoning-message');
        return {tag: r.tagName, open: r.open,
                label: r.querySelector('.thought-label').textContent,
                bold: r.querySelector('.message-body strong').textContent};
    """)
    assert state["tag"] == "DETAILS"
    assert state["open"] is False
    assert state["label"].startswith("Thought for ")
    assert state["bold"] == "Plan"


def test_welcome_screen_leaves_with_first_message(view):
    view.show_welcome("Driverless AGI · m", "C:/proj\nType /help", None)
    assert evaluate(view, "return !!document.getElementById('empty-state');") is True
    view.append_user_message("hi")
    assert evaluate(view, """
        return [!!document.getElementById('empty-state'),
                document.querySelector('.user-message').textContent];
    """) == [False, "hi"]


def test_calls_before_page_load_are_replayed(qapp):
    widget = ConversationView()
    widget.append_info("queued before load")
    loop = QEventLoop()
    widget.loadFinished.connect(loop.quit)
    QTimer.singleShot(10000, loop.quit)
    loop.exec()
    try:
        assert evaluate(widget, "return document.querySelector('.info-message').textContent;") \
            == "queued before load"
    finally:
        widget.close()
        widget.deleteLater()


@pytest.mark.parametrize("url, opened", [
    ("https://example.com", True),
    ("javascript:alert(1)", False),
])
def test_clicked_links_open_externally_never_in_the_pane(monkeypatch, view, url, opened):
    from PySide6.QtCore import QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage

    calls = []
    monkeypatch.setattr(
        "pyside_gui.conversation.QDesktopServices.openUrl", lambda u: calls.append(u.toString())
    )
    accepted = view.page().acceptNavigationRequest(
        QUrl(url), QWebEnginePage.NavigationType.NavigationTypeLinkClicked, True
    )
    assert accepted is False
    assert bool(calls) is opened


def test_tool_args_are_shown_as_labelled_fields_with_real_newlines(view):
    view.append_tool_start("write_handoff", json.dumps({"content": "Hello\n\n- item", "n": [1, 2]}))
    view.append_tool_start("bash", "not json {")
    state = evaluate(view, """
        const rows = document.querySelectorAll('.tool-call');
        const fields = rows[0].querySelectorAll('.tool-arg');
        return {
            keys: Array.from(fields, f => f.querySelector('.tool-arg-key').textContent),
            content: fields[0].querySelector('.tool-arg-value').textContent,
            list: fields[1].querySelector('.tool-arg-value').textContent,
            raw: rows[1].querySelector('pre.tool-args').textContent,
        };
    """)
    assert state == {
        "keys": ["content", "n"],
        "content": "Hello\n\n- item",
        "list": "[\n  1,\n  2\n]",
        "raw": "not json {",
    }
