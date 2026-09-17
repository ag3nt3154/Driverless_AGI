"""agent/_loop_helpers.py — module-level helpers for the agent loop.

Extracted from agent/loop.py so the loop orchestrator stays under the
500-line cap. Only agent/loop.py imports from this module.
"""
from __future__ import annotations

from pathlib import Path
from agent.prompts import load_prompt


def _build_wiki_index_context(memory_root: Path) -> str | None:
    """Point the model at the wiki root path instead of inlining its contents.

    Previously this read and concatenated every section .index.md file into
    the context on every turn — expensive and stale-prone as the wiki grows.
    The model has wiki-query/read tools; it only needs to know where to look.
    """
    wiki_root = memory_root / "wiki"
    if not wiki_root.exists():
        return None
    return f"[WIKI]\nProject wiki root: {wiki_root}\n[END WIKI]"


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


