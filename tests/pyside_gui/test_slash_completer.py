from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pyside_gui.commands import SlashCommandHandler, UIWidgets


def _make_handler() -> SlashCommandHandler:
    widgets = UIWidgets(
        conversation=MagicMock(),
        right_sidebar=MagicMock(),
        left_sidebar=MagicMock(),
    )
    config = MagicMock()
    handler = SlashCommandHandler(widgets, config, Path("."))
    return handler


class TestCompletions:
    def test_includes_builtin_commands(self):
        handler = _make_handler()
        names = [name for name, _desc in handler.completions()]
        assert "/help" in names
        assert "/exit" in names
        assert "/clear" in names

    def test_includes_loaded_skills(self):
        handler = _make_handler()
        skill = MagicMock()
        skill.name = "test-skill"
        skill.description = "A test skill"
        handler._skill_map = {"/test-skill": skill}
        names = [name for name, _desc in handler.completions()]
        assert "/test-skill" in names

    def test_includes_loaded_workflows(self):
        handler = _make_handler()
        wf = MagicMock()
        wf.name = "deploy"
        wf.description = "Deploy workflow"
        handler._workflow_map = {"/deploy": wf}
        names = [name for name, _desc in handler.completions()]
        assert "/deploy" in names

    def test_no_duplicates_even_with_skill_name_collision(self):
        handler = _make_handler()
        skill = MagicMock()
        skill.name = "help"  # collides with /help builtin
        skill.description = "Override"
        handler._skill_map = {"/help": skill}
        names = [name for name, _desc in handler.completions()]
        assert names.count("/help") == 1

    def test_skill_description_included(self):
        handler = _make_handler()
        skill = MagicMock()
        skill.name = "my-skill"
        skill.description = "My skill description"
        handler._skill_map = {"/my-skill": skill}
        pairs = dict(handler.completions())
        assert pairs["/my-skill"] == "My skill description"

    def test_none_description_becomes_empty_string(self):
        handler = _make_handler()
        skill = MagicMock()
        skill.name = "no-desc"
        skill.description = None
        handler._skill_map = {"/no-desc": skill}
        pairs = dict(handler.completions())
        assert pairs["/no-desc"] == ""


