from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.session import SessionTracker


class WebResearchTool(BaseTool):
    name = "web_research"
    description = (
        "Delegate a web research task to a sub-agent that has web_search and web_fetch. "
        "Returns a compiled Markdown report with sources. "
        "Use for any task involving current information, documentation, or web-sourced knowledge. "
        "Do NOT call web_search or web_fetch directly from the main agent."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear research question. The sub-agent searches and returns a Markdown report.",
            },
        },
        "required": ["task"],
    }

    def __init__(self, config, callbacks=None, cwd: Path = Path("."), allowed_roots=None, tracker: "SessionTracker | None" = None):
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker

    def run(self, task: str) -> str:
        try:
            from tools._terminal_subagent import spawn_terminal_subagent

            subagent_id = uuid4().hex[:8]
            depth = self._tracker._depth if self._tracker else 0

            if self._tracker:
                self._tracker.record_subagent_start(subagent_id, "web_research", task, depth)

            result = spawn_terminal_subagent(
                subagent_type="web_research",
                task=task,
                project_path=self._config.project_path,
                timeout=300,
            )

            if self._tracker:
                self._tracker.record_subagent_end(subagent_id, result, depth)

            return result
        except Exception as e:
            return f"[web_research error] {e}"
