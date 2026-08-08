"""
migrate_wiki.py — Wiki structural migration script for the unified memory system.

Migrates the monolithic wiki/user-todo.md into individual todo files under
wiki/todos/, creates wiki/events/ with an empty index, and updates wiki/.index.md
to list all four sections: projects, todos, knowledge, events.

Usage:
    conda run -n dagi python .dagi/scripts/migrate_wiki.py
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import NamedTuple

WIKI_ROOT = Path(r"G:\My Drive\black_grimoire\dagi-memory\wiki")
TODAY = "2026-08-08"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class TodoEntry(NamedTuple):
    number: str          # "001"
    title: str           # Short heading text (without [TODO-NNN])
    raw_heading: str     # Full original heading line
    struck_through: bool
    date_added: str      # YYYY-MM-DD or ""
    date_due: str        # YYYY-MM-DD or ""
    status: str          # pending | in-progress | done
    description: str
    proposed_method: str
    related_nodes: list[str]
    body: str            # Full body text of the entry


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(
    r"^## (?P<struck>~~)?\[TODO-(?P<num>\d{3})\]\s*(?P<title>.+?)(?:~~)?$",
    re.MULTILINE,
)

_FIELD_RE = re.compile(
    r"^\s*-\s+\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.+)$",
    re.MULTILINE,
)

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _extract_field(body: str, key: str) -> str:
    """Return the value for a bold-key field in a todo entry body."""
    for m in _FIELD_RE.finditer(body):
        if m.group("key").strip().lower() == key.lower():
            return m.group("value").strip()
    return ""


def _parse_links(raw: str) -> list[str]:
    """Extract [[link]] references from a field value."""
    if raw in ("—", "-", ""):
        return []
    return [f"[[{m.group(1)}]]" for m in _LINK_RE.finditer(raw)]


def _split_entries(content: str) -> list[tuple[re.Match, str]]:
    """Return list of (heading_match, body_text) for each TODO section."""
    matches = list(_HEADING_RE.finditer(content))
    results = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        results.append((m, body))
    return results


def _parse_date(raw: str) -> str:
    """Normalize a date string; return '' for dash/empty."""
    raw = raw.strip()
    if raw in ("—", "-", "", "null"):
        return ""
    # Accept YYYY-MM-DD directly
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw
    return ""


def _map_status(raw_status: str, struck: bool) -> str:
    """Map todo status to schema values."""
    if struck:
        return "completed"
    normalized = raw_status.strip("`").lower()
    mapping = {
        "done": "completed",
        "pending": "pending",
        "in-progress": "in-progress",
        "in progress": "in-progress",
    }
    return mapping.get(normalized, "pending")


def parse_todos(content: str) -> list[TodoEntry]:
    """Parse all TODO entries from user-todo.md content."""
    entries = []
    for m, body in _split_entries(content):
        struck = bool(m.group("struck"))
        num = m.group("num")
        title = m.group("title").strip()

        date_added = _parse_date(_extract_field(body, "Date Added"))
        date_due = _parse_date(_extract_field(body, "Date Due"))
        raw_status = _extract_field(body, "Status")
        status = _map_status(raw_status, struck)
        description = _extract_field(body, "Task Description")
        proposed_method = _extract_field(body, "Proposed Method")
        raw_links = _extract_field(body, "Related Nodes")
        related_nodes = _parse_links(raw_links)

        entries.append(TodoEntry(
            number=num,
            title=title,
            raw_heading=m.group(0),
            struck_through=struck,
            date_added=date_added,
            date_due=date_due or "null",
            status=status,
            description=description,
            proposed_method=proposed_method,
            related_nodes=related_nodes,
            body=body,
        ))
    return entries


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convert title text to a filesystem-safe slug (max 40 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text[:40].rstrip("-")


def todo_filename(entry: TodoEntry) -> str:
    """Return filename like todo_001_use-markitdown-to-read-pptx.md."""
    slug = _slugify(entry.title)
    return f"todo_{entry.number}_{slug}.md"


# ---------------------------------------------------------------------------
# File rendering
# ---------------------------------------------------------------------------

def _render_links_yaml(links: list[str]) -> str:
    """Render links list for frontmatter."""
    if not links:
        return "[]"
    items = "\n".join(f'  - "{lnk}"' for lnk in links)
    return f"\n{items}"


def render_todo_file(entry: TodoEntry) -> str:
    """Render a complete todo .md file with frontmatter and body."""
    desc_short = entry.description[:100]
    date_created = entry.date_added or TODAY
    links_yaml = _render_links_yaml(entry.related_nodes)
    deadline = entry.date_due if entry.date_due and entry.date_due != "null" else "null"

    frontmatter = (
        f"---\n"
        f"title: \"{entry.title}\"\n"
        f"description: \"{desc_short}\"\n"
        f"tags: migrated\n"
        f"date_created: {date_created}\n"
        f"status: {entry.status}\n"
        f"deadline: {deadline}\n"
        f"frequency: one-off\n"
        f"links: {links_yaml}\n"
        f"---\n"
    )

    body_section = (
        f"\n# [TODO-{entry.number}] {entry.title}\n\n"
        f"{entry.body}\n"
    )
    return frontmatter + body_section


def render_todos_index(entries: list[TodoEntry]) -> str:
    """Render wiki/todos/.index.md."""
    rows = []
    for e in entries:
        fname = todo_filename(e)
        desc = e.description[:60].rstrip() + ("..." if len(e.description) > 60 else "")
        date_created = e.date_added or TODAY
        rows.append(f"| [{e.title[:50]}]({fname}) | {desc} | {date_created} |")

    table = "\n".join(rows)
    return (
        f"---\n"
        f"title: Todos\n"
        f"description: Actionable items with deadlines and status\n"
        f"tags: index, todos\n"
        f"date_created: {TODAY}\n"
        f"links: []\n"
        f"---\n\n"
        f"# Todos\n\n"
        f"> **Last updated:** {TODAY}\n\n"
        f"| Page | Description | Date Created |\n"
        f"|------|-------------|-------------- |\n"
        f"{table}\n"
    )


def render_events_index() -> str:
    """Render wiki/events/.index.md (empty table)."""
    return (
        f"---\n"
        f"title: Events\n"
        f"description: Life events, decisions, conversations\n"
        f"tags: index, events\n"
        f"date_created: {TODAY}\n"
        f"links: []\n"
        f"---\n\n"
        f"# Events\n\n"
        f"> **Last updated:** {TODAY}\n\n"
        f"| Page | Description | Date Created |\n"
        f"|------|-------------|-------------- |\n"
    )


def render_root_index() -> str:
    """Render the updated wiki/.index.md with all four sections."""
    return (
        f"---\n"
        f"title: Memory Wiki\n"
        f"description: Root navigation index for the dagi-memory wiki\n"
        f"tags: index, navigation, wiki\n"
        f"date_created: 2026-06-28\n"
        f"links: []\n"
        f"---\n\n"
        f"# Memory Wiki\n\n"
        f"> **Last updated:** {TODAY}\n\n"
        f"| Section | Description |\n"
        f"|---------|-------------|\n"
        f"| [Projects](projects/.index.md) | Bounded initiatives with goals and subtasks |\n"
        f"| [Todos](todos/.index.md) | Actionable items with deadlines and status |\n"
        f"| [Knowledge](knowledge/.index.md) | Durable domain expertise and personal frameworks |\n"
        f"| [Events](events/.index.md) | Life events, decisions, conversations |\n"
    )


# ---------------------------------------------------------------------------
# Migration orchestration
# ---------------------------------------------------------------------------

def migrate(wiki_root: Path) -> None:
    """Run the full migration."""
    todo_src = wiki_root / "user-todo.md"
    todo_bak = wiki_root / "user-todo.md.bak"
    todos_dir = wiki_root / "todos"
    events_dir = wiki_root / "events"
    root_index = wiki_root / ".index.md"

    # 1. Validate source exists
    if not todo_src.exists():
        raise FileNotFoundError(f"Source not found: {todo_src}")

    content = todo_src.read_text(encoding="utf-8")

    # 2. Parse todos
    entries = parse_todos(content)
    print(f"Parsed {len(entries)} TODO entries.")

    # 3. Create todos/ directory
    todos_dir.mkdir(exist_ok=True)
    print(f"Created: {todos_dir}")

    # 4. Write individual todo files
    for entry in entries:
        fname = todo_filename(entry)
        fpath = todos_dir / fname
        fpath.write_text(render_todo_file(entry), encoding="utf-8")
        print(f"  Wrote: {fname}  [{entry.status}]")

    # 5. Write todos/.index.md
    (todos_dir / ".index.md").write_text(
        render_todos_index(entries), encoding="utf-8"
    )
    print(f"Wrote: {todos_dir / '.index.md'}")

    # 6. Create events/ directory + index
    events_dir.mkdir(exist_ok=True)
    print(f"Created: {events_dir}")
    (events_dir / ".index.md").write_text(render_events_index(), encoding="utf-8")
    print(f"Wrote: {events_dir / '.index.md'}")

    # 7. Backup user-todo.md (rename, not delete)
    shutil.move(str(todo_src), str(todo_bak))
    print(f"Backed up: {todo_src} → {todo_bak}")

    # 8. Update root .index.md
    root_index.write_text(render_root_index(), encoding="utf-8")
    print(f"Updated: {root_index}")

    print("\nMigration complete.")
    _verify(wiki_root, entries)


def _verify(wiki_root: Path, entries: list[TodoEntry]) -> None:
    """Print a quick post-migration verification summary."""
    todos_dir = wiki_root / "todos"
    events_dir = wiki_root / "events"

    checks = [
        ("todos/.index.md exists", (todos_dir / ".index.md").exists()),
        ("events/.index.md exists", (events_dir / ".index.md").exists()),
        ("user-todo.md.bak exists", (wiki_root / "user-todo.md.bak").exists()),
        ("user-todo.md removed", not (wiki_root / "user-todo.md").exists()),
        (".index.md updated", (wiki_root / ".index.md").exists()),
        ("projects/ unchanged", (wiki_root / "projects").is_dir()),
        ("knowledge/ unchanged", (wiki_root / "knowledge").is_dir()),
    ]

    todo_files = list(todos_dir.glob("todo_*.md"))
    checks.append((
        f"todo files count == {len(entries)}",
        len(todo_files) == len(entries),
    ))

    print("\nVerification:")
    all_ok = True
    for label, ok in checks:
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {label}")
        if not ok:
            all_ok = False

    if not all_ok:
        raise RuntimeError("One or more verification checks failed.")
    print("\nAll checks passed.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    migrate(WIKI_ROOT)
