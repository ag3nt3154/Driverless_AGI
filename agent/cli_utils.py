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

    agents_file = dagi_dir / "agents.md"
    project_name = project_path.name
    agents_stub = (
        f"# Project: {project_name}\n\n"
        f"> **Last updated:** {today}\n\n"
        "## Description\n\n"
        "_What this project does and why it exists._\n\n"
        "## Objectives\n\n"
        "_Key goals and success criteria._\n\n"
        "## Directory Structure\n\n"
        f"```\n{project_name}/\n```\n\n"
        "## Environment\n\n"
        "- **Language:**\n"
        "- **Runtime / virtual env:**\n"
        "- **Install dependencies:**\n"
        "- **Run command:**\n\n"
        "## Known Issues & Resolutions\n\n"
        "_Document errors encountered and how they were resolved._\n\n"
        "## Recent Changes\n\n"
        "_Updated by the agent after each task._\n"
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
        "[dim]Next: use [bold]spawn_memory_add_subagent[/bold] to add knowledge, "
        "or drop files into [bold]dagi-memory/raw/[/bold] then invoke [bold]memory-ingest[/bold]. "
        "Add workflows to [bold].dagi/workflow/<name>/workflow.md[/bold].[/dim]"
    )
