"""Board post card widgets kept separate from the sidebar controller."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from pyside_gui.theme import qss
from pyside_gui.image_preview import check_image_limits, read_preview
from tools.board._board import human_size

_IMG_MAX = QSize(160, 140)


def _label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _start_movie(label: QLabel, path: Path) -> None:
    """Animate a size-checked GIF meme, scaled to fit the card image box."""
    movie = QMovie(str(path), parent=label)
    if not movie.isValid():
        movie.deleteLater()
        return
    natural = QImageReader(str(path)).size()
    movie.setScaledSize(natural.scaled(_IMG_MAX, Qt.AspectRatioMode.KeepAspectRatio))
    label.setText("")
    label.setMovie(movie)
    movie.start()


class PostCard(QWidget):
    open_file_requested = Signal(str)

    def __init__(
        self, post: dict, timestamp: datetime | None, asset_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._attachments: dict[str, QToolButton | QLabel] = {}
        self.setObjectName("board-card")
        self.setStyleSheet(qss(
            "QWidget#board-card { background: @popover_bg; border: 1px solid @border; }"
        ))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        reply = f"  ↩ #{post['reply_to']}" if post.get("reply_to") is not None else ""
        header.addWidget(_label(f"{post.get('author', '')}{reply}"))
        header.addStretch()
        when = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else "unknown time"
        header.addWidget(_label(when))
        layout.addLayout(header)
        meme = post.get("meme")
        if meme:
            layout.addWidget(self._meme_label(str(meme), asset_path))
        text = _label(str(post.get("text", "")))
        text.setWordWrap(True)
        layout.addWidget(text)
        for attachment in post.get("attachments", []):
            self._add_attachment(layout, attachment)

    @staticmethod
    def _meme_label(meme: str, asset_path: Path | None) -> QLabel:
        label = _label(f"[{meme}]")
        label.setObjectName("meme-placeholder")
        if asset_path is None:
            return label
        if asset_path.suffix.lower() == ".gif":
            if check_image_limits(asset_path) is None:
                _start_movie(label, asset_path)
            return label
        image, _error = read_preview(asset_path, _IMG_MAX)
        if image is not None:
            label.setPixmap(QPixmap.fromImage(image).scaled(
                _IMG_MAX, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
            label.setText("")
        return label

    def _add_attachment(self, layout: QVBoxLayout, attachment: dict) -> None:
        att_id = attachment["id"]
        if attachment.get("kind") == "image":
            widget = _label("Loading image…")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setMinimumHeight(60)
        else:
            widget = QToolButton()
            name = str(attachment.get("name", "file"))  # '&' is a QToolButton mnemonic
            widget.setText(
                f"📎 {name.replace('&', '&&')} ({human_size(attachment['size'])})"
            )
        widget.setProperty("attachment_id", att_id)
        layout.addWidget(widget)
        self._attachments[att_id] = widget

    def attachment_ready(self, att_id: str, path: Path) -> None:
        widget = self._attachments.get(att_id)
        if widget is None:
            return
        if isinstance(widget, QLabel):
            image, error = read_preview(path, _IMG_MAX)
            if image is not None:
                widget.setPixmap(QPixmap.fromImage(image))
                widget.setText("")
            else:
                widget.setText(error or "Cannot display image")
            widget.mousePressEvent = lambda _event, p=str(path): self.open_file_requested.emit(p)
        else:
            widget.clicked.connect(
                lambda _checked=False, p=str(path): self.open_file_requested.emit(p)
            )

    def attachment_failed(self, att_id: str, message: str) -> None:
        widget = self._attachments.get(att_id)
        if isinstance(widget, QToolButton):
            message = message.replace("&", "&&")
        if widget is not None:
            widget.setText(f"Download failed — {message}")
