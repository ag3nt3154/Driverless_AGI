"""Validate frontmatter fields per category schema."""
from __future__ import annotations

import sys
from pathlib import Path

from _common import (
    CATEGORY_FIELDS,
    SHARED_FIELDS,
    VALID_FREQUENCY,
    VALID_STATUS_PROJECT,
    VALID_STATUS_TODO,
    WIKI_ROOT,
    all_content_files,
    detect_category,
    emit_issues,
    is_overview_file,
    parse_frontmatter,
)


def lint(scope: str | None = None) -> list[dict]:
    issues = []
    for path in all_content_files(scope):
        cat = detect_category(path)
        if not cat:
            continue
        fm = parse_frontmatter(path)
        rel = str(path.relative_to(WIKI_ROOT))
        if fm is None:
            issues.append({
                "file": rel,
                "type": "missing_frontmatter",
                "message": "No valid YAML frontmatter found",
                "severity": "error",
            })
            continue

        # Check shared fields
        for field in SHARED_FIELDS:
            if field not in fm:
                issues.append({
                    "file": rel,
                    "type": "missing_field",
                    "message": f"Missing shared field: {field}",
                    "severity": "warning",
                })

        # Check category-specific fields
        extra = CATEGORY_FIELDS.get(cat, set())
        if cat == "projects" and is_overview_file(path):
            for field in extra:
                if field not in fm:
                    issues.append({
                        "file": rel,
                        "type": "missing_field",
                        "message": (
                            f"Missing project field: {field}"
                        ),
                        "severity": "warning",
                    })
        elif cat == "projects":
            pass  # subtasks only need shared fields
        else:
            for field in extra:
                if field not in fm:
                    issues.append({
                        "file": rel,
                        "type": "missing_field",
                        "message": (
                            f"Missing {cat} field: {field}"
                        ),
                        "severity": "warning",
                    })

        # Validate enum values
        if cat == "projects" and "status" in fm:
            if fm["status"] not in VALID_STATUS_PROJECT:
                issues.append({
                    "file": rel,
                    "type": "invalid_value",
                    "message": (
                        f"Invalid project status: "
                        f"{fm['status']}"
                    ),
                    "severity": "error",
                })
        if cat == "todos" and "status" in fm:
            if fm["status"] not in VALID_STATUS_TODO:
                issues.append({
                    "file": rel,
                    "type": "invalid_value",
                    "message": (
                        f"Invalid todo status: {fm['status']}"
                    ),
                    "severity": "error",
                })
        if cat == "todos" and "frequency" in fm:
            if fm["frequency"] not in VALID_FREQUENCY:
                issues.append({
                    "file": rel,
                    "type": "invalid_value",
                    "message": (
                        f"Invalid frequency: {fm['frequency']}"
                    ),
                    "severity": "error",
                })

        # Check for legacy fields (migration candidates)
        legacy = {"date_added", "type", "topic", "source"}
        for field in legacy:
            if field in fm:
                issues.append({
                    "file": rel,
                    "type": "legacy_field",
                    "message": (
                        f"Legacy field present: {field}"
                    ),
                    "severity": "warning",
                })
    return issues


if __name__ == "__main__":
    scope = sys.argv[1] if len(sys.argv) > 1 else None
    emit_issues(lint(scope))
