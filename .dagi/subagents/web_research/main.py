# .dagi/subagents/web_research/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
    from agent.parent_context import ParentContextProvider


class WebResearchTool(BaseTool):
    name = "web_research"
    description = (
        "Research a topic using web search and web fetch. Use for questions "
        "that require current information, documentation lookup, or finding "
        "external resources."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The research question or topic to investigate.",
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
        parent_context: "ParentContextProvider | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker
        self._session_log = session_log
        self._parent_context = parent_context

    def run(self, task: str, custom_instructions: str = "") -> str:
        from tools._handoff_format import dispatch_status_result, format_handoff_result

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("web_research")

        result = _subagent_api.run_subagent(
            task=task,
            preset="web_research",
            custom_instructions=custom_instructions,
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
                "message": "",
            },
            "web_research",
        )
