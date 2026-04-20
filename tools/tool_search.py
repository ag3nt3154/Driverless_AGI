from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker


@dataclass
class CatalogEntry:
    name: str
    kind: Literal["tool", "skill"]
    description: str
    params_summary: str
    example_call: str


_TOOL_SEARCH_SYSTEM_PROMPT = """\
You are a tool-selection specialist. Match the user's capability request to
the best entry in the catalog below.

## Catalog

{catalog}

Respond in EXACTLY this format — no preamble:

MATCH: <name>
TYPE: <tool|skill>
DESCRIPTION: <one sentence>
CALL: <run_tool(name="...", args='...') example>

If nothing fits, respond with:
NO_MATCH: <brief reason>

Do not invent tools. Do not suggest basic tools (read, write, edit, grep, find, bash).\
"""


def _render_catalog(catalog: list[CatalogEntry]) -> str:
    lines: list[str] = []
    for e in catalog:
        lines.append(f"**{e.name}** ({e.kind})")
        lines.append(f"  {e.description}")
        lines.append(f"  Params: {e.params_summary}")
        lines.append(f"  Example: {e.example_call}")
        lines.append("")
    return "\n".join(lines)


class ToolSearchTool(BaseTool):
    name = "tool_search"
    description = (
        "Discover the right tool or skill for a task. "
        "Returns the best match with its name, type, description, and an example call. "
        "Use this before run_tool whenever you need web research, file exploration, "
        "or any skill-based workflow not listed in the available tools above."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Natural language description of the capability you need. "
                    "Examples: 'search the web for X', 'explore files in the repo', "
                    "'load guidance for writing tests'."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        catalog: list[CatalogEntry],
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
    ) -> None:
        self._catalog = catalog
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker

    def run(self, query: str) -> str:
        from agent.sub_agent import SubAgentConfig, SubAgentRunner

        catalog_text = _render_catalog(self._catalog)
        system_prompt = _TOOL_SEARCH_SYSTEM_PROMPT.format(catalog=catalog_text)
        subagent_id = uuid4().hex
        depth = self._tracker._depth if self._tracker else 0

        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "tool_search", query, depth)

        runner = SubAgentRunner(
            config=self._config,
            tools=[],
            system_prompt=system_prompt,
            callbacks=self._callbacks,
            sub_cfg=SubAgentConfig(prefix="[tool-search]"),
            parent_tracker=self._tracker,
            subagent_id=subagent_id,
        )
        result = runner.run(query)

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, result, depth)

        if result.strip().startswith("NO_MATCH:"):
            return (
                f"[tool_search] {result.strip()}\n\n"
                "Proceed with basic tools (read/grep/find/bash/write/edit) "
                "or inform the user this capability is unavailable."
            )
        return result
