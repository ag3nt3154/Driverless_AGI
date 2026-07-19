from __future__ import annotations

from agent.base_tool import BaseTool

ENTER_PLAN_MODE_SENTINEL = "__ENTER_PLAN_MODE__"
EXIT_PLAN_MODE_SENTINEL = "__EXIT_PLAN_MODE__"


class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    description = (
        "Think before you code. Switches to a structured planning phase where "
        "you outline your approach, identify edge cases, and design your "
        "solution before writing any implementation. Produces higher-quality "
        "first attempts and fewer debug iterations. Use this at the start of "
        "complex tasks — especially when correctness semantics are subtle."
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
    description = "Exit plan mode. Restores full tool access."
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
