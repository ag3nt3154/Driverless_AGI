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
            "Interpret follow-ups and approvals in the current workflow before selecting a skill. "
            "Load matching skill guidance before performing its work; reloading instructions "
            "does not restart a stage or erase prior approval. "
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


def prompt_sections(config: AgentConfig, dagi_root: Path) -> list[tuple[str, str]]:
    """Ordered (label, text) sections making up the persona/context layer.

    Single source of truth: `assemble_system_string` derives both the model-facing
    string and the `system_parts` metadata from this list, so the two cannot disagree.

    A source file is emitted at most once, compared by resolved path. `dagi_root` and
    `config.project_path` are the same directory when dagi runs inside its own repo,
    which used to inject AGENTS.md twice into every prompt and every request header.
    """
    sections: list[tuple[str, str]] = []
    if config.system_prompt_preamble:
        sections.append(("Preamble", config.system_prompt_preamble.strip()))
    soul_text = load_soul(dagi_root, config.project_path)
    if soul_text:
        sections.append(("SOUL.md", soul_text.strip()))

    seen: set[Path] = set()
    for label, path in (
        ("AGENTS.md (dagi)", dagi_root / "AGENTS.md"),
        ("AGENTS.md (project)", config.project_path / "AGENTS.md"),
    ):
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            seen.add(resolved)
            sections.append((label, text))
    return sections


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

    sections = prompt_sections(config, dagi_root)
    system_parts: list[dict] = [
        {"label": label, "content": text} for label, text in sections
    ]
    system_parts.append({"label": "System Prompt", "content": prompt})

    texts = [text for _, text in sections]
    if prompt:
        texts.append(prompt)
    system = "\n\n---\n\n".join(texts)
    system += f"\n\n---\n\nProject root: {config.project_path}"

    if system_prompt_override is not None:
        system = system_prompt_override
    return system, system_parts
