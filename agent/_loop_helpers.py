"""agent/_loop_helpers.py — module-level helpers for the agent loop.

Extracted verbatim from agent/loop.py so the loop orchestrator stays under the
500-line cap. Only agent/loop.py imports from this module; external importers
keep using `from agent.loop import AWAIT_USER_FLAG, ...` (re-exported there).
"""
from __future__ import annotations

from pathlib import Path
from agent.prompts import load_prompt

TASK_END_FLAG = "<<TASK_END>>"           # legacy alias — still recognised
AWAIT_USER_FLAG = "<<END_OF_RESPONSE>>"
WRITE_HANDOFF_SENTINEL = "<<HANDOFF_WRITTEN>>"

_LOOP_SENTINELS = (AWAIT_USER_FLAG, TASK_END_FLAG)


def _escape_sentinels(text: str) -> str:
    """Break loop-control sentinels so they cannot leak from tool results into the
    LLM's message history and cause premature termination on the next turn.

    Replaces '<<' with '< <' in each sentinel — visually similar but won't match
    the substring checks in AgentLoop.run().
    """
    for sentinel in _LOOP_SENTINELS:
        text = text.replace(sentinel, sentinel.replace("<<", "< <"))
    return text


def _is_plan_empty(path: Path) -> bool:
    """Return True if the plan file has no meaningful content beyond scaffold boilerplate."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    meaningful = [
        line for line in text.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and line.strip() not in ("- [ ]", "- [ ] ", "- [x]")
    ]
    return len(meaningful) == 0


def _build_wiki_index_context(memory_root: Path) -> str | None:
    """Read wiki root and section .index.md files; return a formatted context block."""
    wiki_root = memory_root / "wiki"
    root_index = wiki_root / ".index.md"
    if not root_index.exists():
        return None
    parts = [root_index.read_text(encoding="utf-8")]
    for section in ("projects", "knowledge"):
        section_index = wiki_root / section / ".index.md"
        if section_index.exists():
            parts.append(section_index.read_text(encoding="utf-8"))
    return "[WIKI INDEX]\n" + "\n\n---\n\n".join(parts) + "\n[END WIKI INDEX]"


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


def _format_reload_notification(
    total: int,
    added: set[str],
    removed: set[str],
    errors: list[tuple[str, str]],
) -> str:
    lines = [f"[System: Skills reloaded. {total} skill(s) loaded."]
    if added:
        lines.append(f"  New: {', '.join(sorted(added))}")
    if removed:
        lines.append(f"  Removed: {', '.join(sorted(removed))}")
    if errors:
        for path, reason in errors:
            lines.append(f"  Error: {path} — {reason}")
    if not added and not removed and not errors:
        lines.append("  No changes detected.")
    lines.append("]")
    return "\n".join(lines)


CONTINUE_PROMPT = load_prompt("main/continue.md")


def _extract_reasoning(message) -> str:
    """Get reasoning text from the response message, trying SDK attr then model_extra."""
    text = getattr(message, "reasoning_content", None) or ""
    if not text:
        extras = getattr(message, "model_extra", None) or {}
        text = extras.get("reasoning") or extras.get("reasoning_content") or ""
    return text or ""


def _extract_reasoning(message) -> str:
    """Get reasoning text from the response message, trying SDK attr then model_extra."""
    text = getattr(message, "reasoning_content", None) or ""
    if not text:
        extras = getattr(message, "model_extra", None) or {}
        text = extras.get("reasoning") or extras.get("reasoning_content") or ""
    return text or ""


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
