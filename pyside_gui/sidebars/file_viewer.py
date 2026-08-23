from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.markdown_renderer import render_markdown

_MAX_FILE_SIZE = 500_000  # 500 KB

_CSS = """
QWidget#file-viewer {
    background: #1e1e2e;
}
QLabel#file-path-label {
    color: #6c7086;
    font-size: 11px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    padding: 4px 8px;
    background: #181825;
    border-bottom: 1px solid #45475a;
}
QPlainTextEdit {
    background: #1e1e2e;
    color: #cdd6f4;
    border: none;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: #1a3a5c;
}
"""

_MD_PAGE = """<!DOCTYPE html>
<html><head><style>
:root {{
    --bg: #1e1e2e; --text: #cdd6f4; --surface: #282839;
    --border: #45475a; --accent: #89b4fa;
    --font-ui: 'Segoe UI', system-ui, sans-serif;
    --font-mono: 'Cascadia Code', 'Consolas', monospace;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: var(--bg); color: var(--text);
    font-family: var(--font-ui); font-size: 13px;
    line-height: 1.6; padding: 12px;
    word-wrap: break-word; overflow-wrap: break-word;
}}
h1, h2, h3 {{ color: var(--accent); margin: 12px 0 6px; }}
code {{
    background: var(--surface); padding: 1px 4px;
    border-radius: 3px; font-family: var(--font-mono);
    font-size: 12px;
}}
pre {{
    background: var(--surface); padding: 10px;
    border-radius: 6px; overflow-x: auto;
    border: 1px solid var(--border); margin: 8px 0;
    white-space: pre-wrap; word-wrap: break-word;
}}
pre code {{ background: none; padding: 0; }}
table {{
    border-collapse: collapse; width: 100%; margin: 8px 0;
}}
th, td {{
    border: 1px solid var(--border); padding: 6px 10px;
    text-align: left; word-wrap: break-word;
}}
th {{ background: var(--surface); }}
a {{ color: var(--accent); }}
blockquote {{
    border-left: 3px solid var(--accent);
    padding-left: 12px; color: #a6adc8; margin: 8px 0;
}}
ul, ol {{ padding-left: 24px; margin: 6px 0; }}
li {{ margin: 2px 0; }}
ul {{ list-style-type: disc; }}
ol {{ list-style-type: decimal; }}
ul ul {{ list-style-type: circle; margin: 2px 0; }}
</style></head><body>{body}</body></html>"""


class _TextEditor(QPlainTextEdit):

    def set_line_number_area(self, area: "LineNumberArea") -> None:
        self._line_numbers = area
        self._reposition_area()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._reposition_area()

    def _reposition_area(self) -> None:
        if not hasattr(self, "_line_numbers"):
            return
        cr = self.contentsRect()
        w = self._line_numbers._area_width()
        self._line_numbers.setGeometry(
            cr.left(), cr.top(), w, cr.height()
        )


class LineNumberArea(QWidget):
    def __init__(self, editor: QPlainTextEdit) -> None:
        super().__init__(editor)
        self._editor = editor
        editor.blockCountChanged.connect(self._update_width)
        editor.updateRequest.connect(self._on_update)
        self._update_width()

    def sizeHint(self) -> QSize:
        return QSize(self._area_width(), 0)

    def _area_width(self) -> int:
        digits = max(1, len(str(self._editor.blockCount())))
        char_w = self._editor.fontMetrics().horizontalAdvance("9")
        return 10 + char_w * digits

    def _update_width(self) -> None:
        w = self._area_width()
        self._editor.setViewportMargins(w, 0, 0, 0)
        self.setFixedWidth(w)

    def _on_update(self, rect: QRect, dy: int) -> None:
        if dy:
            self.scroll(0, dy)
        else:
            self.update(0, rect.y(), self.width(), rect.height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#181825"))
        block = self._editor.firstVisibleBlock()
        geo = self._editor.blockBoundingGeometry(block)
        top = round(
            geo.translated(self._editor.contentOffset()).top()
        )
        bottom = top + round(
            self._editor.blockBoundingRect(block).height()
        )
        line_h = self._editor.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#6c7086"))
                painter.drawText(
                    0, top, self.width() - 4, line_h,
                    Qt.AlignmentFlag.AlignRight,
                    str(block.blockNumber() + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(
                self._editor.blockBoundingRect(block).height()
            )
        painter.end()


class FileViewerView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("file-viewer")
        self.setStyleSheet(_CSS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._path_label = QLabel("")
        self._path_label.setObjectName("file-path-label")
        self._path_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._path_label)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._text_edit = _TextEditor()
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        font = QFont("Cascadia Code", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._text_edit.setFont(font)
        self._line_numbers = LineNumberArea(self._text_edit)
        self._text_edit.set_line_number_area(self._line_numbers)
        self._stack.addWidget(self._text_edit)

        self._md_view = QWebEngineView()
        self._stack.addWidget(self._md_view)

    def open_file(self, path: str, project_root: Path) -> None:
        file_path = Path(path)
        try:
            rel = file_path.relative_to(project_root)
        except ValueError:
            rel = file_path
        self._path_label.setText(str(rel))

        try:
            size = file_path.stat().st_size
        except OSError as exc:
            self._stack.setCurrentIndex(0)
            self._text_edit.setPlainText(f"Cannot open file: {exc}")
            return

        if size > _MAX_FILE_SIZE:
            self._stack.setCurrentIndex(0)
            self._text_edit.setPlainText(
                f"File too large to display ({size:,} bytes, "
                f"limit {_MAX_FILE_SIZE:,})"
            )
            return

        try:
            content = file_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError as exc:
            self._stack.setCurrentIndex(0)
            self._text_edit.setPlainText(f"Cannot read file: {exc}")
            return

        if file_path.suffix.lower() == ".md":
            html = render_markdown(content)
            self._md_view.setHtml(_MD_PAGE.format(body=html))
            self._stack.setCurrentIndex(1)
        else:
            self._text_edit.setPlainText(content)
            self._stack.setCurrentIndex(0)

    def clear(self) -> None:
        self._path_label.setText("")
        self._text_edit.setPlainText("")
        self._md_view.setHtml("")
        self._stack.setCurrentIndex(0)
