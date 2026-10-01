"""Long-paste cards: composer tokens, fenced expansion, bubble cards."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from pyside_gui import paste_cards
from pyside_gui.prompt_input import PromptInput
from pyside_gui.tests.test_conversation_reasoning import evaluate, view  # noqa: F401

LOG = "\n".join(f"line {i}" for i in range(1, 21))  # 20 lines


@pytest.mark.parametrize("text, long", [
    ("short", False),
    ("\n".join("x" * 3 for _ in range(14)), False),
    ("\n".join("x" * 3 for _ in range(15)), True),
    ("y" * 1499, False),
    ("y" * 1500, True),
])
def test_threshold(text, long):
    assert paste_cards.is_long(text) is long


def test_token_and_fence():
    assert paste_cards.make_token(3, LOG) == "[Pasted text #3 · 20 lines]"
    assert paste_cards.fence("a\nb\n") == "```pasted\na\nb\n```"
    assert paste_cards.fence("x ```` y").startswith("`````pasted\n")


def test_expand_puts_each_paste_on_its_own_lines():
    text = "see [Pasted text #1 · 20 lines] then [Pasted text #9 · 2 lines] ok"
    assert paste_cards.expand(text, {1: "a\nb"}) == (
        "see \n```pasted\na\nb\n```\n then [Pasted text #9 · 2 lines] ok"
    )


@pytest.fixture
def prompt(qtbot):
    widget = PromptInput()
    widget.resize(700, 200)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_long_paste_becomes_a_token_and_is_sent_fenced(prompt, qtbot):
    prompt._editor.insertPlainText("Why does this fail? ")
    prompt._insert_pasted_text(LOG)
    assert prompt.toPlainText() == "Why does this fail? [Pasted text #1 · 20 lines]"
    with qtbot.waitSignal(prompt.submitted) as blocker:
        prompt._submit()
    assert blocker.args[0].text == f"Why does this fail? \n```pasted\n{LOG}\n```"
    assert prompt._pastes == {}


def test_short_paste_stays_inline(prompt):
    prompt._insert_pasted_text("just a line")
    assert prompt.toPlainText() == "just a line"
    assert prompt._pastes == {}


def test_backspace_removes_the_whole_token(prompt):
    prompt._insert_pasted_text(LOG)
    QTest.keyClick(prompt._editor, Qt.Key.Key_Backspace)
    assert prompt.toPlainText() == ""
    assert prompt._pastes == {}


def test_delete_before_a_token_removes_it(prompt):
    prompt._insert_pasted_text(LOG)
    cursor = prompt._editor.textCursor()
    cursor.setPosition(0)
    prompt._editor.setTextCursor(cursor)
    QTest.keyClick(prompt._editor, Qt.Key.Key_Delete)
    assert prompt.toPlainText() == ""


def test_clicking_a_token_expands_it_back_to_text(prompt):
    prompt._editor.insertPlainText("log: ")
    prompt._insert_pasted_text(LOG)
    prompt._expand_token_at(8)
    assert prompt.toPlainText() == "log: " + LOG
    assert prompt._pastes == {}


def test_ctrl_shift_v_pastes_long_text_inline(prompt):
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText(LOG)
    prompt._editor.setFocus()
    QTest.keyClick(
        prompt._editor, Qt.Key.Key_V,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    assert prompt.toPlainText() == LOG


def test_sent_paste_renders_as_a_collapsed_card(view):
    view.append_user_message(f"Why?\n```pasted\n{LOG}\n```\nthanks\n\n```python\nx = 1\n```")
    assert evaluate(view, """
        const b = document.querySelector('.user-message');
        const card = b.querySelector('.paste-card');
        return {
            cards: b.querySelectorAll('.paste-card').length,
            open: card.open,
            title: card.querySelector('.paste-title').textContent,
            first: card.querySelector('.paste-first').textContent,
            body: card.querySelector('.paste-body').textContent,
            text: b.querySelector('.message-body').textContent.replace(card.textContent, '|'),
        };
    """) == {
        "cards": 1, "open": False, "title": "Pasted text · 20 lines", "first": "line 1",
        "body": LOG, "text": "Why?|thanks\n\n```python\nx = 1\n```",
    }


def test_tall_user_bubble_is_capped_until_show_more(view):
    view.append_user_message("\n".join(f"typed {i}" for i in range(80)))
    assert evaluate(view, """
        const b = document.querySelector('.user-message');
        const body = b.querySelector('.message-body');
        const before = [b.classList.contains('capped'), body.clientHeight <= 330];
        b.querySelector('.show-more').click();
        return before.concat([b.classList.contains('expanded'), body.clientHeight > 330,
                              b.querySelector('.show-more').textContent]);
    """) == [True, True, True, True, "Show less"]


def test_opening_a_paste_card_lifts_the_cap(view):
    from pyside_gui.tests.test_conversation_vditor import poll

    view.append_user_message("\n".join(f"typed {i}" for i in range(60)) + f"\n```pasted\n{LOG}\n```")
    evaluate(view, "document.querySelector('.user-message .paste-card').open = true; return 1;")
    assert poll(view, "return document.querySelector('.user-message').classList.contains('expanded');",
                True) is True
