"""Live message board sidebar with a bounded composer and attachment cards."""
from __future__ import annotations

import weakref
from concurrent.futures import CancelledError
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QToolButton, QVBoxLayout, QWidget,
)
from shiboken6 import isValid

from agent._board_files import validate_attachment
from agent import DAGI_ROOT
from pyside_gui.board_runtime import check_user_file, error_text
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


class MessageBoardView(QWidget):
    open_file_requested = Signal(str)
    _download_done = Signal(object, object, object)

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[int] = set()
        self._cards: dict[int, weakref.ReferenceType] = {}
        self._poster = None
        self._fetch = None
        self._closing = False
        self._paths: list[Path] = []
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
        self._posts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, 1)
        outer.addWidget(self._build_composer())

    def _build_composer(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 4, 8, 8)
        self._chips = QHBoxLayout()
        layout.addLayout(self._chips)
        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Post to the board…")
        self._input.textChanged.connect(self._update_count)
        self._input.returnPressed.connect(self._send)
        self._count = _plain_label("0/700")
        self._attach = QToolButton()
        self._attach.setText("Attach")
        self._attach.clicked.connect(self._choose_files)
        self._send_button = QPushButton("Send")
        self._send_button.clicked.connect(self._send)
        row.addWidget(self._input, 1)
        row.addWidget(self._count)
        row.addWidget(self._attach)
        row.addWidget(self._send_button)
        layout.addLayout(row)
        box.setEnabled(False)
        self._composer = box
        return box

    def set_status(self, text: str) -> None:
        self._status.setText(str(text))

    def set_poster(self, poster) -> None:
        self._poster = poster
        self._composer.setEnabled(poster is not None)
        self._update_count(self._input.text())

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

    def _choose_files(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "Attach files")
        self.add_files(names)

    def add_files(self, paths) -> None:
        for raw in paths:
            path = Path(raw)
            if path in self._paths:
                continue
            if len(self._paths) >= 4:
                self.set_status("Attach at most 4 files.")
                break
            error = check_user_file(path)
            if error is not None:
                self.set_status(error)
                continue
            self._paths.append(path)
            self._add_chip(path)

    def _add_chip(self, path: Path) -> None:
        button = QToolButton()
        button.setText(f"{path.name}  ×")
        button.setProperty("attachment_path", str(path))
        button.clicked.connect(lambda: self._remove_path(path, button))
        self._chips.addWidget(button)

    def _remove_path(self, path: Path, button: QWidget) -> None:
        if path in self._paths:
            self._paths.remove(path)
        button.deleteLater()

    def _update_count(self, text: str) -> None:
        self._count.setText(f"{len(text)}/700")
        invalid = len(text) > 700
        self._count.setStyleSheet("color: #d55;" if invalid else "")
        ready = bool(text.strip()) and not invalid and self._poster is not None
        self._send_button.setEnabled(ready)

    def _send(self) -> None:
        text = self._input.text()
        if self._poster is None or not text.strip() or len(text) > 700:
            return
        if not self._poster(text, list(self._paths)):
            return
        self._input.clear()
        self._paths.clear()
        while self._chips.count():
            item = self._chips.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
