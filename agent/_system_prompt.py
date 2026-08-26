"""agent/_system_prompt.py — system-prompt assembly.

Extracted verbatim from agent/loop.py (and agent/_loop_helpers.py) so the loop
orchestrator stays under the 500-line cap. Only agent/loop.py imports from
this module. `assemble_system_string` is the single source of truth for what
the model sees.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agent.prompts import load_main_system_prompt, load_soul

if TYPE_CHECKING:
    from agent._loop_config import AgentConfig
    from agent.registry import ToolRegistry
    from agent.skills import Skill


class _SafePlaceholder:
    """Sentinel returned by _SafeDict for unknown keys.

    Preserves the original ``{key}`` or ``{key:spec}`` text so
    ``str.format_map`` passes through placeholders it doesn't know about.
    """
    __slots__ = ("_key",)

    def __init__(self, key: str) -> None:
        self._key = key

    def __str__(self) -> str:
        return f"{{{self._key}}}"

    def __format__(self, format_spec: str) -> str:
        if format_spec:
            return f"{{{self._key}:{format_spec}}}"
        return f"{{{self._key}}}"


class _SafeDict(dict):
    """Format-map helper: leaves unknown {key} placeholders intact."""
    def __missing__(self, key: str) -> _SafePlaceholder:
        return _SafePlaceholder(key)


def _format_tools_and_skills(registry: ToolRegistry, skills: list[Skill]) -> str:
    """Generate a unified tools + skills section for the system prompt."""
    lines = ["## Available Tools", ""]
    for name, description in registry.list_tools():
        lines.append(f"- **{name}**: {description}")

    if skills:
        lines += [
            "",
            "## Available Skills",
            "",
            "Skills are detailed guidance documents for specific workflows. "
            "You MUST invoke the relevant `skill` tool BEFORE beginning any task for which "
            "a matching skill exists. Treat skill invocation as a required first step — "
            "never implement a skill-governed workflow without loading it first. "
            "If the user's request matches a skill's description or any of its trigger phrases, "
            "call `skill(name)` immediately as your first action. "
            "Skills may include executable scripts — after loading a skill, use "
            "`run_skill_script(skill_name, script_name)` to run them.",
            "",
        ]
        for s in sorted(skills, key=lambda x: x.name):
            desc = f" — {s.description}" if s.description else ""
            lines.append(f"- **{s.name}**{desc}")
            if s.triggers:
                quoted = ", ".join(f'"{t}"' for t in s.triggers)
                lines.append(f"  Triggers: {quoted}")

    return "\n".join(lines)


def build_preamble(config: AgentConfig, dagi_root: Path) -> str:
    """Benchmark/sandbox preamble + soul + AGENTS.md stack (moved verbatim
    from AgentLoop._build_preamble; `self.config` became `config`)."""
    parts: list[str] = []
    if config.system_prompt_preamble:
        parts.append(config.system_prompt_preamble.strip())
    soul_text = load_soul(dagi_root, config.project_path)
    if soul_text:
        parts.append(soul_text.strip())
    for agents_path in [
        dagi_root / "AGENTS.md",
        config.project_path / "AGENTS.md",
    ]:
        if agents_path.exists():
            text = agents_path.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n\n---\n\n".join(parts)


def assemble_system_string(
    config: AgentConfig,
    registry: ToolRegistry,
    skills: list[Skill],
    effective_memory_root: Path,
    system_prompt_override: str | None,
    dagi_root: Path,
) -> tuple[str, list[dict]]:
    """Single source of truth for system-prompt assembly.

    Moved verbatim from AgentLoop._assemble_system_string: instance state
    became parameters and the mutated self.system_parts / self._system_prefix
    are now the returned tuple. Call sites handle _messages assignment via
    _sync_messages().
    """
    readme_path = (dagi_root / "README.md").resolve()
    prompt_text = (
        config.system_prompt
        if config.system_prompt
        else load_main_system_prompt(dagi_root, config.project_path)
    )
    tools_and_skills = _format_tools_and_skills(registry, skills)
    prompt = prompt_text.format_map(_SafeDict(
        readme_path=readme_path,
        tools_and_skills=tools_and_skills,
        cwd=str(config.project_path.resolve()),
        memory_root=str(effective_memory_root),
        dagi_root=str(dagi_root.resolve()),
    ))

    soul_text = load_soul(dagi_root, config.project_path)
    dagi_agents = dagi_root / "AGENTS.md"
    project_agents = config.project_path / "AGENTS.md"
    system_parts: list[dict] = []
    if soul_text:
        system_parts.append({"label": "SOUL.md", "content": soul_text.strip()})
    if dagi_agents.exists():
        system_parts.append({
            "label": "AGENTS.md (dagi)",
            "content": dagi_agents.read_text(encoding="utf-8").strip(),
        })
    if project_agents.exists():
        system_parts.append({
            "label": "AGENTS.md (project)",
            "content": project_agents.read_text(encoding="utf-8").strip(),
        })
    system_parts.append({"label": "System Prompt", "content": prompt})

    preamble = build_preamble(config, dagi_root)
    sections = [s for s in [preamble, prompt] if s]
    system = "\n\n---\n\n".join(sections)
    system += f"\n\n---\n\nProject root: {config.project_path}"

    if system_prompt_override is not None:
        system = system_prompt_override
    return system, system_parts
