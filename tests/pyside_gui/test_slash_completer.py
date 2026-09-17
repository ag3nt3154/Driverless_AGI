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
