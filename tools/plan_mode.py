from __future__ import annotations

from agent.base_tool import BaseTool

ENTER_PLAN_MODE_SENTINEL = "__ENTER_PLAN_MODE__"
EXIT_PLAN_MODE_SENTINEL = "__EXIT_PLAN_MODE__"


class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    description = (
        "Switch to plan mode. Restricts tools to read/grep/find and plan-file write only. "
        "Pass mode='interactive' when invoked by the user (plan requires approval before execution). "
        "Pass mode='autonomous' when DAGI initiates internally (plan is auto-approved). "
        "task_summary is a short kebab-case slug describing the task (e.g. 'fix-git-tools') — "
        "it seeds the plan title and names the git branch auto-created for this task."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["interactive", "autonomous"],
                "description": "interactive: user must approve the plan. autonomous: plan is auto-approved.",
            },
            "task_summary": {
                "type": "string",
                "description": "Short kebab-case slug summarizing the task, e.g. 'fix-git-tools'.",
            },
        },
        "required": ["mode", "task_summary"],
    }

    def run(self, mode: str, task_summary: str) -> str:  # noqa: ARG002
        return f"{ENTER_PLAN_MODE_SENTINEL}:{mode}"


class ExitPlanModeTool(BaseTool):
    name = "exit_plan_mode"
    description = (
        "Restore full tool access. "
        "Call after the user approves the plan (before proceeding to execution) "
        "or when aborting (cancel path)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One-sentence summary of what the plan covers, or 'cancelled' if aborting.",
            }
        },
        "required": ["summary"],
    }

    def run(self, summary: str) -> str:  # noqa: ARG002
        return EXIT_PLAN_MODE_SENTINEL
