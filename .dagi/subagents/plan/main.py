# .dagi/subagents/plan/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog


class WritePlanTool(BaseTool):
    name = "write_plan"
    description = (
        "Writes a plan file with subtasks, acceptance criteria, and test "
        "paths. Does not execute anything — call run_worker afterwards to "
        "implement."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Description of what needs to be planned.",
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance: constraints, preferred structure, "
                    "or context the planner should know. Optional."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker
        self._session_log = session_log

    def run(self, task: str, custom_instructions: str = "") -> str:
        from tools._handoff_format import dispatch_status_result, format_handoff_result

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("plan")

        result = _subagent_api.run_subagent(
            task=task,
            preset="plan",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
            parent_log=self._session_log,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(str(result.handoff_path), unverified=unverified)
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "escalation": result.escalation,
                "message": result.escalation or "",
            },
            "plan",
            include_escalation=True,
        )
