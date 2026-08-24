"""
pyside_gui.py — PySide6 GUI for Driverless AGI.

Usage:
    conda run --no-capture-output -n dagi python pyside_gui.py
    conda run --no-capture-output -n dagi python pyside_gui.py --project /path/to/project
    conda run --no-capture-output -n dagi python pyside_gui.py --model deepseek-v4-pro-openrouter
"""
import os
os.environ["NO_PROXY"] = "127.0.0.1, localhost, 172.25.*"

import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv

load_dotenv()

from agent.config_loader import resolve_model_config
from pyside_gui.app import DagiMainWindow

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

_cli = typer.Typer(name="dagi-gui", add_completion=False)


@_cli.command()
def main(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model ID from .dagi/config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    project_path = Path(project).resolve() if project else Path.cwd()
    config = resolve_model_config(model, project_path=project_path)
    qt_app = QApplication(sys.argv)
    _icon = Path(__file__).parent / "pyside_gui" / "resources" / "icon.png"
    if _icon.exists():
        qt_app.setWindowIcon(QIcon(str(_icon)))
    window = DagiMainWindow(config, project_path, verbose)
    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    _cli()
