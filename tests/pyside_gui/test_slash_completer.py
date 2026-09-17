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
