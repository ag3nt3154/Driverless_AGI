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


def test_context_meter_hidden_until_known_then_tracks_usage(prompt):
    meter = prompt._context_meter
    assert not meter.isVisibleTo(prompt)
    prompt.set_context_usage(62_000, 100_000)
    assert meter.isVisibleTo(prompt)
    assert meter.usage == pytest.approx(0.62)
    assert meter.toolTip().startswith("Context 62% · 62,000 / 100,000 tokens")
    prompt.set_context_usage(10, 0)  # unknown window
    assert not meter.isVisibleTo(prompt)


@pytest.mark.parametrize("usage, role", [
    (0.0, "fg_secondary"), (0.69, "fg_secondary"), (0.70, "warn"),
    (0.89, "warn"), (0.90, "danger"), (1.3, "danger"),
])
def test_context_meter_colour_thresholds(usage, role):
    from pyside_gui.context_meter import meter_role

    assert meter_role(usage) == role


def test_context_meter_paints_without_error(prompt):
    prompt.set_context_usage(95_000, 100_000)
    image = prompt._context_meter.grab().toImage()
    assert not image.isNull()


def test_sidebar_context_total_feeds_the_meter(prompt, tmp_path):
    from pyside_gui.right_sidebar import RightSidebar

    sidebar = RightSidebar("test", 10_000, 1_000, tmp_path, tmp_path)
    sidebar.context_usage.connect(prompt.set_context_usage)
    sidebar.update_context({"user": 2_000, "assistant": 3_000, "tools": 0, "summary": 0})
    # user + assistant + reserve (no AGENTS.md / system prompt in tmp_path)
    assert prompt._context_meter.usage == pytest.approx(0.6, abs=0.05)
    assert sidebar._context_bar.value() == round(prompt._context_meter.usage * 1000)
    sidebar.deleteLater()
