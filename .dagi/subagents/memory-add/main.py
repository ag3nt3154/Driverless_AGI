# .dagi/subagents/memory-add/main.py
from __future__ import annotations

from typing import TYPE_CHECKING

import tools.subagent_api as _subagent_api
from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog


class MemoryAddTool(BaseTool):
    name = "memory_add"
    description = (
        "File a new entry into the memory wiki. You must classify the "
        "content and provide a category. Use to persist decisions, "
        "knowledge, events, or todos."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The content to file into the memory wiki.",
            },
            "category": {
                "type": "string",
                "enum": ["projects", "todos", "knowledge", "events"],
                "description": "Which wiki category to file under.",
            },
            "deadline": {
                "type": "string",
                "description": (
                    "For todos: due date in YYYY-MM-DD format. Optional."
                ),
            },
            "frequency": {
                "type": "string",
                "enum": [
                    "one-off", "daily", "weekly", "monthly",
                ],
                "description": (
                    "For todos: recurrence. Default: one-off. Optional."
                ),
            },
            "date": {
                "type": "string",
                "description": (
                    "For events: when it occurred (YYYY-MM-DD). "
                    "Default: today. Optional."
                ),
            },
            "custom_instructions": {
                "type": "string",
                "description": (
                    "Additional guidance for the subagent. Optional."
                ),
            },
        },
        "required": ["task", "category"],
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
        category: str,
        deadline: str = "",
        frequency: str = "",
        date: str = "",
        custom_instructions: str = "",
    ) -> str:
        from tools._handoff_format import (
            dispatch_status_result,
            format_handoff_result,
        )

        # Build enriched task with category metadata
        parts = [task, f"\nCategory: {category}"]
        if deadline:
            parts.append(f"Deadline: {deadline}")
        if frequency:
            parts.append(f"Frequency: {frequency}")
        if date:
            parts.append(f"Date: {date}")
        enriched_task = "\n".join(parts)

        on_event = None
        if (
            self._callbacks
            and self._callbacks.on_subagent_event_factory
        ):
            on_event = (
                self._callbacks.on_subagent_event_factory(
                    "memory-add",
                )
            )

        result = _subagent_api.run_subagent(
            task=enriched_task,
            preset="memory-add",
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
            "memory-add",
            include_escalation=True,
        )
