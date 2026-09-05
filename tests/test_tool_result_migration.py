"""Verify each sentinel tool returns ToolResult with correct side_effect."""
from __future__ import annotations

import pytest
from agent.protocol import SideEffect, ToolResult


class TestCreatePlanTool:
    def test_creates_plan_file(self, tmp_path):
        from tools.create_plan._create_plan import CreatePlanTool
        from unittest.mock import MagicMock

        config = MagicMock()
        config.project_path = tmp_path

        result = CreatePlanTool(config=config).run(task_summary="fix-login-bug")
        assert "Plan scaffolded at:" in result
        plans = list((tmp_path / ".dagi" / "plans").glob("plan_*/plan.md"))
        assert len(plans) == 1
        assert "# Plan: fix-login-bug" in plans[0].read_text(encoding="utf-8")

    def test_requires_task_summary(self, tmp_path):
        from tools.create_plan._create_plan import CreatePlanTool
        from unittest.mock import MagicMock

        config = MagicMock()
        config.project_path = tmp_path

        result = CreatePlanTool(config=config).run(task_summary="")
        assert "Error" in result


class TestReloadSkillsTool:
    def test_returns_tool_result(self):
        from tools.reload_skills._reload_skills import ReloadSkillsTool

        result = ReloadSkillsTool().run()
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.RELOAD_SKILLS


class TestSwitchModelTool:
    def test_returns_tool_result(self):
        from tools.switch_model._switch_model import SwitchModelTool

        result = SwitchModelTool().run(target="plan", reason="need reasoning")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.SWITCH_MODEL
        assert result.side_effect_data == {"tier": "plan"}


class TestUpdateTaskStatusTool:
    def test_returns_tool_result_when_all_resolved(self, tmp_path):
        from tools.update_task_status._update_task_status import UpdateTaskStatusTool

        plan = tmp_path / "plan.md"
        plan.write_text("### Task 1: [ ] Do something\n", encoding="utf-8")
        result = UpdateTaskStatusTool(plan_path=plan).run(task=1, status="complete")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.ALL_TASKS_RESOLVED

    def test_returns_tool_result_without_side_effect_when_not_all_resolved(self, tmp_path):
        from tools.update_task_status._update_task_status import UpdateTaskStatusTool

        plan = tmp_path / "plan.md"
        plan.write_text("### Task 1: [ ] Task one\n### Task 2: [ ] Task two\n", encoding="utf-8")
        result = UpdateTaskStatusTool(plan_path=plan).run(task=1, status="complete")
        assert isinstance(result, ToolResult)
        assert result.side_effect is None
