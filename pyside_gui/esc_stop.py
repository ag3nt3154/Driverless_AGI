"""Global Esc: stop the running agent from anywhere in DAGI's windows.

Web views (conversation pane, file viewer, notepad) swallow key presses, so a
window-level ``keyPressEvent`` never sees Esc once the user has clicked into
one. An application-wide event filter sees the key first.

Esc still goes to whatever is open: Qt popups (menus, combo lists), modal
dialogs, and any visible widget flagged ``claimsEscape`` (slash completer,
copy picker) close first. When the agent is idle, paused or waiting on an
``ask_user`` answer, Esc passes through untouched.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QWidget

CLAIMS_ESCAPE = "claimsEscape"


def claim_escape(widget: QWidget) -> None:
    """Mark ``widget`` as handling Esc itself while it is visible."""
    widget.setProperty(CLAIMS_ESCAPE, True)


def _claimed(window: QWidget) -> bool:
    return any(
        w.property(CLAIMS_ESCAPE) and w.isVisible()
        for w in window.findChildren(QWidget)
    )


class EscapeStop(QObject):
    """Application event filter that turns Esc into ``stop()`` while
    ``can_stop()`` is true and the key came from one of ``windows()``."""

    def __init__(
        self,
        windows: Callable[[], list[QWidget]],
        can_stop: Callable[[], bool],
        stop: Callable[[], None],
    ) -> None:
        super().__init__()
        self._windows = windows
        self._can_stop = can_stop
        self._stop = stop

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if event.type() != QEvent.Type.KeyPress or event.key() != Qt.Key.Key_Escape:
            return False
        if not isinstance(obj, QWidget) or event.isAutoRepeat():
            return False
        if QApplication.activePopupWidget() or QApplication.activeModalWidget():
            return False
        window = obj.window()
        if not any(window is w for w in self._windows()) or _claimed(window):
            return False
        if not self._can_stop():
            return False
        self._stop()
        return True


def install(win) -> EscapeStop:
    """Wire global Esc for the main window ``win`` (and the desktop pet)."""

    def windows() -> list[QWidget]:
        pet = getattr(win, "_desktop_pet", None)
        return [win] + ([pet] if pet is not None else [])

    def can_stop() -> bool:
        loop = win._current_loop_ref[0] if win._current_loop_ref else None
        return bool(
            win._worker and win._worker.is_alive() and loop is not None
            and not loop.is_paused and win._pending_ask is None
        )

    esc = EscapeStop(windows, can_stop, win._action_pause)
    QApplication.instance().installEventFilter(esc)
    return esc
