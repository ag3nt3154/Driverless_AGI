"""
agent/tools.py — Tool registration.

Imports all tool implementations from the top-level tools/ package and
provides create_tool_registry() for building a project-scoped registry.
"""
from pathlib import Path

from agent.registry import ToolRegistry
from tools.read import ReadTool
from tools.write import WriteTool
from tools.edit import EditTool
from tools.bash import BashTool
from tools.grep import GrepTool
from tools.find import FindTool
from tools.skill import SkillTool

_CORE_TOOL_CLASSES = [ReadTool, WriteTool, EditTool, BashTool, GrepTool, FindTool]
_DAGI_ROOT = Path(__file__).parent.parent


def create_tool_registry(
    cwd: Path = Path("."),
    allowed_roots: list[Path] | None = None,
    skills: list | None = None,
) -> ToolRegistry:
    """Build a fresh ToolRegistry with all tools bound to *cwd*.

    File-touching tools (read, write, edit, grep, find) are sandboxed to
    *allowed_roots* (defaults to [dagi_root, cwd]). BashTool is excluded
    from path sandboxing by design. If *skills* is provided, a SkillTool
    is registered so the agent can load skill documents on demand.
    """
    effective_roots = allowed_roots if allowed_roots is not None else [_DAGI_ROOT, cwd]
    reg = ToolRegistry()
    for cls in _CORE_TOOL_CLASSES:
        if cls is BashTool:
            reg.register(cls(cwd=cwd))
        else:
            reg.register(cls(cwd=cwd, allowed_roots=effective_roots))
    if skills:
        reg.register(SkillTool(skills=skills))
    return reg
