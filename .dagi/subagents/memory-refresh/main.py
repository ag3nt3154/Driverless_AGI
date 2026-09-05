# .dagi/subagents/memory-refresh/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
    from agent.parent_context import ParentContextProvider


class MemoryRefreshTool(BaseTool):
    name = "memory_refresh"
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
            parent_log=self._session_log,
            parent_context=self._parent_context,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            text = format_handoff_result(str(result.handoff_path), unverified=unverified)
            if result.exit_code not in (None, 0):
                text += f"\n\n⚠️ Process exited code {result.exit_code} despite writing handoff."
            return text
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "message": result.message,
                "exit_code": result.exit_code,
                "output_tail": result.output_tail,
            },
            "memory-refresh",
        )
