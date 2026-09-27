"""agent/_loop_helpers.py — module-level helpers for the agent loop.

Extracted from agent/loop.py so the loop orchestrator stays under the
500-line cap. Imported by agent/loop.py; agent/_init_templates.py also uses
`project_slug`.
"""
from __future__ import annotations

import re
from pathlib import Path
from agent.prompts import load_prompt


def project_slug(project_path: Path) -> str:
    """Kebab-case project folder name, matching wiki/projects/<slug>/."""
    slug = re.sub(r"[^a-z0-9]+", "-", project_path.name.lower()).strip("-")
    return slug or "project"


def _build_memory_context(memory_root: Path, project_path: Path) -> str | None:
    """Short, static per-project pointer to the central memory wiki.

    Only the location is injected — the model searches with the memory-query
    skill (grep/read) rather than receiving wiki content every turn.
    """
    wiki_root = memory_root / "wiki"
    if not wiki_root.exists():
        return None
    return (
        "[MEMORY]\n"
        f"Memory wiki: {wiki_root}\n"
        f"This project: projects/{project_slug(project_path)}/  — search with memory-query "
        "at task start and before debugging; file with memory-add.\n"
        "[END MEMORY]"
    )


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


