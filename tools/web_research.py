from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.session import SessionTracker

_SYSTEM_PROMPT = """\
You are a focused web research agent. Answer the research question using web_search and web_fetch only.

Guidelines:
- Issue 1-3 targeted searches.
- Fetch the most relevant URLs (limit to 3 fetches).
- Synthesise findings into a concise Markdown report.
- End with a ## Sources section listing every URL used.
- Do NOT speculate beyond what the sources say.
- Output plain Markdown only — no preamble, no meta-commentary.\
"""


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
            from agent.sub_agent import SubAgentConfig, SubAgentRunner
            from tools.web_fetch import WebFetchTool
            from tools.web_search import WebSearchTool

            subagent_id = uuid4().hex
            depth = self._tracker._depth if self._tracker else 0

            if self._tracker:
                self._tracker.record_subagent_start(subagent_id, "web_research", task, depth)

            runner = SubAgentRunner(
                config=self._config,
                tools=[WebSearchTool(), WebFetchTool()],
                system_prompt=_SYSTEM_PROMPT,
                callbacks=self._callbacks,
                sub_cfg=SubAgentConfig(max_iterations=8, prefix="[web-research]"),
                parent_tracker=self._tracker,
                subagent_id=subagent_id,
            )
            result = runner.run(task)

            if self._tracker:
                self._tracker.record_subagent_end(subagent_id, result, depth)

            return result
        except Exception as e:
            return f"[web_research error] {e}"
