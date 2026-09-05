"""tools/create_plan — scaffold a new plan directory and plan.md file."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentConfig


class CreatePlanTool(BaseTool):
    name = "create_plan"
    description = (
        "Create a new plan directory under .dagi/plans/ with a scaffolded "
        "plan.md file. Returns the path to the plan file so you can write "
        "your plan into it."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task_summary": {
                "type": "string",
                "description": (
                    "Short kebab-case slug summarising the task, "
                    "e.g. 'fix-login-bug'. Used in the plan title."
                ),
            },
        },
        "required": ["task_summary"],
    }

    def __init__(self, config: "AgentConfig | None" = None, **_: object) -> None:
        self._config = config

    def run(self, task_summary: str) -> str:
        task_summary = task_summary.strip()
        if not task_summary:
            return "Error: task_summary is required."

        project_path = (
            Path(self._config.project_path)
            if self._config else Path(".").resolve()
        )
        plans_dir = project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # The timestamp alone has 1-second resolution; two calls in the same
        # second would silently overwrite each other. A short uuid suffix
        # guarantees a distinct directory per call.
        plan_dir = plans_dir / f"plan_{ts}_{uuid.uuid4().hex[:8]}"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(
            f"# Plan: {task_summary}\n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Subtasks\n\n"
            "### Subtask 1: [ ] \n"
            "**Goal:** \n"
            "**Requirements:**\n"
            "- \n"
            "**Acceptance Criteria:**\n"
            "- \n"
            "#### Tests\n\n"
            "## Notes\n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )

        return (
            f"Plan scaffolded at: {plan_file}\n"
            f"Plan directory: {plan_dir}\n\n"
            "Write your plan into the plan file, then call "
            "set_active_plan to associate it with this session."
        )
