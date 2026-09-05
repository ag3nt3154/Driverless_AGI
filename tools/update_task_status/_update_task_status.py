"""tools/update_task_status — Programmatic plan task status updates.

Replaces the old ``complete_plan`` tool. Updates the status marker in the
plan file on disk and returns a sentinel when all tasks are resolved,
signalling the loop to auto-clear the active plan.
"""
from __future__ import annotations

from pathlib import Path

from typing import TYPE_CHECKING

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult
from tools._plan_parser import update_task_marker

if TYPE_CHECKING:
    from agent.loop import AgentConfig

_RESOLVED = {"complete", "failed"}


class UpdateTaskStatusTool(BaseTool):
    name = "update_task_status"
    description = (
        "Update a task's status in the active plan file. "
        "Provide the task number and new status. When all tasks "
        "are resolved (complete or failed), the plan is "
        "automatically marked finished."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "integer",
                "description": "Task number (e.g. 3 for Task 3).",
            },
            "status": {
                "type": "string",
                "enum": ["pending", "in_progress", "complete", "failed"],
                "description": "New status for the task.",
            },
        },
        "required": ["task", "status"],
    }

    def __init__(
        self,
        plan_path: Path | None = None,
        config: "AgentConfig | None" = None,
        **_: object,
    ) -> None:
        super().__init__()
        self._static_plan_path = plan_path
        self._config = config

    def run(self, task: int, status: str) -> ToolResult:
        # Config-based path is preferred so SET_ACTIVE_PLAN side effects propagate.
        if self._config is not None and self._config.active_plan_file:
            plan_path: Path | None = Path(self._config.active_plan_file)
        else:
            plan_path = self._static_plan_path
        if plan_path is None:
            return ToolResult(output="Error: no active plan file.")

        try:
            statuses = update_task_marker(
                plan_path, task_number=task, new_status=status,
            )
        except (ValueError, OSError) as exc:
            return ToolResult(output=f"Error: {exc}")

        marker_map = {
            "pending": " ", "in_progress": "~",
            "complete": "x", "failed": "!",
        }
        lines = [
            f"{i}. [{marker_map.get(s['status'], '?')}] {s['name']}"
            for i, s in enumerate(statuses, start=1)
        ]
        board = "Status updated.\n" + "\n".join(lines)

        all_resolved = all(s["status"] in _RESOLVED for s in statuses)
        if all_resolved:
            board += "\n\nAll tasks resolved — plan complete."
            return ToolResult(output=board, side_effect=SideEffect.ALL_TASKS_RESOLVED)
        return ToolResult(output=board)
