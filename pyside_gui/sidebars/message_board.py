"""Read-only live message board sidebar with attachment cards."""
from __future__ import annotations

import weakref
from concurrent.futures import CancelledError
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from agent._board_files import validate_attachment
from agent import DAGI_ROOT
from pyside_gui.board_runtime import error_text
from pyside_gui.sidebars.board_widgets import PostCard
from pyside_gui.theme import qss
from tools.board._board import _scan_memes


def _plain_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _local_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except (ValueError, OverflowError, OSError):
        return None


def _normalized(post: dict) -> dict:
    """Coerce untrusted remote fields into the shapes the card renders."""
    def text_field(name: str) -> str:
        value = post.get(name)
        return value if isinstance(value, str) else ""

    reply_to = post.get("reply_to")
    return {
        **post,
        "author": text_field("author"),
        "text": text_field("text"),
        "meme": text_field("meme") or None,
        "reply_to": reply_to if type(reply_to) is int else None,
        "attachments": _safe_attachments(post),
    }


def _safe_attachments(post: dict) -> list[dict]:
    result = []
    attachments = post.get("attachments", [])
    if not isinstance(attachments, list):
        return result
    for attachment in attachments:
        try:
            result.append(validate_attachment(attachment.get("id"), attachment))
        except (AttributeError, ValueError):
            continue
    return result


def board_url(text: str) -> str | None:
    """Normalise a typed board address to ``scheme://host[:port]``, or None when invalid."""
    text = text.strip()
    if text and "://" not in text:
        text = "http://" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    valid = (parts.scheme in ("http", "https") and parts.hostname
             and not any((parts.username, parts.password, parts.query, parts.fragment))
             and parts.path in ("", "/"))
    if not valid:
        return None
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


