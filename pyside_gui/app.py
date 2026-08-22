from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QLabel, QVBoxLayout, QWidget

from agent.loop import AgentConfig


class DagiMainWindow(QMainWindow):
    def __init__(
        self,
        config: AgentConfig,
        project_path: Path,
        verbose: bool,
    ) -> None:
        super().__init__()
        self._config = config
        self._project_path = project_path
        self._verbose = verbose

        self.setWindowTitle(
            f"Driverless AGI — {config.display_name}"
        )
        self.setMinimumSize(1200, 700)

        placeholder = QLabel(
            f"DAGI · {config.display_name} · {project_path}"
        )
        placeholder.setStyleSheet(
            "color: #88ccff; font-size: 16px; padding: 20px;"
        )
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(placeholder)
        self.setCentralWidget(central)
