"""tests/test_plan_status_board.py — Live plan status board rendering + prefix caching."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.loop import AgentConfig, AgentLoop


def _make_loop(project_path: Path, active_plan_file: str | None = None) -> AgentLoop:
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
        loop = AgentLoop(config=config, _registry=fake_registry, _tracker=fake_tracker)

    loop.tracker = fake_tracker
    loop.registry = fake_registry
    return loop


PLAN_TEXT = """\
# Plan: Test Feature

## Subtasks

### Subtask 1: [x] Add escalate_issue tool
**Goal:** Done.

### Subtask 2: [~] Wire runner escalation detection
**Goal:** In progress.

### Subtask 3: [ ] Update plan-work-review skill
**Goal:** Pending.

### Subtask 4: [!] Add status board renderer
**Goal:** Failed once.
"""


class TestPlanStatusBoardRendering:
    def test_status_board_lists_all_subtasks_with_markers(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        tail = loop._build_active_plan_tail()

        assert "## Plan Status" in tail
        assert "[x] Add escalate_issue tool" in tail
        assert "[~] Wire runner escalation detection" in tail
        assert "[ ] Update plan-work-review skill" in tail
        assert "[!] Add status board renderer" in tail

    def test_no_active_plan_returns_empty_tail(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)

        assert loop._build_active_plan_tail() == ""

    def test_plan_mode_active_returns_empty_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))
        loop.config.plan_mode = True

        assert loop._build_active_plan_tail() == ""

    def test_malformed_plan_file_does_not_raise(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("not a real plan, no headings at all", encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        tail = loop._build_active_plan_tail()

        assert "## Active Plan" in tail  # pointer section still renders

    def test_missing_plan_file_does_not_raise(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=str(tmp_path / "does_not_exist.md"))

        tail = loop._build_active_plan_tail()

        assert "## Active Plan" in tail


class TestSystemPrefixCaching:
    def test_system_prefix_set_after_init(self, tmp_path):
        loop = _make_loop(tmp_path, active_plan_file=None)

        assert isinstance(loop._system_prefix, str)
        assert len(loop._system_prefix) > 0

    def test_system_prefix_excludes_active_plan_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        assert "## Active Plan" not in loop._system_prefix
        assert "## Plan Status" not in loop._system_prefix

    def test_full_system_string_equals_prefix_plus_tail(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(PLAN_TEXT, encoding="utf-8")
        loop = _make_loop(tmp_path, active_plan_file=str(plan_file))

        full = loop._messages[0]["content"]
        assert full == loop._system_prefix + loop._build_active_plan_tail()
