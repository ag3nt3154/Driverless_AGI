from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QSize, Slot
from PySide6.QtGui import QFont, QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_IMG_MAX = QSize(160, 140)

_CARD_CSS = """
QWidget#board-card {
    background: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
}
"""

_HEADER_CSS = """
QLabel#board-header {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 0 4px 0;
}
"""


@dataclass
class BoardPost:
    author: str
    meme_name: str
    asset_path: Path
    text: str
    timestamp: datetime


class _PostCard(QWidget):
    def __init__(self, post: BoardPost) -> None:
        super().__init__()
        self.setObjectName("board-card")
        self.setStyleSheet(_CARD_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        author_label = QLabel(post.author)
        author_label.setStyleSheet(
            "color: #89b4fa; font-size: 11px; font-weight: bold;"
            "font-family: 'Segoe UI', system-ui, sans-serif;"
        )
        header_row.addWidget(author_label)
        header_row.addStretch()

        ts_label = QLabel(post.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        ts_label.setStyleSheet("color: #6c7086; font-size: 10px;")
        header_row.addWidget(ts_label)

        layout.addLayout(header_row)

        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: #45475a;")
        layout.addWidget(divider)

        img_label = QLabel()
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setMinimumHeight(80)
        suffix = post.asset_path.suffix.lower()
        if suffix == ".gif":
            movie = QMovie(str(post.asset_path))
            if movie.isValid():
                natural = QImageReader(str(post.asset_path)).size()
                if natural.isValid() and not natural.isEmpty():
                    scaled = natural.scaled(_IMG_MAX, Qt.AspectRatioMode.KeepAspectRatio)
                else:
                    scaled = _IMG_MAX
                movie.setScaledSize(scaled)
                movie.setParent(img_label)
                img_label.setMovie(movie)
                movie.start()
            else:
                img_label.setText(f"[{post.meme_name}]")
        else:
            pixmap = QPixmap(str(post.asset_path))
            if not pixmap.isNull():
                img_label.setPixmap(
                    pixmap.scaled(
                        _IMG_MAX,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                img_label.setText(f"[{post.meme_name}]")

        layout.addWidget(img_label)

        text_label = QLabel(post.text)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(
            "color: #cdd6f4; font-size: 12px; padding: 4px 0;"
            "font-family: 'Segoe UI', system-ui, sans-serif;"
        )
        layout.addWidget(text_label)


class MessageBoardView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setStyleSheet("background: #1e1e2e;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QLabel("MESSAGE BOARD")
        header.setObjectName("board-header")
        header.setStyleSheet(_HEADER_CSS)
        header.setContentsMargins(8, 8, 8, 4)
        outer.addWidget(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: #1e1e2e; }"
        )
        self._scroll.viewport().setStyleSheet("background: #1e1e2e;")

        self._container = QWidget()
        self._container.setStyleSheet("background: #1e1e2e;")
        self._posts_layout = QVBoxLayout(self._container)
        self._posts_layout.setContentsMargins(8, 4, 8, 8)
        self._posts_layout.setSpacing(12)
        self._posts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll, stretch=1)

    @Slot(str, str, str, str, str)
    def add_post(self, author: str, meme_name: str, asset_path: str, text: str, timestamp: str) -> None:
        post = BoardPost(
            author=author,
            meme_name=meme_name,
            asset_path=Path(asset_path),
            text=text,
            timestamp=datetime.fromisoformat(timestamp),
        )
        card = _PostCard(post)
        self._posts_layout.insertWidget(0, card)
        self._scroll.verticalScrollBar().setValue(0)
