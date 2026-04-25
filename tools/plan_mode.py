from __future__ import annotations

from agent.base_tool import BaseTool

ENTER_PLAN_MODE_SENTINEL = "__ENTER_PLAN_MODE__"
EXIT_PLAN_MODE_SENTINEL = "__EXIT_PLAN_MODE__"


class EnterPlanModeTool(BaseTool):
    name = "enter_plan_mode"
    description = (
        "Switch into plan mode before executing a complex task. "
        "Use this autonomously when the task requires 3 or more distinct implementation steps "
        "across different files, involves architectural trade-offs, or has ambiguous requirements "
        "that risk wasted implementation work. "
        "In plan mode your write/edit access is restricted to the plan document only and bash is "
        "unavailable. Explore the codebase freely with read/grep/find, write the plan, then call "
        "exit_plan_mode to restore full tools and begin implementation immediately. "
        "Do NOT use for single-file edits, clearly scoped bug fixes, or fully-specified tasks."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Brief explanation of why planning is needed before execution.",
            }
        },
        "required": ["reason"],
    }

    def run(self, reason: str) -> str:  # noqa: ARG002
        return ENTER_PLAN_MODE_SENTINEL


class ExitPlanModeTool(BaseTool):
    name = "exit_plan_mode"
    description = (
        "Exit plan mode and restore full tool access (write, edit, bash). "
        "In DAGI-initiated plan mode: call this when the plan is complete to return to the main agent. "
        "In user-initiated plan mode: do NOT call this — the user exits plan mode manually via /exit-plan. "
        "After show_plan confirms approval, simply output your final response and stop."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One-sentence summary of what the plan covers.",
            }
        },
        "required": ["summary"],
    }

    def __init__(self, show_plan_tool: "object | None" = None) -> None:
        self._show_plan_tool = show_plan_tool

    def run(self, summary: str) -> str:  # noqa: ARG002
        if self._show_plan_tool is not None:
            # User-initiated plan mode: exit is controlled by the user via /exit-plan in the CLI.
            return (
                "Do not call this tool. "
                "The user exits plan mode by typing /exit-plan in the CLI. "
                "Simply output your final response and stop."
            )
        return EXIT_PLAN_MODE_SENTINEL
