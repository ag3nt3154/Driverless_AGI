# .dagi/subagents/review/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
    from agent.parent_context import ParentContextProvider


class ReviewWorkTool(BaseTool):
    name = "review_work"
    description = (
        "General-purpose reviewer. Evaluates any material (plan, diff, "
        "worker handoff, document) against explicit passing criteria. "
        "Returns PASS or ESCALATE with structured findings. "
        "Does not require an active plan or prior worker run."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "material": {
                "type": "string",
                "description": (
                    "What to review: exact file paths, diff base/revision "
                    "(e.g. 'git diff HEAD~1'), or inline content. "
                    "The reviewer will read paths before evaluating."
                ),
            },
            "passing_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Explicit list of criteria that must all be met for PASS.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Background the reviewer needs: plan context, subtask goal, "
                    "prior attempt notes. Optional but strongly recommended."
                ),
            },
            "verification": {
                "type": "string",
                "description": (
                    "Expected verification steps (e.g. test commands to run, "
                    "invariants to check). Optional."
                ),
            },
        },
        "required": ["material", "passing_criteria"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
        parent_context: "ParentContextProvider | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker
        self._session_log = session_log
        self._parent_context = parent_context

    def run(
        self,
        material: str,
        passing_criteria: list[str],
        context: str = "",
        verification: str = "",
    ) -> str:
        from tools._handoff_format import dispatch_status_result, format_handoff_result

        if not material or not material.strip():
            return "Error: material must not be empty — provide file paths, a diff spec, or inline content."
        if not passing_criteria:
            return "Error: passing_criteria must be a non-empty list."

        task_body = _compose_review_task(material, passing_criteria, context, verification)

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("review")

        result = _subagent_api.run_subagent(
            task=task_body,
            preset="review",
            project_path=self._config.project_path,
            on_event=on_event,
            parent_log=self._session_log,
            parent_context=self._parent_context,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(str(result.handoff_path), unverified=unverified)
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "message": result.message,
                "exit_code": result.exit_code,
                "output_tail": result.output_tail,
            },
            "review",
        )


def _compose_review_task(
    material: str,
    passing_criteria: list[str],
    context: str,
    verification: str,
) -> str:
    """Build the review task body from explicit caller-supplied fields."""
    sections: list[str] = []

    if context and context.strip():
        sections.append(f"## Context\n{context.strip()}")

    criteria_block = "\n".join(f"- {c}" for c in passing_criteria)
    sections.append(f"## Passing Criteria\n{criteria_block}")

    sections.append(f"## Material to Review\n{material.strip()}")

    if verification and verification.strip():
        sections.append(f"## Verification Steps\n{verification.strip()}")

    return "\n\n---\n\n".join(sections)
