"""Verify each sentinel tool returns ToolResult with correct side_effect."""
from __future__ import annotations

import pytest
from agent.protocol import SideEffect, ToolResult


class TestPlanModeTools:
    def test_enter_plan_mode_returns_tool_result(self):
        from tools.plan_mode._plan_mode import EnterPlanModeTool

        result = EnterPlanModeTool().run(mode="interactive", task_summary="test")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.ENTER_PLAN_MODE
        assert result.side_effect_data == {"mode": "interactive"}

    def test_exit_plan_mode_returns_tool_result(self):
        from tools.plan_mode._plan_mode import ExitPlanModeTool

        result = ExitPlanModeTool().run(summary="done")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.EXIT_PLAN_MODE


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
