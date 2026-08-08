"""Verify .index.md tables match actual folder contents."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from _common import WIKI_ROOT, emit_issues, is_index_file


def _parse_index_links(index_path: Path) -> set[str]:
    """Extract filenames referenced in index table rows."""
    try:
        text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    links = set()
    for m in re.finditer(r"\[.+?\]\((.+?)\)", text):
        links.add(m.group(1))
    return links


def _actual_children(folder: Path) -> set[str]:
    """List .md files in folder (non-recursive, excluding .index.md)."""
    if not folder.is_dir():
        return set()
    return {
        f.name for f in folder.iterdir()
        if f.suffix == ".md" and not is_index_file(f) and f.name != "log.md"
    }


def check(scope: str | None = None) -> list[dict]:
    issues = []
    root = WIKI_ROOT / scope if scope else WIKI_ROOT

    for index_path in root.rglob(".index.md"):
        folder = index_path.parent
        rel_index = str(
            index_path.relative_to(WIKI_ROOT),
        )
        indexed = _parse_index_links(index_path)
        actual = _actual_children(folder)

        # Check for sub-folder indexes too
        sub_indexed = set()
        sub_actual = set()
        for item in indexed:
            if item.endswith("/.index.md"):
                sub_indexed.add(
                    item.replace("/.index.md", ""),
                )
        for d in folder.iterdir():
            if d.is_dir() and (d / ".index.md").exists():
                sub_actual.add(d.name)

        # Files in folder but not in index
        for f in actual:
            if f not in indexed:
                issues.append({
                    "file": rel_index,
                    "type": "missing_from_index",
                    "message": f"File {f} exists but not in index",
                    "severity": "warning",
                })

        # Files in index but not in folder
        for f in indexed:
            if (
                f not in actual
                and not f.endswith("/.index.md")
                and not (folder / f).is_dir()
            ):
                issues.append({
                    "file": rel_index,
                    "type": "stale_index_entry",
                    "message": (
                        f"Index references {f} "
                        f"but file does not exist"
                    ),
                    "severity": "error",
                })

        # Sub-folders with .index.md not listed
        for d in sub_actual - sub_indexed:
            issues.append({
                "file": rel_index,
                "type": "missing_from_index",
                "message": (
                    f"Subfolder {d}/ exists "
                    f"but not in index"
                ),
                "severity": "warning",
            })
    return issues


if __name__ == "__main__":
    scope = sys.argv[1] if len(sys.argv) > 1 else None
    emit_issues(check(scope))
