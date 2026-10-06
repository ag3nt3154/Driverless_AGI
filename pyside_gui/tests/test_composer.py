"""The composer card: auto-grow, send/stop button, attachments; the sidebar model picker."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

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
    prompt.set_running(False)
    prompt.setDisabled(False)
    assert prompt._send_btn.toolTip().startswith("Send")


def test_while_running_the_button_sends_when_there_is_text(prompt, qtbot):
    prompt.set_running(True)
    assert prompt._send_btn.toolTip().startswith("Stop")  # empty: stop
    prompt._editor.setPlainText("also update the tests")
    assert prompt._send_btn.toolTip().startswith("Send")
    with qtbot.waitSignal(prompt.submitted) as blocker:
        prompt._send_btn.click()
    assert blocker.args[0].text == "also update the tests"
    assert prompt._send_btn.toolTip().startswith("Stop")  # cleared again


@pytest.fixture
def sidebar(qtbot, tmp_path):
    from pyside_gui.right_sidebar import RightSidebar

    widget = RightSidebar("test", 10_000, 1_000, tmp_path, tmp_path)
    qtbot.addWidget(widget)
    return widget


def test_composer_has_no_model_pill_or_context_ring(prompt):
    assert not hasattr(prompt, "_model_btn")
    assert not hasattr(prompt, "_context_meter")


def test_sidebar_model_name_opens_picker_and_emits_selection(sidebar, qtbot):
    sidebar.set_models(["a-model", "b-model"], "a-model", "A Model")
    label = sidebar._model_label
    assert label.name == "A Model"
    assert label.text() == "A Model  ▾"
    assert label.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert label.cursor().shape() == Qt.CursorShape.PointingHandCursor
    actions = label._menu.actions()
    assert [a.text() for a in actions] == ["a-model", "b-model"]
    assert [a.isChecked() for a in actions] == [True, False]
    with qtbot.waitSignal(sidebar.model_selected) as blocker:
        actions[1].trigger()
    assert blocker.args == ["b-model"]


def test_sidebar_model_name_not_clickable_without_models(sidebar):
    sidebar.set_models([], "", "Solo")
    assert sidebar._model_label.text() == "Solo"  # no chevron: not a button
    assert sidebar._model_label._menu.isEmpty()
    assert sidebar._model_label.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_attach_adds_image_files(prompt, tmp_path):
    from PySide6.QtGui import QColor, QImage

    path = tmp_path / "shot.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    assert image.save(str(path))
    prompt._add_image_paths([path])
    assert len(prompt._attachments) == 1
    assert prompt._strip.isVisibleTo(prompt)
