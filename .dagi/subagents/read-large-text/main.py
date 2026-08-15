# .dagi/subagents/read-large-text/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


class ReadLargeTextTool(BaseTool):
    name = "read_large_text"
    description = (
        "Read and digest a large text file. Returns a sectioned summary "
        "with key excerpts, line ranges, and token estimates. Use when a "
        "file is too long to fit in context or requires structured "
        "summarization. Also called automatically by read when the "
        "file exceeds the default 2000-line window."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "The file path and what to extract or summarize from it."
                ),
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance: sections to focus on, output format "
                    "preferences, or extra constraints. Optional."
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
            on_event = self._callbacks.on_subagent_event_factory("read-large-text")

        result = _subagent_api.run_subagent(
            task=task,
            preset="read-large-text",
            custom_instructions=custom_instructions,
            project_path=self._config.project_path,
            on_event=on_event,
        )

        if result.is_ok:
            unverified = result.status == "ok_unverified"
            return format_handoff_result(
                str(result.handoff_path), unverified=unverified
            )
        return dispatch_status_result(
            {
                "status": result.status,
                "pid": result.pid,
                "escalation": result.escalation,
                "message": result.escalation or "",
            },
            "read-large-text",
            include_escalation=True,
        )
