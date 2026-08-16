"""tests/test_dynamic_context.py — Dynamic context board tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentConfig, AgentLoop


def _make_loop(
    project_path: Path,
    active_plan_file: str | None = None,
    python_env: str = "",
) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=project_path,
        active_plan_file=active_plan_file,
        python_env=python_env,
    )
    fake_registry = MagicMock()
    fake_registry.get_openai_tools_list.return_value = []
    fake_registry.list_tools.return_value = []
    fake_tracker = MagicMock()
    fake_tracker.record_system = MagicMock()
    fake_tracker.record_user = MagicMock()
    fake_tracker.record_assistant = MagicMock()

    with (
        patch("agent.loop.SessionTracker", return_value=fake_tracker),
        patch("openai.OpenAI"),
        patch.object(Path, "exists", return_value=False),
    ):
        loop = AgentLoop(
            config=config,
            _registry=fake_registry,
            _tracker=fake_tracker,
        )
    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


PLAN_TEXT = """\
# Plan: Test Feature

## Subtasks

### Task 1: [x] Setup
**Goal:** Done.

### Task 2: [~] Implement
**Goal:** In progress.

### Task 3: [ ] Test
**Goal:** Pending.
"""

_SENTINEL = "## Session Context"


class TestDynamicContextBoardRendering:
    def test_board_contains_sentinel(self, tmp_path):
        loop = _make_loop(tmp_path, python_env="conda:dagi")
        board = loop._build_dynamic_context()
        assert _SENTINEL in board

    def test_board_contains_python_env(self, tmp_path):
        loop = _make_loop(tmp_path, python_env="conda:dagi")
        board = loop._build_dynamic_context()
        assert "Python env: conda:dagi" in board

    def test_board_contains_plan_status(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(
            tmp_path,
            active_plan_file=str(plan_file),
            python_env="conda:dagi",
        )
        board = loop._build_dynamic_context()
        assert "1.[x]" in board or "[x]" in board
        assert "2.[~]" in board or "[~]" in board
        assert "3.[ ]" in board or "[ ]" in board

    def test_board_shows_active_task(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(
            tmp_path,
            active_plan_file=str(plan_file),
            python_env="conda:dagi",
        )
        board = loop._build_dynamic_context()
        assert "Implement" in board  # first in_progress task

    def test_board_without_plan(self, tmp_path):
        loop = _make_loop(tmp_path, python_env="venv:.venv")
        board = loop._build_dynamic_context()
        assert "Python env: venv:.venv" in board
        assert "Plan:" not in board
        assert "Status:" not in board

    def test_board_without_python_env_or_plan(self, tmp_path):
        loop = _make_loop(tmp_path)
        board = loop._build_dynamic_context()
        assert _SENTINEL in board
        # Board should still render (even if sparse)


class TestDynamicContextBoardInjection:
    def test_refresh_appends_board_at_end(self, tmp_path):
        """The board trails the request without joining the conversation."""
        loop = _make_loop(tmp_path, python_env="conda:dagi")
        initial_count = len(loop._messages)

        loop._refresh_dynamic_context()

        assert len(loop._messages) == initial_count
        request = loop._build_request_messages()
        assert request[-1]["role"] == "system"
        assert _SENTINEL in request[-1]["content"]

    def test_refresh_replaces_existing_board(self, tmp_path):
        loop = _make_loop(tmp_path, python_env="conda:dagi")

        loop._refresh_dynamic_context()
        loop._refresh_dynamic_context()
        loop._refresh_dynamic_context()

        board_count = sum(
            1 for m in loop._build_request_messages()
            if m.get("role") == "system"
            and _SENTINEL in str(m.get("content", ""))
        )
        assert board_count == 1

    def test_system_prefix_does_not_contain_python_env(self, tmp_path):
        loop = _make_loop(tmp_path, python_env="conda:dagi")
        assert "DEFAULT_PYTHON_ENV" not in loop._system_prefix
        assert "conda:dagi" not in loop._system_prefix

    def test_system_prefix_does_not_contain_plan_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(
            tmp_path, active_plan_file=str(plan_file),
        )
        assert "## Active Plan" not in loop._system_prefix
        assert "## Plan Status" not in loop._system_prefix
        assert "## Session Context" not in loop._system_prefix

    def test_messages_0_unchanged_after_refresh(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(
            tmp_path,
            active_plan_file=str(plan_file),
            python_env="conda:dagi",
        )
        msg0_before = loop._messages[0]["content"]

        plan_file.write_text(
            PLAN_TEXT.replace("[~]", "[x]"), encoding="utf-8",
        )
        loop._refresh_dynamic_context()

        assert loop._messages[0]["content"] == msg0_before

    def test_board_reflects_plan_changes(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(
            tmp_path,
            active_plan_file=str(plan_file),
            python_env="conda:dagi",
        )

        loop._refresh_dynamic_context()
        assert "[~]" in loop._build_request_messages()[-1]["content"]

        plan_file.write_text(
            PLAN_TEXT.replace("[~]", "[x]"), encoding="utf-8",
        )
        loop._refresh_dynamic_context()

        board = loop._build_request_messages()[-1]["content"]
        assert "[~]" not in board
        assert board.count("[x]") == 2

    def test_compaction_safe_no_crash_after_pop(self, tmp_path):
        """Simulate compaction removing messages between refreshes."""
        loop = _make_loop(tmp_path, python_env="conda:dagi")
        loop._refresh_dynamic_context()

        # Simulate compaction wiping the conversation
        loop._messages[:] = [loop._messages[0]]

        # Should not crash — the board is rebuilt independently of _messages
        loop._refresh_dynamic_context()
        assert _SENTINEL in loop._build_request_messages()[-1]["content"]
