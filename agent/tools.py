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


def create_tool_registry(cwd: Path = Path("."), skills: list | None = None) -> ToolRegistry:
    """Build a fresh ToolRegistry with all tools bound to *cwd*.

    If *skills* is provided, a SkillTool is registered so the agent can
    load skill documents on demand.
    """
    reg = ToolRegistry()
    for cls in _CORE_TOOL_CLASSES:
        reg.register(cls(cwd=cwd))
    if skills:
        reg.register(SkillTool(skills=skills))
    return reg
