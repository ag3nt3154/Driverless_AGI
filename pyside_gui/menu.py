from __future__ import annotations

import os
import sys
from collections.abc import Callable

from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QMainWindow, QMessageBox

from pyside_gui.menu_style import MENU_STYLESHEET
from pyside_gui.theme import MODES, load_preference, save_preference


def build_main_menu(
    window: QMainWindow,
    *,
    on_new_session: Callable[[], None],
    on_compact: Callable[[], None],
    on_compose: Callable[[], None],
    on_theme: Callable[[str], None],
) -> None:
    menu = window.menuBar()
    menu.setStyleSheet(MENU_STYLESHEET)

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

    view_menu = menu.addMenu("&View")
    theme_menu = view_menu.addMenu("&Theme")
    group = QActionGroup(window)
    current = load_preference()
    for mode in MODES:
        act = QAction(mode.capitalize(), window, checkable=True)
        act.setChecked(mode == current)
        act.triggered.connect(lambda _checked, m=mode: on_theme(m))
        group.addAction(act)
        theme_menu.addAction(act)


def choose_theme(window: QMainWindow, choice: str, *, busy: bool) -> None:
    """Save the theme. Stylesheets are built at import, so offer a relaunch
    (unless an agent run is in flight, which a restart would kill)."""
    save_preference(choice)
    os.environ.pop("DAGI_THEME", None)  # the saved choice wins from now on
    name = choice.capitalize()
    if busy:
        QMessageBox.information(window, "Theme", f"{name} theme saved. It applies on the next launch.")
        return
    answer = QMessageBox.question(
        window, "Theme",
        f"{name} theme saved. Restart Driverless AGI now to apply it?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    # orig_argv keeps "-m pyside_gui" (argv[0] alone would be __main__.py).
    started, _pid = QProcess.startDetached(sys.executable, sys.orig_argv[1:], os.getcwd())
    if started:
        window.close()
