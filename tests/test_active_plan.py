"""tests/test_active_plan.py — Unit tests for tools/active_plan/_active_plan.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.protocol import SideEffect, ToolResult
from tools.active_plan import CheckActivePlanTool, SetActivePlanTool


def _check_text(result: "ToolResult | str") -> str:
    """Return the text output from either a ToolResult or a plain string."""
    return result.output if isinstance(result, ToolResult) else result


def _make_config(project_path: Path, thread_id: str = "thread-abc") -> MagicMock:
    config = MagicMock()
    config.project_path = project_path
    config.thread_id = thread_id
    return config


def _make_tracker(thread_id: str = "thread-abc") -> MagicMock:
    tracker = MagicMock()
    tracker._thread_id = thread_id
    return tracker


def _no_branch():
    return None


def _branch(name: str = "main"):
    return name


class TestSetActivePlanTool:
    def test_attach_valid_plan_writes_sidecar(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config = _make_config(tmp_path)
        tracker = _make_tracker()
        tool = SetActivePlanTool(config=config, tracker=tracker)

        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = tool.run(str(plan))

        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.SET_ACTIVE_PLAN
        assert result.side_effect_data["path"] == str(plan)
        sidecar = tmp_path / ".dagi" / "session-state" / "thread-abc" / "active-plan.json"
        assert sidecar.exists()
        import json
        data = json.loads(sidecar.read_text())
        assert data["plan_path"] == str(plan)
        assert data["expected_branch"] == "main"

    def test_detach_removes_sidecar(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config = _make_config(tmp_path)
        tracker = _make_tracker()
        tool = SetActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            tool.run(str(plan))

        result = tool.run(None)

        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.SET_ACTIVE_PLAN
        assert result.side_effect_data["path"] is None
        sidecar = tmp_path / ".dagi" / "session-state" / "thread-abc" / "active-plan.json"
        assert not sidecar.exists()

    def test_detach_with_no_sidecar_is_safe(self, tmp_path):
        config = _make_config(tmp_path)
        tool = SetActivePlanTool(config=config)
        result = tool.run(None)
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.SET_ACTIVE_PLAN

    def test_nonexistent_file_returns_error_string(self, tmp_path):
        config = _make_config(tmp_path)
        tool = SetActivePlanTool(config=config)
        result = tool.run(str(tmp_path / "missing.md"))
        assert isinstance(result, str)
        assert "not found" in result.lower()

    def test_path_escape_returns_error_string(self, tmp_path):
        other = tmp_path.parent / "other.md"
        other.write_text("# Other\n")
        config = _make_config(tmp_path)
        tool = SetActivePlanTool(config=config)
        result = tool.run(str(other))
        assert isinstance(result, str)
        assert "escape" in result.lower() or "project root" in result.lower()

    def test_tracker_thread_id_takes_precedence_over_config(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config = _make_config(tmp_path, thread_id="config-tid")
        tracker = _make_tracker(thread_id="tracker-tid")
        tool = SetActivePlanTool(config=config, tracker=tracker)

        with patch("tools.active_plan._active_plan._current_branch", return_value=None):
            tool.run(str(plan))

        sidecar = tmp_path / ".dagi" / "session-state" / "tracker-tid" / "active-plan.json"
        assert sidecar.exists()

    def test_two_thread_ids_write_separate_sidecars(self, tmp_path):
        plan_a = tmp_path / "a.md"
        plan_b = tmp_path / "b.md"
        plan_a.write_text("# A\n")
        plan_b.write_text("# B\n")

        tool_a = SetActivePlanTool(
            config=_make_config(tmp_path, "tid-a"),
            tracker=_make_tracker("tid-a"),
        )
        tool_b = SetActivePlanTool(
            config=_make_config(tmp_path, "tid-b"),
            tracker=_make_tracker("tid-b"),
        )
        with patch("tools.active_plan._active_plan._current_branch", return_value=None):
            tool_a.run(str(plan_a))
            tool_b.run(str(plan_b))

        import json
        data_a = json.loads(
            (tmp_path / ".dagi" / "session-state" / "tid-a" / "active-plan.json")
            .read_text()
        )
        data_b = json.loads(
            (tmp_path / ".dagi" / "session-state" / "tid-b" / "active-plan.json")
            .read_text()
        )
        assert data_a["plan_path"] == str(plan_a)
        assert data_b["plan_path"] == str(plan_b)


class TestCheckActivePlanTool:
    def _attach(self, tmp_path, plan_path, thread_id="thread-abc", branch="main"):
        config = _make_config(tmp_path, thread_id)
        tracker = _make_tracker(thread_id)
        set_tool = SetActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value=branch):
            set_tool.run(str(plan_path))
        return config, tracker

    def test_no_sidecar_returns_absent_message(self, tmp_path):
        config = _make_config(tmp_path)
        tool = CheckActivePlanTool(config=config)
        result = tool.run()
        assert "no active plan" in result.lower()

    def test_check_returns_plan_contents(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# My Plan\n\n## Task 1\n")
        config, tracker = self._attach(tmp_path, plan)
        tool = CheckActivePlanTool(config=config, tracker=tracker)

        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = tool.run()

        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.SET_ACTIVE_PLAN
        assert result.side_effect_data["path"] == str(plan)
        text = _check_text(result)
        assert "My Plan" in text
        assert str(plan) in text

    def test_check_after_file_edit_returns_new_contents(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Original\n")
        config, tracker = self._attach(tmp_path, plan)
        plan.write_text("# Updated\n")

        tool = CheckActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = tool.run()

        text = _check_text(result)
        assert "Updated" in text
        assert "Original" not in text

    def test_stale_pointer_after_rename(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config, tracker = self._attach(tmp_path, plan)
        plan.rename(tmp_path / "plan_renamed.md")

        tool = CheckActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = tool.run()

        assert "stale" in result.lower() or "no longer exists" in result.lower()
        assert str(plan) in result

    def test_branch_mismatch_is_flagged(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config, tracker = self._attach(tmp_path, plan, branch="main")

        tool = CheckActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="feature-x"):
            result = tool.run()

        text = _check_text(result)
        assert "mismatch" in text.lower()
        assert "feature-x" in text

    def test_branch_match_is_confirmed(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n")
        config, tracker = self._attach(tmp_path, plan, branch="main")

        tool = CheckActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = tool.run()

        assert "mismatch" not in _check_text(result).lower()

    def test_two_threads_see_different_plans(self, tmp_path):
        plan_a = tmp_path / "a.md"
        plan_b = tmp_path / "b.md"
        plan_a.write_text("# Plan A\n")
        plan_b.write_text("# Plan B\n")
        config_a, tracker_a = self._attach(tmp_path, plan_a, thread_id="tid-a")
        config_b, tracker_b = self._attach(tmp_path, plan_b, thread_id="tid-b")

        with patch("tools.active_plan._active_plan._current_branch", return_value=None):
            result_a = _check_text(CheckActivePlanTool(config=config_a, tracker=tracker_a).run())
            result_b = _check_text(CheckActivePlanTool(config=config_b, tracker=tracker_b).run())

        assert "Plan A" in result_a
        assert "Plan B" not in result_a
        assert "Plan B" in result_b
        assert "Plan A" not in result_b

    def test_sidecar_survives_tool_reinstantiation(self, tmp_path):
        """Sidecar persists so a new tool instance (new session) reads the old association."""
        plan = tmp_path / "plan.md"
        plan.write_text("# Persistent Plan\n")
        config_orig, tracker_orig = self._attach(tmp_path, plan, thread_id="tid-persist")

        # Simulate new session: fresh config/tracker objects with same thread_id
        config_new = _make_config(tmp_path, "tid-persist")
        tracker_new = _make_tracker("tid-persist")
        tool = CheckActivePlanTool(config=config_new, tracker=tracker_new)
        with patch("tools.active_plan._active_plan._current_branch", return_value=None):
            result = tool.run()

        assert "Persistent Plan" in _check_text(result)


class TestPlanModeCompat:
    """Behavioural tests for Task 4 plan-mode compatibility changes."""

    def _make_loop(self, tmp_path, thread_id="tid-loop"):
        """Build a minimal mock loop with enough attributes for _plan_mode handlers."""
        plan_dir = tmp_path / ".dagi" / "plans" / "plan_001"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text("# Plan\n\n## Subtasks\n\n### Subtask 1: [ ] Do it\n")

        config = MagicMock()
        config.project_path = tmp_path
        config.plan_file = str(plan_file)
        config.active_plan_file = str(plan_file)
        config.thread_id = thread_id

        tracker = MagicMock()
        tracker._thread_id = thread_id

        loop = MagicMock()
        loop.config = config
        loop.tracker = tracker
        return loop, plan_file

    def test_all_tasks_resolved_does_not_clear_active_plan(self, tmp_path):
        from agent._plan_mode import handle_all_tasks_resolved

        loop, plan_file = self._make_loop(tmp_path)
        result = handle_all_tasks_resolved(loop)

        # active_plan_file must not be cleared
        assert loop.config.active_plan_file is not None
        assert "verification" in result.lower() or "final review" in result.lower()
        # Must NOT rebuild — no auto-clear
        loop._rebuild_for_normal_mode.assert_not_called()

    def test_all_tasks_resolved_references_plan_in_message(self, tmp_path):
        from agent._plan_mode import handle_all_tasks_resolved

        loop, plan_file = self._make_loop(tmp_path)
        result = handle_all_tasks_resolved(loop)
        assert str(plan_file) in result or "active plan" in result.lower()

    def test_exit_plan_mode_cancelled_does_not_set_active_plan(self, tmp_path):
        from agent._plan_mode import handle_exit_plan_mode

        loop, plan_file = self._make_loop(tmp_path)
        loop.config.active_plan_file = None
        with patch("agent._plan_mode.get_current_branch", return_value="main"):
            result = handle_exit_plan_mode(loop, {"summary": "cancelled"})

        assert loop.config.active_plan_file is None
        assert "cancel" in result.lower()
        sidecar = tmp_path / ".dagi" / "session-state" / "tid-loop" / "active-plan.json"
        assert not sidecar.exists()

    def test_exit_plan_mode_success_writes_sidecar(self, tmp_path):
        from agent._plan_mode import handle_exit_plan_mode

        loop, plan_file = self._make_loop(tmp_path)
        loop.config.active_plan_file = None
        with patch("agent._plan_mode.get_current_branch", return_value="main"):
            handle_exit_plan_mode(loop, {"summary": "Plan complete."})

        sidecar = tmp_path / ".dagi" / "session-state" / "tid-loop" / "active-plan.json"
        assert sidecar.exists()
        import json
        data = json.loads(sidecar.read_text())
        assert data["plan_path"] == str(plan_file)
        assert data["expected_branch"] == "main"

    def test_exit_plan_mode_success_sets_active_plan_file(self, tmp_path):
        from agent._plan_mode import handle_exit_plan_mode

        loop, plan_file = self._make_loop(tmp_path)
        loop.config.active_plan_file = None
        with patch("agent._plan_mode.get_current_branch", return_value="main"):
            handle_exit_plan_mode(loop, {"summary": "Done."})

        assert loop.config.active_plan_file == str(plan_file)


class TestFailedTaskRetention:
    """Failed tasks must not clear the active plan association."""

    def test_update_task_status_failed_fires_all_tasks_resolved(self, tmp_path):
        """When all tasks are failed, ALL_TASKS_RESOLVED fires (the side effect is correct)."""
        from agent.protocol import SideEffect, ToolResult
        from tools.update_task_status import UpdateTaskStatusTool
        from tools._plan_parser import update_task_marker

        plan = tmp_path / "plan.md"
        plan.write_text(
            "# Plan\n\n## Subtasks\n\n"
            "### Subtask 1: [x] First\n"
            "### Subtask 2: [ ] Second\n",
            encoding="utf-8",
        )
        tool = UpdateTaskStatusTool(plan_path=plan)
        result = tool.run(task=2, status="failed")

        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.ALL_TASKS_RESOLVED

    def test_handle_all_tasks_resolved_message_mentions_verification(self, tmp_path):
        """ALL_TASKS_RESOLVED message must not say 'cleared' — must say verification."""
        from agent._plan_mode import handle_all_tasks_resolved

        plan_dir = tmp_path / ".dagi" / "plans"
        plan_dir.mkdir(parents=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text("# Plan\n")

        config = MagicMock()
        config.project_path = tmp_path
        config.active_plan_file = str(plan_file)
        config.thread_id = "tid"

        loop = MagicMock()
        loop.config = config
        loop.tracker = MagicMock()

        result = handle_all_tasks_resolved(loop)

        assert "cleared" not in result.lower()
        assert "verification" in result.lower() or "final review" in result.lower()
        assert loop.config.active_plan_file is not None

    def test_active_plan_still_readable_after_all_tasks_resolved(self, tmp_path):
        """After all tasks resolve, check_active_plan must still return plan contents."""
        from agent._plan_mode import handle_all_tasks_resolved

        plan = tmp_path / "plan.md"
        plan.write_text("# My Delivery Plan\n\n## Verification\nRun tests.\n")

        # Attach via SetActivePlanTool
        config = _make_config(tmp_path, "tid-delivery")
        tracker = _make_tracker("tid-delivery")
        set_tool = SetActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            set_tool.run(str(plan))

        # Simulate ALL_TASKS_RESOLVED (must not clear association)
        loop_config = MagicMock()
        loop_config.project_path = tmp_path
        loop_config.active_plan_file = str(plan)
        loop_config.thread_id = "tid-delivery"
        loop = MagicMock()
        loop.config = loop_config
        handle_all_tasks_resolved(loop)

        # Plan must still be readable via check_active_plan
        check_tool = CheckActivePlanTool(config=config, tracker=tracker)
        with patch("tools.active_plan._active_plan._current_branch", return_value="main"):
            result = check_tool.run()

        assert "My Delivery Plan" in _check_text(result)
