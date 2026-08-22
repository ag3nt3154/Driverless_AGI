from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

os.environ["NO_PROXY"] = "127.0.0.1, localhost, 172.25.*"

import typer
from dotenv import load_dotenv

load_dotenv()

from agent.config_loader import resolve_model_config
from pyside_gui.app import DagiMainWindow

from PySide6.QtWidgets import QApplication

_cli = typer.Typer(name="dagi-gui", add_completion=False)


@_cli.command()
def main(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model ID from .dagi/config.yaml"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    project: Optional[str] = typer.Option(
        None, "--project", "-p", help="Project directory"
    ),
) -> None:
    project_path = Path(project).resolve() if project else Path.cwd()
    config = resolve_model_config(model, project_path=project_path)
    qt_app = QApplication(sys.argv)
    window = DagiMainWindow(config, project_path, verbose)
    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    _cli()
