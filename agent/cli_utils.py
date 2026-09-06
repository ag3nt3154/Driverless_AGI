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
    from agent._init_templates import build_init_files

    dagi_dir = project_path / ".dagi"
    for name in ("skills", "workflow", "self-review", "logs"):
        (dagi_dir / name).mkdir(parents=True, exist_ok=True)

    files = build_init_files(project_path.name, date.today().isoformat())
    created: list[str] = []
    skipped: list[str] = []
    for relative, content in files.items():
        path = project_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError:
            skipped.append(relative)
        else:
            created.append(relative)

    console.print(f"[green]✓ Initialised[/green] [dim]{dagi_dir}[/dim]")
    for relative in created:
        console.print(f"  [dim]created:[/dim] {relative}")
    for relative in skipped:
        console.print(f"  [dim]skipped (exists):[/dim] {relative}")
    console.print(
        "[dim]Next: use [bold]wiki-query[/bold] for project knowledge and "
        "[bold]wiki-add[/bold] to save selected findings. Invoke [bold]wiki-refresh[/bold] "
        "explicitly for maintenance. "
        "Add workflows to [bold].dagi/workflow/<name>/workflow.md[/bold].[/dim]"
    )
