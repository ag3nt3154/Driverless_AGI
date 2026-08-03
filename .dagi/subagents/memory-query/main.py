# .dagi/subagents/memory-query/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


class SpawnMemoryQuerySubagentTool(BaseTool):
    name = "spawn_memory-query_subagent"
    description = (
        "Query the memory wiki to retrieve stored knowledge. Use to look up "
        "prior decisions, design notes, known issues, or any information "
        "previously filed in the wiki."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The question or topic to look up in the memory wiki.",
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance: traps to avoid, prior failed "
                    "attempt context, or extra constraints. Optional."
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
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker

    def run(self, task: str, custom_instructions: str = "") -> str:
        from tools._handoff_format import dispatch_status_result, format_handoff_result

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("memory-query")

        result = _subagent_api.run_subagent(
            task=task,
            preset="memory-query",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
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
            "memory-query",
            include_escalation=True,
        )
