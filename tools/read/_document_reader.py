"""tools/_document_reader.py — Orchestrate document-reader subagent for long documents."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

from tools._subagent_runner import run_subagent

_SUMMARY_SUBDIR = "document_summary"
_HASH_CACHE_DIR = ".dagi/hash_cache"


def _summary_cache_path(content_hash: str, project_path: Path) -> Path:
    return (
        project_path / _HASH_CACHE_DIR / _SUMMARY_SUBDIR
        / f"{content_hash}_summary.md"
    )


def summarize_document(
    full_text: str,
    source_path: Path,
    filename: str,
    project_path: Path,
    on_event: Callable[[str], None] | None = None,
    timeout: float = 1800.0,
) -> str | None:
    """Spawn a document-reader subagent to produce a sectioned summary.

    Returns the summary string on success, or None on failure (caller
    should fall back to truncation).
    """
    content_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    summary_path = _summary_cache_path(content_hash, project_path)

    # Cache hit — return immediately
    if summary_path.exists():
        return summary_path.read_text(encoding="utf-8")

    # Cache miss — save full text, spawn subagent
    full_text_dir = project_path / _HASH_CACHE_DIR / "tool_output"
    full_text_dir.mkdir(parents=True, exist_ok=True)
    full_text_path = full_text_dir / f"{content_hash}.txt"
    if not full_text_path.exists():
        full_text_path.write_text(full_text, encoding="utf-8", newline="\n")

    summary_path.parent.mkdir(parents=True, exist_ok=True)

    task = (
        f"Read the document at: {full_text_path}\n"
        f"Filename: {filename}\n"
        f"Write the sectioned summary digest to: {summary_path}\n"
        f"Source path (for the header): {source_path}\n"
    )

    handoff_dir = project_path / ".dagi" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoff_dir / f"document_reader_{content_hash[:12]}.md"

    result = run_subagent(
        subagent_type="document-reader",
        task=task,
        project_path=project_path,
        handoff_path=handoff_path,
        timeout=timeout,
        on_event=on_event,
    )

    if result["status"] == "ok" and summary_path.exists():
        return summary_path.read_text(encoding="utf-8")

    return None
