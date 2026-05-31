"""
tui.py — Textual TUI for Driverless AGI.

Usage:
    conda run --no-capture-output -n dagi python tui.py
    conda run --no-capture-output -n dagi python tui.py --project /path/to/project
    conda run --no-capture-output -n dagi python tui.py --model deepseek-v4-pro-openrouter
"""
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

from tui import DagiApp  # noqa: E402

_cli = typer.Typer(name="dagi-tui", add_completion=False)


@_cli.command()
def main(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model ID from config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full tool output"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    DagiApp(model_id=model, project=project, verbose=verbose).run()


if __name__ == "__main__":
    _cli()
