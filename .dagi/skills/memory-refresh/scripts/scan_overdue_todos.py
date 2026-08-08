"""Find todos with passed deadlines."""
from __future__ import annotations

import sys
from datetime import date

from _common import (
    WIKI_ROOT,
    all_content_files,
    emit_issues,
    parse_frontmatter,
)


def scan(scope: str | None = None) -> list[dict]:
    issues = []
    today = date.today()
    effective_scope = scope or "todos"

    for path in all_content_files(effective_scope):
        if not path.name.startswith("todo_"):
            continue
        fm = parse_frontmatter(path)
        if fm is None:
            continue
        rel = str(path.relative_to(WIKI_ROOT))
        status = fm.get("status", "pending")
        if status in ("completed", "dropped"):
            continue
        deadline = fm.get("deadline")
        if not deadline or deadline == "null":
            continue
        try:
            dl = date.fromisoformat(str(deadline))
        except (ValueError, TypeError):
            issues.append({
                "file": rel,
                "type": "invalid_deadline",
                "message": (
                    f"Cannot parse deadline: {deadline}"
                ),
                "severity": "warning",
            })
            continue
        if dl < today:
            days = (today - dl).days
            issues.append({
                "file": rel,
                "type": "overdue_todo",
                "message": (
                    f"Overdue by {days} day(s): "
                    f"deadline was {deadline}, "
                    f"status is {status}"
                ),
                "severity": "warning",
            })
    return issues


if __name__ == "__main__":
    scope = sys.argv[1] if len(sys.argv) > 1 else None
    emit_issues(scan(scope))
