"""agent/_reload.py — hot-reload skills from disk.

Rebuilds the tool registry and system prompt after skill files change.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent import DAGI_ROOT
from agent.skills import SkillLoader

if TYPE_CHECKING:
    from agent.loop import AgentLoop


def rebuild_for_reload(loop: AgentLoop) -> tuple[set[str], set[str], list[tuple[str, str]]]:
    """Hot-reload skills from disk, rebuild registry + system prompt.

    Returns (added_names, removed_names, errors) for notification formatting.
    """
    from agent.tools import create_tool_registry

    dagi_root = DAGI_ROOT
    skill_roots = [
        dagi_root / ".dagi" / "skills",
        loop.config.project_path / ".dagi" / "skills",
    ]

    before_names = {s.name for s in loop.skills}
    new_skills, errors = SkillLoader().load_all_with_errors(skill_roots, dagi_root=dagi_root)
    loop.skills = new_skills
    after_names = {s.name for s in loop.skills}

    loop.registry = create_tool_registry(
        cwd=loop.config.project_path,
        allowed_roots=[dagi_root, loop.config.project_path, loop._effective_memory_root],
        skill_roots=skill_roots,
        config=loop.config,
        callbacks=loop.callbacks,
        tracker=loop.tracker,
        memory_root=loop._effective_memory_root,
        bash_tool=loop._injected_bash_tool,
        session_log=loop.log,
        parent_context=loop.parent_context_provider,
        expression_controller=loop.tracker.expression_controller,
    )

    _system = loop._assemble_system_string(dagi_root)
    loop._emit_header(_system, "change")
    loop._sync_messages()

    return after_names - before_names, before_names - after_names, errors
