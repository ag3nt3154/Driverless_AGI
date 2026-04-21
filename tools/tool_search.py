from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
    source: str = ""  # "builtin" | "project" | "" for unknown


_TOOL_SEARCH_SYSTEM_PROMPT = """\
You are a tool-selection specialist. Match the user's capability request to
the best entry in the catalog below.

The catalog includes BOTH built-in tools/skills [builtin] and project-specific
tools/skills [project]. When the user is working on a project task, prefer
entries labeled [project] if they closely match the request. Use [builtin]
entries when no project-specific match exists.

## Catalog

{catalog}

Respond in EXACTLY this format — no preamble:

MATCH: <name>
TYPE: <tool|skill>
DESCRIPTION: <one sentence>
CALL: <run_tool(name="...", args='...') example>

If nothing in the catalog fits the request, respond with:
NO_MATCH: <brief reason>

Do not invent tools. Do not suggest basic tools (read, write, edit, grep, find, bash).\
"""


def _render_catalog(catalog: list[CatalogEntry]) -> str:
    lines: list[str] = []
    for e in catalog:
        source_tag = f" [{e.source}]" if e.source else ""
        lines.append(f"**{e.name}** ({e.kind}){source_tag}")
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
                    "Natural language description of the capability you need, "
                    "including your best guess at the kind of tool required. "
                    "Always start with a short tool-type hypothesis, then the task. "
                    "Examples: "
                    "'web-search or web-fetch tool needed — find recent papers on RAG'; "
                    "'file-explorer tool needed — list all Python files under src/'; "
                    "'skill or guidance tool needed — load test-writing conventions'."
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        static_tool_entries: list[CatalogEntry],
        dagi_root: Path,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
    ) -> None:
        self._static_tool_entries = static_tool_entries
        self._dagi_root = dagi_root
        self._config = config
        self._callbacks = callbacks
        self._tracker = tracker

    def _build_catalog(self) -> list[CatalogEntry]:
        """Rebuild catalog on every call: static tool entries + freshly scanned skills."""
        from agent.skills import SkillLoader

        catalog = list(self._static_tool_entries)
        skill_roots = [
            self._dagi_root / ".dagi" / "skills",
            self._config.project_path / ".dagi" / "skills",
        ]
        for s in SkillLoader().load_all(skill_roots, dagi_root=self._dagi_root):
            catalog.append(CatalogEntry(
                name=s.name,
                kind="skill",
                description=s.description or "(no description)",
                params_summary="(none — skill loads a guidance document)",
                example_call=f'run_tool(name="skill", args=\'{{"skill": "{s.name}"}}\')',
                source=s.source,
            ))
        return catalog

    def run(self, query: str) -> str:
        from agent.sub_agent import SubAgentConfig, SubAgentRunner

        catalog_text = _render_catalog(self._build_catalog())
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
            return f"[tool_search] {result.strip()}"
        return result
