"""tests/test_update_task_status.py — UpdateTaskStatusTool unit tests."""
from __future__ import annotations

from pathlib import Path

PLAN_TEXT = """\
# Plan: Test Feature

## Subtasks

### Task 1: [x] First task
**Goal:** Done.

### Task 2: [~] Second task
**Goal:** In progress.

### Task 3: [ ] Third task
**Goal:** Pending.
"""

ALMOST_DONE_PLAN = """\
# Plan: Nearly Done

## Subtasks

### Task 1: [x] First task
**Goal:** Done.

### Task 2: [~] Last task
**Goal:** Finishing up.
"""


class TestUpdateTaskStatusTool:
    def test_updates_status_on_disk(self, tmp_path):
        from tools.update_task_status import UpdateTaskStatusTool
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_TEXT, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=2, status="complete")

        text = plan.read_text(encoding="utf-8")
        assert "### Task 2: [x] Second task" in text
        assert "complete" in result.lower() or "[x]" in result

    def test_returns_updated_status_board(self, tmp_path):
        from tools.update_task_status import UpdateTaskStatusTool
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_TEXT, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=3, status="in_progress")

        assert "[~]" in result
        assert "Third task" in result

    def test_auto_complete_sentinel_when_all_resolved(self, tmp_path):
        from tools.update_task_status import (
            UpdateTaskStatusTool, UPDATE_TASK_STATUS_SENTINEL,
        )
        plan = tmp_path / "plan.md"
        plan.write_text(ALMOST_DONE_PLAN, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=2, status="complete")

        assert UPDATE_TASK_STATUS_SENTINEL in result

    def test_no_sentinel_when_tasks_remain(self, tmp_path):
        from tools.update_task_status import (
            UpdateTaskStatusTool, UPDATE_TASK_STATUS_SENTINEL,
        )
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_TEXT, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=2, status="complete")

        assert UPDATE_TASK_STATUS_SENTINEL not in result

    def test_invalid_task_number(self, tmp_path):
        from tools.update_task_status import UpdateTaskStatusTool
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_TEXT, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=99, status="complete")

        assert "not found" in result.lower() or "error" in result.lower()

    def test_schema_exposes_task_and_status(self, tmp_path):
        from tools.update_task_status import UpdateTaskStatusTool
        tool = UpdateTaskStatusTool(plan_path=tmp_path / "plan.md")
        schema = tool.schema()
        props = schema["function"]["parameters"]["properties"]
        assert "task" in props
        assert "status" in props
        assert props["status"]["enum"] == [
            "pending", "in_progress", "complete", "failed",
        ]

    def test_all_failed_also_triggers_sentinel(self, tmp_path):
        from tools.update_task_status import (
            UpdateTaskStatusTool, UPDATE_TASK_STATUS_SENTINEL,
        )
        plan = tmp_path / "plan.md"
        plan.write_text(ALMOST_DONE_PLAN, encoding="utf-8")
        tool = UpdateTaskStatusTool(plan_path=plan)

        result = tool.run(task=2, status="failed")

        assert UPDATE_TASK_STATUS_SENTINEL in result
