"""
agent/tools.py — Tool registration.

Imports all tool implementations from the top-level tools/ package and
provides create_tool_registry() for building a project-scoped registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent.registry import ToolRegistry
from tools.bash import BashTool
from tools.edit import EditTool
from tools.find import FindTool
from tools.grep import GrepTool
from tools.read import ReadTool
from tools.skill import SkillTool
from tools.write import WriteTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker

_DAGI_ROOT = Path(__file__).parent.parent


def create_tool_registry(
    cwd: Path = Path("."),
    allowed_roots: list[Path] | None = None,
    skills: list | None = None,
    plan_mode: bool = False,
    plan_file: Path | None = None,
    config: "AgentConfig | None" = None,
    callbacks: "AgentCallbacks | None" = None,
    tracker: "SessionTracker | None" = None,
) -> ToolRegistry:
    """Build a fresh ToolRegistry with all tools bound to *cwd*.

    File-touching tools (read, write, edit, grep, find) are sandboxed to
    *allowed_roots* (defaults to [dagi_root, cwd]). BashTool is excluded
    from path sandboxing by design. If *skills* is provided, a SkillTool
    is registered so the agent can load skill documents on demand.

    When *plan_mode* is True, BashTool is omitted and WriteTool/EditTool are
    registered with *plan_file* as their sole allowed path so the agent can
    only write to the plan document.

    When *config* is provided, web research and file exploration are handled
    by delegate tools that spin up sub-agents. Without *config* (e.g. in
    tests), the raw web_search and web_fetch tools are registered instead.
    """
    effective_roots = allowed_roots if allowed_roots is not None else [_DAGI_ROOT, cwd]
    reg = ToolRegistry()
    reg.register(ReadTool(cwd=cwd, allowed_roots=effective_roots))
    reg.register(GrepTool(cwd=cwd, allowed_roots=effective_roots))
    reg.register(FindTool(cwd=cwd, allowed_roots=effective_roots))
    if plan_mode:
        if plan_file:
            reg.register(WriteTool(cwd=cwd, allowed_roots=[plan_file]))
            reg.register(EditTool(cwd=cwd, allowed_roots=[plan_file]))
        # BashTool always omitted in plan mode
    else:
        reg.register(WriteTool(cwd=cwd, allowed_roots=effective_roots))
        reg.register(EditTool(cwd=cwd, allowed_roots=effective_roots))
        reg.register(BashTool(cwd=cwd))
        if config is not None:
            from tools.explore_files import ExploreFilesTool
            from tools.web_research import WebResearchTool
            reg.register(WebResearchTool(config=config, callbacks=callbacks, cwd=cwd, allowed_roots=effective_roots, tracker=tracker))
            reg.register(ExploreFilesTool(config=config, callbacks=callbacks, cwd=cwd, allowed_roots=effective_roots, tracker=tracker))
        else:
            # Fallback for callers that do not supply config (e.g. tests)
            from tools.web_fetch import WebFetchTool
            from tools.web_search import WebSearchTool
            reg.register(WebSearchTool())
            reg.register(WebFetchTool())
    if skills:
        reg.register(SkillTool(skills=skills))
    return reg
