# .dagi/subagents/explore_files/main.py
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog


class ExploreFilesTool(BaseTool):
    name = "explore_files"
    description = (
        "Explore the codebase with read, grep, find, and bash. Use for "
        "open-ended discovery: mapping a module, finding all usages of a "
        "symbol, understanding an unfamiliar subsystem."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The exploration query or question to answer.",
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
            on_event = self._callbacks.on_subagent_event_factory("explore_files")

        result = _subagent_api.run_subagent(
            task=task,
            preset="explore_files",
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
            "explore_files",
            include_escalation=True,
        )