from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from pyside_gui.slash_completer import SlashCompleterPopup


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class TestSlashCompleterPopup:
    def test_set_items_populates_list(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit"), ("/clear", "Clear")]
        popup.set_items(items)
        assert popup.count() == 3

    def test_filter_narrows_list(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit"), ("/clear", "Clear")]
        popup.set_items(items)
        popup.apply_filter("/he")
        visible = [popup.item(i) for i in range(popup.count())
                   if not popup.item(i).isHidden()]
        assert len(visible) == 1
        assert visible[0].data(Qt.ItemDataRole.UserRole) == "/help"

    def test_filter_empty_prefix_shows_all(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit")]
        popup.set_items(items)
        popup.apply_filter("/")
        visible = [popup.item(i) for i in range(popup.count())
                   if not popup.item(i).isHidden()]
        assert len(visible) == 2

    def test_filter_no_match_hides_all(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit")]
        popup.set_items(items)
        popup.apply_filter("/zzz")
        visible = [popup.item(i) for i in range(popup.count())
                   if not popup.item(i).isHidden()]
        assert len(visible) == 0

    def test_selected_command_returns_name(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit")]
        popup.set_items(items)
        popup.setCurrentRow(0)
        assert popup.selected_command() == "/help"

    def test_move_selection_wraps(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit"), ("/clear", "Clear")]
        popup.set_items(items)
        popup.apply_filter("/")
        popup.setCurrentRow(0)
        popup.move_selection(1)
        assert popup.currentRow() == 1
        popup.move_selection(1)
        assert popup.currentRow() == 2
        popup.move_selection(1)
        assert popup.currentRow() == 0  # wraps

    def test_valid_commands_highlighted(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help")]
        popup.set_items(items)
        item = popup.item(0)
        fg = item.foreground().color().name()
        assert fg == "#cdd6f4"  # Catppuccin Mocha text color

    def test_visible_count_after_filter(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit"), ("/hist", "History")]
        popup.set_items(items)
        popup.apply_filter("/h")
        assert popup.visible_count() == 2

    def test_move_selection_backward_wraps(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/clear", "Clear"), ("/exit", "Exit"), ("/help", "Help")]
        popup.set_items(items)
        popup.apply_filter("/")
        popup.setCurrentRow(0)
        popup.move_selection(-1)
        # Should wrap to last visible item
        assert popup.currentRow() == 2

    def test_selected_command_returns_none_after_no_match(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit")]
        popup.set_items(items)
        popup.apply_filter("/zzz")
        assert popup.selected_command() is None

    def test_move_selection_skips_hidden_items(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/aa", "AA"), ("/bb", "BB"), ("/cc", "CC")]
        popup.set_items(items)
        popup.apply_filter("/a")  # only /aa visible
        popup.move_selection(1)   # only one visible item, should stay on /aa
        assert popup.selected_command() == "/aa"

    def test_popup_reshows_after_no_match_filter(self, qapp):
        popup = SlashCompleterPopup(None)
        items = [("/help", "Show help"), ("/exit", "Exit")]
        popup.set_items(items)
        popup.apply_filter("/zzz")   # no match → hidden
        assert not popup.isVisible()
        popup.apply_filter("/he")    # matches → should show again
        assert popup.isVisible()


from pyside_gui.prompt_input import PromptInput


class TestPromptInputCompleter:
    def test_completer_created(self, qapp):
        prompt = PromptInput()
        assert hasattr(prompt, "_completer")

    def test_set_completions_stores_items(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help"), ("/exit", "Exit")])
        assert len(prompt._completer._all_items) == 2

    def test_typing_slash_shows_popup(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help"), ("/exit", "Exit")])
        prompt._editor.setPlainText("/")
        # signal fires automatically from textChanged connection
        assert prompt._completer.isVisible()

    def test_typing_space_hides_popup(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/help ")
        # signal fires automatically from textChanged connection
        assert not prompt._completer.isVisible()

    def test_no_slash_prefix_hides_popup(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("hello")
        # signal fires automatically from textChanged connection
        assert not prompt._completer.isVisible()

    def test_accept_completion_replaces_text(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help"), ("/exit", "Exit")])
        prompt._editor.setPlainText("/he")
        prompt._on_text_changed()
        prompt._accept_completion()
        assert prompt._editor.toPlainText() == "/help "

    def test_accept_completion_hides_popup(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/he")
        prompt._on_text_changed()
        prompt._accept_completion()
        assert not prompt._completer.isVisible()

    def test_accept_completion_noop_when_no_selection(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/zzz")
        prompt._on_text_changed()  # no match, popup hidden
        original = prompt._editor.toPlainText()
        prompt._accept_completion()
        assert prompt._editor.toPlainText() == original

    def test_empty_completions_slash_does_not_crash(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([])
        prompt._editor.setPlainText("/")
        # signal fires
        assert not prompt._completer.isVisible()


from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import QEvent


def _make_key_event(key, modifiers=Qt.KeyboardModifier.NoModifier):
    return QKeyEvent(QEvent.Type.KeyPress, key, modifiers, "", False)


class TestEditorKeyHandling:
    def test_tab_accepts_completion(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help"), ("/exit", "Exit")])
        prompt._editor.setPlainText("/he")
        assert prompt._completer.isVisible()
        event = _make_key_event(Qt.Key.Key_Tab)
        prompt._editor.keyPressEvent(event)
        assert prompt._editor.toPlainText() == "/help "
        assert not prompt._completer.isVisible()

    def test_escape_hides_popup(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/")
        assert prompt._completer.isVisible()
        event = _make_key_event(Qt.Key.Key_Escape)
        prompt._editor.keyPressEvent(event)
        assert not prompt._completer.isVisible()

    def test_down_arrow_moves_selection(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/clear", "Clear"), ("/exit", "Exit"), ("/help", "Help")])
        prompt._editor.setPlainText("/")
        initial_cmd = prompt._completer.selected_command()
        event = _make_key_event(Qt.Key.Key_Down)
        prompt._editor.keyPressEvent(event)
        after_cmd = prompt._completer.selected_command()
        assert after_cmd != initial_cmd

    def test_up_arrow_moves_selection(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/clear", "Clear"), ("/exit", "Exit"), ("/help", "Help")])
        prompt._editor.setPlainText("/")
        # Move down first to have somewhere to go up from
        prompt._completer.move_selection(1)
        before = prompt._completer.currentRow()
        event = _make_key_event(Qt.Key.Key_Up)
        prompt._editor.keyPressEvent(event)
        assert prompt._completer.currentRow() == before - 1

    def test_enter_with_popup_accepts_and_does_not_submit(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/he")
        assert prompt._completer.isVisible()
        submitted = []
        prompt.submitted.connect(lambda s: submitted.append(s))
        event = _make_key_event(Qt.Key.Key_Return)
        prompt._editor.keyPressEvent(event)
        assert prompt._editor.toPlainText() == "/help "
        assert len(submitted) == 0

    def test_tab_without_popup_does_not_insert_tab(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("hello")
        assert not prompt._completer.isVisible()
        event = _make_key_event(Qt.Key.Key_Tab)
        prompt._editor.keyPressEvent(event)
        assert prompt._editor.toPlainText() == "hello"

    def test_down_arrow_without_popup_passes_through(self, qapp):
        """Down arrow when popup is not visible should not crash."""
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("hello")
        assert not prompt._completer.isVisible()
        event = _make_key_event(Qt.Key.Key_Down)
        # Should not raise; QPlainTextEdit handles it normally
        prompt._editor.keyPressEvent(event)

    def test_shift_enter_with_popup_inserts_newline_not_accept(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/he")
        assert prompt._completer.isVisible()
        submitted = []
        prompt.submitted.connect(lambda s: submitted.append(s))
        event = _make_key_event(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        prompt._editor.keyPressEvent(event)
        # Should NOT accept completion (popup still visible or text still /he area)
        # and should NOT submit
        assert len(submitted) == 0
        # text should have a newline appended (Shift+Enter inserts newline)
        assert "\n" in prompt._editor.toPlainText()

    def test_ctrl_enter_with_popup_inserts_newline_not_accept(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("/he")
        assert prompt._completer.isVisible()
        submitted = []
        prompt.submitted.connect(lambda s: submitted.append(s))
        event = _make_key_event(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        prompt._editor.keyPressEvent(event)
        # Should NOT accept completion
        assert prompt._editor.toPlainText() != "/help "
        # Should NOT submit
        assert len(submitted) == 0

    def test_shift_tab_with_popup_does_not_accept(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help"), ("/exit", "Exit")])
        prompt._editor.setPlainText("/")
        assert prompt._completer.isVisible()
        original_text = prompt._editor.toPlainText()
        event = _make_key_event(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        prompt._editor.keyPressEvent(event)
        # Shift+Tab should NOT accept completion
        assert prompt._editor.toPlainText() == original_text

    def test_enter_without_popup_submits(self, qapp):
        prompt = PromptInput()
        prompt.set_completions([("/help", "Show help")])
        prompt._editor.setPlainText("hello world")
        assert not prompt._completer.isVisible()
        submitted = []
        prompt.submitted.connect(lambda s: submitted.append(s))
        event = _make_key_event(Qt.Key.Key_Return)
        prompt._editor.keyPressEvent(event)
        assert len(submitted) == 1
        assert submitted[0].text == "hello world"
