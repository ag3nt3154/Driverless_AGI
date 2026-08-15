"""
cli_utils.py — helpers shared between entry points (currently just the TUI).

Extracted from the deprecated cli.py (moved to archives/) so the TUI no
longer depends on an archived module.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from rich.console import Console

console = Console()


def _skill_invocation_message(skill_name: str, user_arg: str) -> str:
    msg = f"Invoke the `{skill_name}` skill."
    if user_arg:
        msg += f"\n\n{user_arg}"
    return msg


def _cmd_init(project_path: Path) -> None:
    dagi_dir = project_path / ".dagi"
    memory = project_path / "dagi-memory"
    today = date.today().isoformat()

    for d in [
        dagi_dir / "skills",
        dagi_dir / "workflow",
        dagi_dir / "self-review",
        dagi_dir / "logs",
        memory / "raw",
        memory / "sources",
        memory / "wiki" / "projects",
        memory / "wiki" / "knowledge",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    agents_file = project_path / "AGENTS.md"
    project_name = project_path.name
    agents_stub = (
        f"# AGENTS.md\n\n"
        f"> Last updated: {today}\n\n"
        "---\n\n"
        "## Overview\n\n"
        f"_What {project_name} does, who/what uses it, and the core problem it solves._\n\n"
        "## Rules\n\n"
        "_Behavioral rules relevant to this specific project._\n\n"
        "## Behavioral Guidelines\n\n"
        "_Coding standards, session protocol, and other stable operating rules. "
        "Preserve verbatim across routine updates._\n\n"
        "## Process Flow\n\n"
        "_Numbered, step-by-step main execution path._\n\n"
        "## Architecture\n\n"
        "_High-level components and how they relate._\n\n"
        "## Key Files & Directories\n\n"
        "| Path | Purpose |\n"
        "|------|---------|\n\n"
        "## Errors Log\n\n"
        "_Capped at the 10 most recent entries: `**{date}**: {error} → {fix}`._\n\n"
        "## Notes & Terms\n\n"
        "_Gotchas and glossary entries._\n\n"
        "---\n\n"
        "## User Insights\n\n"
        "> Independent observations — not highlighted by the user.\n\n"
        "### User Tendencies\n\n"
        "### Project Shortcomings\n\n"
        "### Potential Areas of Exploration\n"
    )
    wiki_stubs: dict[Path, str] = {
        memory / "wiki" / ".index.md": (
            "# Wiki Index\n\n"
            f"> **Last updated:** {today}\n\n"
            "## Sections\n\n"
            "| Section | Description |\n"
            "|---------|-------------|\n"
            "| [projects](projects/.index.md) | Per-project knowledge, context, and updates |\n"
            "| [knowledge](knowledge/.index.md) | General domain knowledge and research |\n"
            "| [User TODO](user-todo.md) | Personal task and intention tracker |\n\n"
            "## Meta Files\n\n"
            "- [log.md](log.md) — Operation history\n"
            "- [open_questions.md](open_questions.md) — Research gaps\n"
        ),
        memory / "wiki" / "projects" / ".index.md": (
            "# Projects\n\n"
            f"> **Last updated:** {today}\n\n"
            "| Project | Description | Last Updated |\n"
            "|---------|-------------|-------------- |\n"
            "| — | — | — |\n"
        ),
        memory / "wiki" / "knowledge" / ".index.md": (
            "# Knowledge\n\n"
            f"> **Last updated:** {today}\n\n"
            "| Topic | Description | Pages |\n"
            "|-------|-------------|-------|\n"
            "| — | — | — |\n"
        ),
        memory / "wiki" / "log.md": (
            "# Memory Log\n\n"
            "> Append-only. Do not edit manually.\n"
            "> Each entry format: `[YYYY-MM-DD] {operation} | {title} | {path}`\n"
            "> Operations: add | add-todo | ingest | query | lint\n\n"
            "<!-- entries appended below -->\n"
        ),
        memory / "wiki" / "user-todo.md": (
            "---\n"
            "type: note\n"
            "topic: user-todos\n"
            "description: Personal task and intention tracker for the Admiral\n"
            f"date_added: {today}\n"
            "tags: todo, tasks, planning, personal\n"
            "---\n\n"
            "# User TODO\n\n"
            "> Personal intention log. Entries are appended by the memory-add skill "
            "whenever the Admiral\n"
            "> expresses a plan or goal. Never delete entries — update `Status` "
            "instead.\n\n"
            "<!-- Append new entries below. -->\n"
        ),
        memory / "wiki" / "open_questions.md": (
            "# Open Questions\n\n"
            f"> **Last updated:** {today}\n\n"
            "## Pending\n\n"
            "| # | Question | Context | Source Page | Date Raised |\n"
            "|---|----------|---------|-------------|-------------|\n"
            "| — | — | — | — | — |\n\n"
            "## Resolved\n\n"
            "| # | Question | Answer Summary | Wiki Page | Date Resolved |\n"
            "|---|----------|----------------|-----------|---------------|\n"
            "| — | — | — | — | — |\n"
        ),
    }

    created: list[str] = []
    skipped: list[str] = []

    if agents_file.exists():
        skipped.append(str(agents_file.relative_to(project_path)))
    else:
        agents_file.write_text(agents_stub, encoding="utf-8")
        created.append(str(agents_file.relative_to(project_path)))

    for path, content in wiki_stubs.items():
        rel = str(path.relative_to(project_path))
        if path.exists() and path.stat().st_size > 0:
            skipped.append(rel)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(rel)

    console.print(f"[green]✓ Initialised[/green] [dim]{dagi_dir}[/dim]")
    for p in created:
        console.print(f"  [dim]created:[/dim] {p}")
    for p in skipped:
        console.print(f"  [dim]skipped (exists):[/dim] {p}")
    if not created and not skipped:
        console.print(f"[dim]Already initialised: {dagi_dir}[/dim]")
    console.print(
        "[dim]Next: use [bold]memory_add[/bold] to add knowledge, "
        "or drop files into [bold]dagi-memory/raw/[/bold] then invoke [bold]memory-ingest[/bold]. "
        "Add workflows to [bold].dagi/workflow/<name>/workflow.md[/bold].[/dim]"
    )
