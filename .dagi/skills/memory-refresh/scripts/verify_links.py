"""Check bidirectional wikilinks and flag broken/orphaned links."""
from __future__ import annotations

import sys
from pathlib import Path

from _common import (
    WIKI_ROOT,
    all_content_files,
    emit_issues,
    extract_wikilinks,
)


def _resolve_wikilink(link: str) -> Path | None:
    """Resolve a wikilink to a file path."""
    candidate = WIKI_ROOT / link
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    if candidate.exists():
        return candidate
    return None


def verify(scope: str | None = None) -> list[dict]:
    issues = []
    files = all_content_files(scope)

    # Build reverse map: target -> set of sources
    reverse_map: dict[str, set[str]] = {}
    forward_map: dict[str, list[str]] = {}

    for path in files:
        rel = str(path.relative_to(WIKI_ROOT))
        links = extract_wikilinks(path)
        forward_map[rel] = links
        for link in links:
            reverse_map.setdefault(link, set()).add(rel)

    # Check each link resolves
    for source, links in forward_map.items():
        for link in links:
            target = _resolve_wikilink(link)
            if target is None:
                issues.append({
                    "file": source,
                    "type": "broken_link",
                    "message": f"Broken wikilink: [[{link}]]",
                    "severity": "error",
                })

    # Check bidirectionality (warning, not error)
    for source, links in forward_map.items():
        for link in links:
            target = _resolve_wikilink(link)
            if target is None:
                continue
            target_rel = str(
                target.relative_to(WIKI_ROOT),
            ).replace("\\", "/")
            source_norm = source.replace("\\", "/")
            # Remove .md for comparison
            source_stem = (
                source_norm[:-3]
                if source_norm.endswith(".md")
                else source_norm
            )
            target_links = forward_map.get(
                str(target.relative_to(WIKI_ROOT)), [],
            )
            has_backlink = any(
                source_stem in tl
                or source_norm in tl
                for tl in target_links
            )
            if not has_backlink:
                issues.append({
                    "file": source,
                    "type": "missing_backlink",
                    "message": (
                        f"[[{link}]] has no backlink to "
                        f"{source}"
                    ),
                    "severity": "warning",
                })
    return issues


if __name__ == "__main__":
    scope = sys.argv[1] if len(sys.argv) > 1 else None
    emit_issues(verify(scope))
