from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow


def build_main_menu(
    window: QMainWindow,
    *,
    on_new_session: Callable[[], None],
    on_compact: Callable[[], None],
    on_compose: Callable[[], None],
) -> None:
    menu = window.menuBar()
    menu.setStyleSheet("""
        QMenuBar {
            background: #313244; color: #cdd6f4;
            border-bottom: 1px solid #45475a;
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 13px;
            padding: 2px 0px;
        }
        QMenuBar::item {
            padding: 4px 12px;
            border-radius: 4px;
            margin: 2px 2px;
        }
        QMenuBar::item:selected { background: #45475a; }
        QMenu {
            background: #313244; color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            padding: 4px;
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 13px;
        }
        QMenu::item {
            padding: 6px 24px 6px 12px;
            border-radius: 4px;
        }
        QMenu::item:selected { background: #45475a; }
    """)

    file_menu = menu.addMenu("&File")
    new_act = QAction("&New Session", window)
    new_act.setShortcut(QKeySequence("Ctrl+N"))
    new_act.triggered.connect(on_new_session)
    file_menu.addAction(new_act)

    exit_act = QAction("E&xit", window)
    exit_act.setShortcut(QKeySequence("Ctrl+Q"))
    exit_act.triggered.connect(window.close)
    file_menu.addAction(exit_act)

    sess_menu = menu.addMenu("&Session")
    compact_act = QAction("&Compact", window)
    compact_act.triggered.connect(on_compact)
    sess_menu.addAction(compact_act)

    compose_act = QAction("&Compose Mode", window)
    compose_act.setShortcut(QKeySequence("Ctrl+O"))
    compose_act.triggered.connect(on_compose)
    sess_menu.addAction(compose_act)
