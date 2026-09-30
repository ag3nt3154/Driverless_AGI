from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from pyside_gui.theme import with_theme

_LOGGER = logging.getLogger(__name__)

_PAGE = Path(__file__).parent / "resources" / "notepad" / "notepad.html"
_EXTERNAL_SCHEMES = frozenset({"http", "https", "mailto"})


def open_external(url: str) -> bool:
    """Open *url* in the system handler when it uses a safe scheme."""
    qurl = QUrl(url)
    if qurl.scheme().lower() not in _EXTERNAL_SCHEMES:
        return False
    return QDesktopServices.openUrl(qurl)


class _Bridge(QObject):
    """Object exposed to notepad.js as ``channel.objects.notepad``."""

    ready = Signal()
    content_changed = Signal(str)
    save_requested = Signal()

    @Slot()
    def onReady(self) -> None:  # noqa: N802 - JS-facing name
        self.ready.emit()

    @Slot(str)
    def contentChanged(self, text: str) -> None:  # noqa: N802 - JS-facing name
        self.content_changed.emit(text)

    @Slot()
    def saveRequested(self) -> None:  # noqa: N802 - JS-facing name
        self.save_requested.emit()

    @Slot(str)
    def openLink(self, url: str) -> None:  # noqa: N802 - JS-facing name
        open_external(url)



class _NotepadPage(QWebEnginePage):
    """Keeps the editor page in place: every navigation away is sent to the OS browser."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:  # noqa: N802
        if url.isLocalFile() and url.path().endswith("notepad.html"):
            return True
        # setHtml() (used to splice in the theme tokens) loads via a data: URL.
        link = QWebEnginePage.NavigationType.NavigationTypeLinkClicked
        if url.scheme() == "data" and is_main_frame and nav_type != link:
            return True
        open_external(url.toString())
        return False


class NotepadEditor(QWebEngineView):
    """Vditor WYSIWYG markdown editor hosted in a web view."""

    ready = Signal()
    content_changed = Signal(str)
    save_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ready = False
        self._pending_text: str | None = None
        self.setPage(_NotepadPage(self))
        self._bridge = _Bridge(self)
        self._bridge.ready.connect(self._on_ready)
        self._bridge.content_changed.connect(self.content_changed)
        self._bridge.save_requested.connect(self.save_requested)
        self._channel = QWebChannel(self)
        self._channel.registerObject("notepad", self._bridge)
        self.page().setWebChannel(self._channel)
        # setHtml with the page's own file URL as base: relative asset paths
        # resolve as before and _NotepadPage still accepts the navigation.
        html = with_theme(_PAGE.read_text(encoding="utf-8"))
        self.setHtml(html, QUrl.fromLocalFile(str(_PAGE)))

    def is_ready(self) -> bool:
        return self._ready

    def _on_ready(self) -> None:
        self._ready = True
        if self._pending_text is not None:
            text, self._pending_text = self._pending_text, None
            self.set_markdown(text)
        self.ready.emit()

    def set_markdown(self, text: str) -> None:
        """Replace the editor content (no content_changed echo, undo cleared)."""
        if not self._ready:
            self._pending_text = text
            return
        self.page().runJavaScript(f"npSetMarkdown({json.dumps(text)})")

    def fetch_markdown(self, callback: Callable[[str | None], None]) -> None:
        """Asynchronously read the current markdown; *callback* gets None if not ready."""
        if not self._ready:
            callback(self._pending_text)
            return
        self.page().runJavaScript("npGetMarkdown()", 0, callback)

    def focus_editor(self) -> None:
        if self._ready:
            self.setFocus()
            self.page().runJavaScript("npFocus()")
