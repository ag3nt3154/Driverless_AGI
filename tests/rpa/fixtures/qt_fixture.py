"""tests/rpa/fixtures/qt_fixture.py — a Qt window for `test_uia_driver.py` desktop tests.

Run standalone: `python -m tests.rpa.fixtures.qt_fixture` (run from the repo root so the
`tests` package resolves). Exercises the UIA cases Subtask 7 needs: a stable
`objectName`, two unnamed-id duplicates, a per-launch unstable id, a password field,
a child dialog, and a control that appears after a delay.
"""
from __future__ import annotations

import random
import sys

import pyside_gui  # noqa: F401 - register Qt DLL paths before any PySide6 import (AGENTS.md)
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMainWindow,
    QMenuBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

WINDOW_TITLE = "RPA Qt Fixture"


class SaveAsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save As")
        layout = QFormLayout(self)
        self.file_name = QLineEdit(self)
        self.file_name.setAccessibleName("File name:")
        layout.addRow("File name:", self.file_name)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)


class FixtureWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)

        menu_bar = QMenuBar(self)
        menu_bar.addMenu("File")
        menu_bar.addMenu("Reports")
        self.setMenuBar(menu_bar)

        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.from_date = QDateEdit(central)
        self.from_date.setAccessibleName("From date")
        layout.addWidget(self.from_date)

        self.comment = QLineEdit(central)
        self.comment.setAccessibleName("Comment")
        layout.addWidget(self.comment)

        self.password = QLineEdit(central)
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setAccessibleName("Password")
        layout.addWidget(self.password)

        self.export_btn = QPushButton("Export CSV", central)
        self.export_btn.setObjectName("btnExport")
        self.export_btn.clicked.connect(self._open_save_as)
        layout.addWidget(self.export_btn)

        self.ok_btn_1 = QPushButton("OK", central)
        layout.addWidget(self.ok_btn_1)
        self.ok_btn_2 = QPushButton("OK", central)
        layout.addWidget(self.ok_btn_2)

        self.random_btn = QPushButton("Random", central)
        self.random_btn.setObjectName(f"rnd_{random.randint(100000, 999999)}")
        layout.addWidget(self.random_btn)

        self.setCentralWidget(central)
        self._layout = layout

        QTimer.singleShot(1500, self._show_late_button)

    def _show_late_button(self) -> None:
        late_btn = QPushButton("Appeared late", self.centralWidget())
        self._layout.addWidget(late_btn)
        self.late_btn = late_btn

    def _open_save_as(self) -> None:
        dialog = SaveAsDialog(self)
        dialog.exec()


def main() -> int:
    app = QApplication(sys.argv)
    window = FixtureWindow()
    window.resize(480, 360)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
