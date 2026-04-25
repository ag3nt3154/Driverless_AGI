from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks

_NO_MODIFICATION_PHRASES = frozenset({
    "", "n", "no", "nope", "none", "no modifications", "no changes",
    "looks good", "good", "proceed", "ok", "okay", "approved", "approve",
})


class ShowPlanTool(BaseTool):
    name = "show_plan"
    description = (
        "Display the current plan document to the user and ask if they have modifications. "
        "Call this exactly once after the plan document is fully written. "
        "If the user requests modifications, revise the plan file and call show_plan again. "
        "Only call exit_plan_mode after the user confirms no modifications."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, plan_file: Path, callbacks: "AgentCallbacks") -> None:
        self._plan_file = plan_file
        self._callbacks = callbacks
        self._approved: bool = False

    def run(self) -> str:
        try:
            contents = self._plan_file.read_text(encoding="utf-8")
        except Exception as exc:
            return f"[show_plan] Could not read plan file: {exc}"
        self._callbacks.on_assistant_text(f"\n---\n\n## Plan Complete\n\n{contents}")
        answer = self._callbacks.on_ask_user("Do you have any modifications?", [])
        if answer.strip().lower() in _NO_MODIFICATION_PHRASES:
            self._approved = True
            return (
                "Plan approved by the user. "
                "Write a brief summary of the plan to the user, then stop. "
                "Do NOT call exit_plan_mode — the user will type /exit-plan in the CLI "
                "when they are ready to begin implementation."
            )
        return (
            f"Modifications requested: {answer}\n\n"
            "Revise the plan file to incorporate the above feedback, "
            "then call show_plan again."
        )
