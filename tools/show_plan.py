from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks


class ShowPlanTool(BaseTool):
    name = "show_plan"
    description = (
        "Render the current plan document to the user. "
        "In interactive mode, also prompts the user for modifications and returns their response. "
        "In autonomous mode, renders the plan and returns auto-approval immediately. "
        "Call this after the plan file is fully written."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, plan_file: Path, callbacks: "AgentCallbacks | None", interactive: bool = True) -> None:
        self._plan_file = plan_file
        self._callbacks = callbacks
        self._interactive = interactive

    def run(self) -> str:
        try:
            contents = self._plan_file.read_text(encoding="utf-8")
        except Exception as exc:
            return f"[show_plan] Could not read plan file: {exc}"

        if self._callbacks is not None:
            self._callbacks.on_assistant_text(f"\n---\n\n## Plan Complete\n\n{contents}")

        if not self._interactive:
            return "Plan rendered. Auto-approved (autonomous mode). Proceed to execution."

        if self._callbacks is None:
            return "Plan approved by the user. Call exit_plan_mode, then proceed to Phase 2 execution."

        self._callbacks.on_plan_shown()
        answer = self._callbacks.on_ask_user("Do you have any modifications?", [], None)
        answer_clean = answer.strip().lower()
        if answer_clean in {"", "n", "no", "nope", "none", "no modifications", "no changes",
                            "looks good", "good", "proceed", "ok", "okay", "approved", "approve"}:
            return "Plan approved by the user. Call exit_plan_mode, then proceed to Phase 2 execution."
        return (
            f"Modifications requested: {answer}\n\n"
            "Revise the plan file to incorporate the above feedback, "
            "then call show_plan again."
        )
