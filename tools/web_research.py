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
        from tools._subagent_runner import run_subagent
        from uuid import uuid4 as _uuid4

        subagent_id = _uuid4().hex[:8]
        handoff_path = self._config.project_path / ".dagi" / "handoffs" / f"web_research_{subagent_id}.md"
        depth = self._tracker._depth if self._tracker else 0

        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "web_research", task, depth)

        result = run_subagent("web_research", task, self._config.project_path, handoff_path, 300)

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, str(result), depth)

        if result["status"] == "ok":
            return Path(result["handoff"]).read_text(encoding="utf-8")
        return f"[web_research error] {result.get('message', result['status'])}"
