"""tests/test_git_tools_registration.py — Git tools appear in (or are absent from)
the main tool registry as expected."""
from __future__ import annotations

from pathlib import Path

from agent.tools import create_tool_registry


class TestGitToolsRegistration:
    def test_all_new_git_tools_registered(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        expected = {
            "git_status", "git_diff", "git_log", "git_branch",
            "git_checkout", "git_add", "git_commit", "git_reset",
        }
        assert expected.issubset(names)

    def test_git_rollback_not_registered(self):
        reg = create_tool_registry(cwd=Path("."))
        names = {n for n, _ in reg.list_tools()}
        assert "git_rollback" not in names
