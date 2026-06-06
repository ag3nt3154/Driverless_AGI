"""tools/complete_plan.py — Signal that the active plan's Work-Review cycle is finished.

Returns COMPLETE_PLAN_SENTINEL so the loop can clear active_plan_file and rebuild
the system prompt. After this call, SpawnSubagentTool routes handoffs back to
.dagi/handoffs/ instead of the plan folder.
"""
from agent.base_tool import BaseTool

COMPLETE_PLAN_SENTINEL = "__COMPLETE_PLAN__"


class CompletePlanTool(BaseTool):
    name = "complete_plan"
    description = (
        "Mark the active plan as finished. Clears the active plan reference so future "
        "subagent handoffs return to .dagi/handoffs/ instead of the plan folder. "
        "Call this once all subtasks in the Work-Review cycle are resolved "
        "(every subtask is [x] complete or [!] failed — none remain [ ] pending or [~] in-progress)."
    )
    _parameters: dict = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:  # noqa: PLR6301
        return COMPLETE_PLAN_SENTINEL
