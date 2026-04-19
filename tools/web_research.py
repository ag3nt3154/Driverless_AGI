from pathlib import Path

from agent.base_tool import BaseTool

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

    def __init__(self, config, callbacks=None, cwd: Path = Path("."), allowed_roots=None):
        self._config = config
        self._callbacks = callbacks

    def run(self, task: str) -> str:
        try:
            from agent.sub_agent import SubAgentConfig, SubAgentRunner
            from tools.web_fetch import WebFetchTool
            from tools.web_search import WebSearchTool

            runner = SubAgentRunner(
                config=self._config,
                tools=[WebSearchTool(), WebFetchTool()],
                system_prompt=_SYSTEM_PROMPT,
                callbacks=self._callbacks,
                sub_cfg=SubAgentConfig(max_iterations=8, prefix="[web-research]"),
            )
            return runner.run(task)
        except Exception as e:
            return f"[web_research error] {e}"
