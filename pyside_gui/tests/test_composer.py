"""The composer card: auto-grow, send/stop button, model pill."""
from __future__ import annotations

import pytest

from pyside_gui.prompt_input import MAX_EDITOR_HEIGHT, PromptInput


@pytest.fixture
def prompt(qtbot):
    widget = PromptInput()
    widget.resize(700, 200)
    qtbot.addWidget(widget)
    widget.show()
    return widget


def test_editor_grows_with_text_up_to_a_cap(prompt, qtbot):
    one_line = prompt._editor.height()
    prompt._editor.setPlainText("a\nb\nc\nd")
    qtbot.waitUntil(lambda: prompt._editor.height() > one_line)
    prompt._editor.setPlainText("\n".join("x" * 5 for _ in range(200)))
    qtbot.waitUntil(lambda: prompt._editor.height() == MAX_EDITOR_HEIGHT)
    prompt._editor.clear()
    qtbot.waitUntil(lambda: prompt._editor.height() == one_line)


def test_compose_mode_gives_a_tall_editor(prompt):
    prompt.set_compose_mode(True)
    assert prompt._editor.minimumHeight() >= 300
    prompt.set_compose_mode(False)
    assert prompt._editor.maximumHeight() <= MAX_EDITOR_HEIGHT


def test_send_button_submits_text(prompt, qtbot):
    prompt._editor.setPlainText("hello")
    with qtbot.waitSignal(prompt.submitted) as blocker:
        prompt._send_btn.click()
    assert blocker.args[0].text == "hello"
    assert prompt.toPlainText() == ""


def test_send_turns_into_stop_while_running_and_locked(prompt, qtbot):
    prompt.set_running(True)
    prompt.setDisabled(True)
    assert prompt._send_btn.isEnabled()
    assert prompt._send_btn.toolTip().startswith("Stop")
    with qtbot.waitSignal(prompt.stop_requested):
        prompt._send_btn.click()
    # An ask_user question unlocks the editor mid-run: the button sends again.
    prompt.setDisabled(False)
    assert prompt._send_btn.toolTip().startswith("Send")
    prompt.set_running(False)
    assert prompt._send_btn.toolTip().startswith("Send")


def test_model_pill_lists_models_and_emits_selection(prompt, qtbot):
    prompt.set_models(["a-model", "b-model"], "a-model", "A Model")
    assert prompt._model_btn.isVisibleTo(prompt)
    assert prompt._model_btn.text() == "A Model"
    actions = prompt._model_menu.actions()
    assert [a.text() for a in actions] == ["a-model", "b-model"]
    assert [a.isChecked() for a in actions] == [True, False]
    with qtbot.waitSignal(prompt.model_selected) as blocker:
        actions[1].trigger()
    assert blocker.args == ["b-model"]


def test_model_pill_hidden_without_models(prompt):
    prompt.set_models([], "", "")
    assert not prompt._model_btn.isVisibleTo(prompt)


def test_attach_adds_image_files(prompt, tmp_path):
    from PySide6.QtGui import QColor, QImage

    path = tmp_path / "shot.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))
    prompt._add_image_paths([path])
    assert len(prompt._attachments) == 1
    assert prompt._strip.isVisibleTo(prompt)