class MessageBoardView(QWidget):
    open_file_requested = Signal(str)
    connect_requested = Signal(str, object)  # url, token (None = keep the current token)
    _download_done = Signal(object, object, object)

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[int] = set()
        self._cards: dict[int, weakref.ReferenceType] = {}
        self._fetch = None
        self._closing = False
        self._memes = _scan_memes(DAGI_ROOT / ".dagi" / "emotes" / "memes")
        self._build()
        self._download_done.connect(self._on_download_done)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        header = _plain_label("MESSAGE BOARD")
        header.setObjectName("board-header")
        header.setStyleSheet(qss("color: @fg_secondary; font-weight: bold; padding: 8px;"))
        outer.addWidget(header)
        outer.addLayout(self._build_connection())
        self._status = _plain_label("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(qss("color: @fg_secondary; padding: 0 8px;"))
        outer.addWidget(self._status)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._posts_layout = QVBoxLayout(self._container)
        self._posts_layout.setContentsMargins(8, 4, 8, 8)
        self._posts_layout.setSpacing(10)
        # A trailing stretch, not setAlignment(AlignTop): an aligned layout is sized
        # from sizeHint and ignores heightForWidth, clipping wrapped post text when narrow.
        self._posts_layout.addStretch()
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)

    def _build_connection(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        self._url_label = _plain_label("not connected")
        self._url_label.setStyleSheet(qss("color: @fg_secondary;"))
        self._fallback = _plain_label("central")
        self._fallback.setStyleSheet(qss(
            "color: @fg_secondary; border: 1px solid @border; border-radius: 6px; padding: 0 6px;"
        ))
        self._connect = QToolButton()
        self._connect.setText("Connect…")
        self._connect.setToolTip("Connect to another message board")
        self._connect_menu = QMenu(self._connect)
        self._switch_central_action = QAction(self._connect_menu)
        self._switch_central_action.setVisible(False)
        self._switch_central_action.setEnabled(False)
        self._connect_menu.addAction(self._switch_central_action)
        self._switch_central_action.triggered.connect(self._switch_to_central)
        self._connect_menu.addSeparator()
        self._connect_another_action = self._connect_menu.addAction("Connect to another board…")
        self._connect_another_action.triggered.connect(self._ask_url)
        self._connect.setMenu(self._connect_menu)
        self._connect.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(self._url_label, 1)
        row.addWidget(self._fallback)
        row.addWidget(self._connect)
        self._central_url = ""
        return row

    def set_connection(self, url: str, central_url: str | None) -> None:
        """Show the connected board and whether it is temporary or central."""
        self._url_label.setText(url)
        self._central_url = central_url or ""
        is_temp = bool(central_url)
        self._fallback.setText("temp" if is_temp else "central")
        self._fallback.setToolTip(
            f"Temporary board — {central_url} is unreachable; posts here are discarded "
            "when DAGI closes" if is_temp else "Central board"
        )
        self._fallback.setStyleSheet(qss(
            "color: @popover_bg; background: #c98a1b; border-radius: 6px; padding: 0 6px;"
            if is_temp else
            "color: @fg_secondary; border: 1px solid @border; border-radius: 6px; padding: 0 6px;"
        ))
        self._switch_central_action.setText(f"Switch to central ({central_url})" if is_temp else "")
        self._switch_central_action.setVisible(is_temp)
        self._switch_central_action.setEnabled(False)
        tip = self._fallback.toolTip() if is_temp else url
        self._url_label.setToolTip(tip)

    def set_central_available(self, url: str, available: bool) -> None:
        """Enable switching only when the currently configured central URL is reachable."""
        self._switch_central_action.setEnabled(
            bool(available) and bool(self._central_url) and url == self._central_url
        )

    @Slot()
    def _switch_to_central(self) -> None:
        if self._central_url:
            self.connect_requested.emit(self._central_url, None)

    def _ask_url(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Connect to message board", "Board URL:", text=self._url_label.text(),
        )
        if not ok:
            return
        url = board_url(text)
        if url is None:
            self.set_status("Enter an http(s) board address such as http://host:8765.")
            return
        self.connect_requested.emit(url, None)

    def ask_token(self, url: str) -> None:
        token, ok = QInputDialog.getText(
            self, "Board token", f"{url} needs a bearer token:", QLineEdit.EchoMode.Password,
        )
        if ok and token.strip():
            self.connect_requested.emit(url, token.strip())

    def clear_posts(self) -> None:
        """Drop every card before showing another board's posts."""
        while self._posts_layout.count() > 1:  # keep the trailing stretch
            item = self._posts_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._seen.clear()
        self._cards.clear()

    def set_status(self, text: str) -> None:
        self._status.setText(str(text))

    @property
    def meme_map(self) -> dict[str, Path]:
        """Meme name to local asset path, scanned once when the view is built."""
        return self._memes

    def set_fetcher(self, fetch) -> None:
        self._fetch = fetch

    def close_downloads(self) -> None:
        self._closing = True
        self._fetch = None

    @Slot(object)
    def add_post(self, post: dict) -> None:
        if self._closing or not isinstance(post, dict):
            return
        post_id = post.get("id")
        if type(post_id) is not int or post_id in self._seen:
            return
        post = _normalized(post)
        card = PostCard(
            post, _local_time(post.get("created_at")), self._memes.get(post["meme"]),
        )
        self._seen.add(post_id)
        card.open_file_requested.connect(self.open_file_requested)
        self._cards[post_id] = weakref.ref(card)
        self._posts_layout.insertWidget(0, card)
        self._scroll.verticalScrollBar().setValue(0)
        if self._fetch is not None:
            view_ref = weakref.ref(self)
            for attachment in post.get("attachments", []):
                future = self._fetch(attachment["id"])
                def complete(done, pid=post_id, att=dict(attachment), ref=view_ref):
                    view = ref()
                    if view is not None and isValid(view) and not view._closing:
                        view._future_finished(pid, att, done)
                future.add_done_callback(complete)

    def _future_finished(self, post_id: int, attachment: dict, future) -> None:
        try:
            result = future.result()
        except Exception as error:
            result = error
        self._download_done.emit(post_id, attachment, result)

    @Slot(object, object, object)
    def _on_download_done(self, post_id, attachment, result) -> None:
        if self._closing:
            return
        card = self._cards.get(post_id, lambda: None)()
        if card is None or not isValid(card) or isinstance(result, CancelledError):
            return
        if isinstance(result, BaseException):
            card.attachment_failed(attachment["id"], error_text(result))
        elif isinstance(result, (str, Path)):
            card.attachment_ready(attachment["id"], Path(result))
