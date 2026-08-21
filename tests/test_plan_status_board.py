"""tests/test_plan_status_board.py — Dynamic context board (migrated)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentConfig, AgentLoop


def _make_loop(
    project_path: Path,
    active_plan_file: str | None = None,
) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        project_path=project_path,
        active_plan_file=active_plan_file,
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

### Subtask 1: [x] Add write_handoff tool
**Goal:** Done.

### Subtask 2: [~] Wire runner handoff detection
**Goal:** In progress.

### Subtask 3: [ ] Update plan-work-review skill
**Goal:** Pending.

### Subtask 4: [!] Add status board renderer
**Goal:** Failed once.
"""


class TestDynamicContextRendering:
    def test_board_lists_all_tasks_with_markers(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        board = loop._build_dynamic_context()

        assert "## Session Context" in board
        assert "[x]" in board
        assert "[~]" in board
        assert "[ ]" in board
        assert "[!]" in board

    def test_no_active_plan_omits_plan_lines(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)

        board = loop._build_dynamic_context()

        assert "## Session Context" in board
        assert "Plan:" not in board
        assert "Status:" not in board

    def test_plan_mode_active_omits_plan_lines(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))
        loop.config.plan_mode = True

        board = loop._build_dynamic_context()

        assert "Status:" not in board

    def test_malformed_plan_no_crash(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("not a plan", encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        board = loop._build_dynamic_context()

        assert "## Session Context" in board
        assert "Plan:" in board

    def test_missing_plan_file_no_crash(self, tmp_path):
        loop = _make_loop(
            tmp_path,
            active_plan_file=str(tmp_path / "missing.md"),
        )

        board = loop._build_dynamic_context()

        assert "## Session Context" in board


class TestStaticPrefixClean:
    def test_prefix_excludes_python_env(self, tmp_path):
        loop = _make_loop(tmp_path)
        assert "DEFAULT_PYTHON_ENV" not in loop._system_prefix

    def test_prefix_excludes_plan_content(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        assert "## Active Plan" not in loop._system_prefix
        assert "## Plan Status" not in loop._system_prefix
        assert "## Session Context" not in loop._system_prefix


class TestRefreshUpdatesLastMessage:
    def test_board_at_messages_end(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        loop._refresh_dynamic_context()

        last = loop._build_request_messages()[-1]
        assert last["role"] == "system"
        assert "## Session Context" in last["content"]

    def test_messages_0_unchanged_after_refresh(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))
        msg0 = loop._messages[0]["content"]

        plan_file.write_text(
            PLAN_TEXT.replace("[~]", "[x]"), encoding="utf-8",
        )
        loop._refresh_dynamic_context()

        assert loop._messages[0]["content"] == msg0

    def test_board_reflects_disk_changes(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        loop._refresh_dynamic_context()
        assert "[~]" in loop._build_request_messages()[-1]["content"]

        plan_file.write_text(
            PLAN_TEXT.replace(
                "### Subtask 2: [~]",
                "### Subtask 2: [x]",
            ),
            encoding="utf-8",
        )
        loop._refresh_dynamic_context()

        last = loop._build_request_messages()[-1]["content"]
        assert "[~]" not in last
