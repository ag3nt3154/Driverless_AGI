# .dagi/subagents/memory-query/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog


class MemoryQueryTool(BaseTool):
    name = "memory_query"
    description = (
        "Query the memory wiki to retrieve stored knowledge. "
        "Returns a synthesised answer with citations."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The question or topic to look up."
                ),
            },
            "scope": {
                "type": "string",
                "description": (
                    "Narrow search to a subtree, e.g. 'todos', "
                    "'projects/dagi', "
                    "'knowledge/trading-strategies'. Optional."
                ),
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance. Optional."
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

    def run(
        self,
        task: str,
        scope: str = "",
        custom_instructions: str = "",
    ) -> str:
        from tools._handoff_format import (
            dispatch_status_result,
            format_handoff_result,
        )

        # Build enriched task with scope
        enriched_task = task
        if scope:
            enriched_task += f"\nScope: {scope}"

        on_event = None
        if (
            self._callbacks
            and self._callbacks.on_subagent_event_factory
        ):
            on_event = (
                self._callbacks.on_subagent_event_factory(
                    "memory-query",
                )
            )

        result = _subagent_api.run_subagent(
            task=enriched_task,
            preset="memory-query",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
            parent_log=self._session_log,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(
                str(result.handoff_path),
                unverified=unverified,
            )
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
