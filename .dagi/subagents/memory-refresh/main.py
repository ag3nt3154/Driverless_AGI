# .dagi/subagents/memory-refresh/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


class SpawnMemoryRefreshSubagentTool(BaseTool):
    name = "spawn_memory-refresh_subagent"
    description = (
        "Maintain and repair the memory wiki. Runs lint scripts, "
        "presents issues for user approval, and executes fixes. "
        "Handles: todo updates, frontmatter normalisation, "
        "broken links, index drift."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": (
                    "Narrow to a category, project, or topic. "
                    "E.g. 'todos', 'projects/dagi'. Optional."
                ),
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance. Optional."
                ),
            },
        },
        "required": [],
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

    def run(
        self,
        scope: str = "",
        custom_instructions: str = "",
    ) -> str:
        from tools._handoff_format import (
            dispatch_status_result,
            format_handoff_result,
        )

        task = "Run memory-refresh protocol."
        if scope:
            task += f"\nScope: {scope}"

        on_event = None
        if (
            self._callbacks
            and self._callbacks.on_subagent_event_factory
        ):
            on_event = (
                self._callbacks.on_subagent_event_factory(
                    "memory-refresh",
                )
            )

        result = _subagent_api.run_subagent(
            task=task,
            preset="memory-refresh",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
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
            "memory-refresh",
            include_escalation=True,
        )
