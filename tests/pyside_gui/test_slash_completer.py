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

    def test_no_duplicates(self):
        handler = _make_handler()
        names = [name for name, _desc in handler.completions()]
        assert len(names) == len(set(names))
