from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QPixmap, QTextCursor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.markdown_renderer import render_markdown_with_source_lines
from pyside_gui.image_preview import MAX_IMAGE_BYTES, read_preview
from pyside_gui.theme import qcolor, qss


_MAX_FILE_SIZE = 500_000  # 500 KB
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})
_MIN_IMAGE_BOUND = QSize(1600, 1200)

_CSS = qss("""
QWidget#file-viewer {
    background: @app_bg;
}
QLabel#file-path-label {
    color: @fg_secondary;
    font-size: 11px;
    font-family: @font_mono;
    padding: 4px 8px;
    background: @app_bg;
    border-bottom: 1px solid @border;
}
QPlainTextEdit {
    background: @app_bg;
    color: @fg;
    border: none;
    font-family: @font_mono;
    font-size: 12px;
    selection-background-color: @selection;
}
""")

_MD_PAGE = qss("""<!DOCTYPE html>
<html><head><style>
html {{ color-scheme: dark; }}
:root {{
    --bg: @app_bg; --text: @fg; --surface: @popover_bg;
    --border: @border; --accent: @fg; --highlight: @active_bg;
    --gutter: @app_bg; --line-num: @fg_tertiary; --link: @link;
    --dim: @fg_secondary;
    --font-ui: @font_ui;
    --font-mono: @font_mono;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: var(--bg); color: var(--text);
    font-family: var(--font-ui); font-size: 13px;
    line-height: 1.6; padding: 12px 12px 12px 48px;
    word-wrap: break-word; overflow-wrap: break-word;
    position: relative;
}}
body > [data-source-line] {{
    position: relative;
}}
body > [data-source-line]::before {{
    content: attr(data-source-line);
    position: absolute;
    left: -40px;
    width: 32px;
    text-align: right;
    color: var(--line-num);
    font-family: var(--font-mono);
    font-size: 11px;
    line-height: inherit;
    pointer-events: none;
    user-select: none;
}}
.line-highlight {{
    background: var(--highlight) !important;
    border-radius: 3px;
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
a {{ color: var(--link); }}
blockquote {{
    border-left: 3px solid var(--border);
    padding-left: 12px; color: var(--dim); margin: 8px 0;
}}
ul, ol {{ padding-left: 24px; margin: 6px 0; }}
li {{ margin: 2px 0; }}
ul {{ list-style-type: disc; }}
ol {{ list-style-type: decimal; }}
ul ul {{ list-style-type: circle; margin: 2px 0; }}
</style>
<script>
function jumpToLine(line) {{
    var best = null;
    var bestLine = 0;
    document.querySelectorAll('[data-source-line]').forEach(function(el) {{
        var n = parseInt(el.getAttribute('data-source-line'), 10);
        if (n <= line && n > bestLine) {{
            bestLine = n;
            best = el;
        }}
    }});
    if (best) {{
        document.querySelectorAll('.line-highlight').forEach(function(el) {{
            el.classList.remove('line-highlight');
        }});
        best.classList.add('line-highlight');
        best.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
    }}
}}
</script>
</head><body>{body}</body></html>""")


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
        painter.fillRect(event.rect(), qcolor("app_bg"))
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
                painter.setPen(qcolor("fg_tertiary"))
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
        self._md_view.loadFinished.connect(self._on_md_loaded)
        self._pending_md_line: int | None = None
        self._stack.addWidget(self._md_view)

        self._image_view = QLabel()
        self._image_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_view.setTextFormat(Qt.TextFormat.PlainText)
        self._image_scroll = QScrollArea()
        self._image_scroll.setWidgetResizable(True)
        self._image_scroll.setWidget(self._image_view)
        self._stack.addWidget(self._image_scroll)

    def open_file(self, path: str, project_root: Path, line: int | None = None) -> None:
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

        if file_path.suffix.lower() in _IMAGE_SUFFIXES:
            self._open_image(file_path, size)
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
            html = render_markdown_with_source_lines(content)
            self._pending_md_line = line
            self._md_view.setHtml(_MD_PAGE.format(body=html))
            self._stack.setCurrentIndex(1)
        else:
            self._text_edit.setPlainText(content)
            self._stack.setCurrentIndex(0)
            if line is not None:
                QTimer.singleShot(0, lambda: self._jump_to_line(line))

    def _open_image(self, path: Path, size: int) -> None:
        if size > MAX_IMAGE_BYTES:
            self._show_image_error(f"Image too large to display ({size:,} bytes)")
            return
        image, error = read_preview(path, self._image_decode_bound())
        if image is None:
            self._show_image_error(error or "Cannot display image")
            return
        self._image_view.setText("")
        self._image_view.setPixmap(QPixmap.fromImage(image))
        self._stack.setCurrentWidget(self._image_scroll)

    def _image_decode_bound(self) -> QSize:
        """Fixed decode cap, independent of the panel's current width (it may widen later)."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        bound = screen.availableGeometry().size() if screen is not None else QSize()
        return bound.expandedTo(_MIN_IMAGE_BOUND)

    def _show_image_error(self, message: str) -> None:
        self._image_view.setPixmap(QPixmap())
        self._image_view.setText(message)
        self._stack.setCurrentWidget(self._image_scroll)

    def _on_md_loaded(self, ok: bool) -> None:
        if ok and self._pending_md_line is not None:
            line = self._pending_md_line
            self._pending_md_line = None
            self._md_view.page().runJavaScript(f"jumpToLine({line})")

    def _jump_to_line(self, line: int) -> None:
        block = self._text_edit.document().findBlockByLineNumber(line - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self._text_edit.setTextCursor(cursor)
        self._text_edit.centerCursor()
        sel = self._text_edit.ExtraSelection()
        sel.format.setBackground(qcolor("active_bg"))
        sel.format.setProperty(
            sel.format.Property.FullWidthSelection, True
        )
        sel.cursor = cursor
        self._text_edit.setExtraSelections([sel])

    def clear(self) -> None:
        self._path_label.setText("")
        self._text_edit.setPlainText("")
        self._md_view.setHtml("")
        self._image_view.setPixmap(QPixmap())
        self._image_view.setText("")
        self._stack.setCurrentIndex(0)
