from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.expression_widget import ExpressionWidget
from pyside_gui.icons import icon
from pyside_gui.theme import SCROLLBAR_QSS, qss
from tui.utils import _system_breakdown


def _path_tail(path: Path | str, max_chars: int = 24) -> str:
    s = str(path)
    return s if len(s) <= max_chars else "…" + s[-(max_chars - 1):]


# status -> (label, qss colour token, pill background)
_STATUS = {
    "running":    ("Running", "success", "rgba(110, 205, 140, 0.14)"),
    "paused":     ("Paused", "warn", "rgba(255, 180, 96, 0.14)"),
    "compacting": ("Compacting", "link", "rgba(150, 170, 255, 0.14)"),
    "idle":       ("Idle", "fg_secondary", "rgba(238, 237, 250, 0.07)"),
}

_SIDEBAR_CSS = SCROLLBAR_QSS + qss("""
QWidget#right-sidebar {
    background: @app_bg;
    border-left: 1px solid @border;
}
QLabel {
    color: @fg;
    font-family: @font_ui;
    font-size: 13px;
}
QLabel#expression-image {
    color: @fg_secondary;
    font-family: @font_mono;
    font-size: 11px;
    padding: 4px;
}
QLabel#expression-caption {
    color: @fg_tertiary;
    font-size: 11px;
    padding-bottom: 2px;
}
QLabel#status-label {
    font-size: 12px;
    font-weight: 600;
    border-radius: 10px;
    padding: 2px 10px;
}
QLabel#model-label {
    color: @fg;
    font-size: 14px;
    font-weight: 600;
    padding-top: 4px;
}
QLabel#section-header {
    color: @fg_tertiary;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.8px;
    padding-top: 10px;
    padding-bottom: 1px;
}
QLabel[role="key"] { color: @fg_secondary; font-size: 12px; }
QLabel[role="path"] { color: @fg; font-size: 12px; }
QLabel[role="tokens"] { color: @tokens_fg; font-size: 12px; }
QLabel[role="context"] { color: @context_fg; font-size: 12px; }
QLabel[role="pct"] { color: @fg_tertiary; font-size: 11.5px; }
QLabel[role="total"] { color: @fg; font-size: 12px; font-weight: 600; }
QProgressBar#context-bar {
    background-color: @active_bg;
    border: 1px solid @active_bg;
    border-radius: 3px;
}
QProgressBar#context-bar::chunk { background: @context_fg; border-radius: 3px; }
QPushButton#scroll-to-bottom-button {
    background: @popover_bg;
    border: 1px solid @border;
    border-radius: 8px;
    color: @fg_secondary;
    font-family: @font_ui;
    font-size: 12.5px;
    padding: 7px;
}
QPushButton#scroll-to-bottom-button:hover { background: @hover_bg; color: @fg; }
""")


class _Rows(QWidget):
    """Key / value(s) rows: dim labels on the left, values on the right."""

    def __init__(self, value_role: str, columns: int = 1) -> None:
        super().__init__()
        self._value_role = value_role
        self._columns = columns
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(0)
        self._grid.setColumnStretch(0, 1)
        self._cells: list[list[QLabel]] = []

    def set_rows(self, rows: list[tuple]) -> None:
        """Each row is ``(key, value, *extra_values)``; a ``(text, role)``
        tuple in place of a string overrides that cell's role."""
        while len(self._cells) > len(rows):
            for label in self._cells.pop():
                label.deleteLater()
        for r, row in enumerate(rows):
            if r == len(self._cells):
                cells = [QLabel() for _ in range(1 + self._columns)]
                for c, label in enumerate(cells):
                    align = Qt.AlignmentFlag.AlignLeft if c == 0 else Qt.AlignmentFlag.AlignRight
                    label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
                    self._grid.addWidget(label, r, c)
                self._cells.append(cells)
            for c, label in enumerate(self._cells[r]):
                value = row[c] if c < len(row) else ""
                text, role = value if isinstance(value, tuple) else (
                    value, "key" if c == 0 else (self._value_role if c == 1 else "pct")
                )
                if label.property("role") != role:
                    label.setProperty("role", role)
                    label.style().unpolish(label)
                    label.style().polish(label)
                label.setText(text)


class RightSidebar(QScrollArea):
    scroll_to_bottom_requested = Signal()

    def __init__(
        self,
        model_name: str,
        context_window: int,
        reserve_tokens: int,
        dagi_root: Path,
        project_path: Path,
        memory_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._model_name = model_name
        self._context_window = context_window
        self._reserve_tokens = reserve_tokens
        self._dagi_root = dagi_root
        self._project_path = project_path
        self._memory_root = memory_root
        self._status = "idle"
        self._input_tok = 0
        self._output_tok = 0
        self._thinking_tok = 0
        self._cached_tok = 0
        self._cost: float | None = None
        self._buckets: dict[str, int] = {}

        self.setObjectName("right-sidebar")
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setMinimumWidth(180)
        self.setMaximumWidth(260)
        self.setStyleSheet(_SIDEBAR_CSS)

        container = QWidget()
        container.setObjectName("right-sidebar")
        self.viewport().setStyleSheet(qss("background: @app_bg;"))
        self._layout = QVBoxLayout(container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(14, 10, 14, 12)

        self.expression_widget = ExpressionWidget(
            self._dagi_root / ".dagi" / "emotes"
        )
        self.expression_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._layout.addWidget(self.expression_widget)

        # Status pill
        self._status_label = QLabel()
        self._status_label.setObjectName("status-label")
        self._status_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._layout.addWidget(self._status_label)

        # Model + paths
        self._model_label = QLabel(model_name)
        self._model_label.setObjectName("model-label")
        self._model_label.setWordWrap(True)
        self._layout.addWidget(self._model_label)
        self._paths = _Rows("path")
        self._layout.addWidget(self._paths)

        # Tokens
        self._layout.addWidget(self._header("TOKENS"))
        self._tokens = _Rows("tokens")
        self._layout.addWidget(self._tokens)

        # Context
        self._layout.addWidget(self._header("CONTEXT"))
        self._context_bar = QProgressBar()
        self._context_bar.setObjectName("context-bar")
        self._context_bar.setTextVisible(False)
        self._context_bar.setFixedHeight(5)
        self._context_bar.setContentsMargins(4, 0, 0, 0)
        self._context_bar.setRange(0, 1000)
        self._layout.addWidget(self._context_bar)
        self._layout.addSpacing(4)
        self._context = _Rows("context", columns=2)
        self._layout.addWidget(self._context)

        self._layout.addStretch()
        self._scroll_to_bottom_button = QPushButton("Scroll to bottom")
        self._scroll_to_bottom_button.setObjectName("scroll-to-bottom-button")
        self._scroll_to_bottom_button.setIcon(icon("arrow_down", 14))
        self._scroll_to_bottom_button.setIconSize(QSize(14, 14))
        self._scroll_to_bottom_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scroll_to_bottom_button.clicked.connect(
            lambda _checked=False: self.scroll_to_bottom_requested.emit()
        )
        self._layout.addWidget(self._scroll_to_bottom_button)
        self.setWidget(container)
        self._refresh_all()

    @staticmethod
    def _header(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section-header")
        return label

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh_status()

    def update_model(self, name: str) -> None:
        self._model_name = name
        self._model_label.setText(name)

    def update_stats(
        self, inp: int, out: int, cost: float | None,
        thinking: int, cached: int = 0,
    ) -> None:
        self._input_tok = inp
        self._output_tok = out
        self._cost = cost
        self._thinking_tok = thinking
        self._cached_tok = cached
        self._refresh_tokens()

    def update_context(self, buckets: dict) -> None:
        self._buckets = dict(buckets)
        self._refresh_context()

    def set_project_path(self, path: Path) -> None:
        self._project_path = path
        self._refresh_paths()

    def _refresh_all(self) -> None:
        self._refresh_status()
        self._refresh_paths()
        self._refresh_tokens()
        self._refresh_context()

    def _refresh_status(self) -> None:
        label, token, pill = _STATUS.get(self._status, _STATUS["idle"])
        self._status_label.setText(f"●  {label}")
        self._status_label.setStyleSheet(
            qss(f"color: @{token}; background: {pill};")
        )

    def _refresh_paths(self) -> None:
        rows = [("cwd", self._project_path), ("app", self._dagi_root)]
        if self._memory_root:
            rows.append(("mem", self._memory_root))
        self._paths.set_rows([(key, _path_tail(path)) for key, path in rows])
        for (key, path), cells in zip(rows, self._paths._cells):
            cells[1].setToolTip(str(path))

    def _refresh_tokens(self) -> None:
        rows = [("Input", f"{self._input_tok:,}"), ("Output", f"{self._output_tok:,}")]
        if self._thinking_tok:
            rows.append(("Thinking", f"{self._thinking_tok:,}"))
        if self._cached_tok:
            rows.append(("Cached", f"{self._cached_tok:,}"))
        cost = f"${self._cost:.4f}" if self._cost is not None else "—"
        rows.append(("Cost", cost))
        self._tokens.set_rows(rows)

    def _refresh_context(self) -> None:
        W = self._context_window
        sys_parts = _system_breakdown(
            self._dagi_root, self._project_path
        )

        def pct(n: int) -> str:
            return f"{n / W * 100:.0f}%" if W else "—"

        names = {
            "sys-prompt": "System prompt", "dagi/ag": "DAGI AGENTS.md",
            "proj/ag": "Project AGENTS.md", "summary": "Summary", "user": "User",
            "assistant": "Assistant", "tools": "Tools",
        }
        rows: list[tuple] = []
        for key in ("sys-prompt", "dagi/ag", "proj/ag"):
            n = sys_parts.get(key, 0)
            rows.append((names[key], f"{n:,}", pct(n)))
        for key in ("summary", "user", "assistant", "tools"):
            n = self._buckets.get(key, 0)
            rows.append((names[key], f"{n:,}", pct(n)))
        res = self._reserve_tokens
        rows.append(("Reserve", f"{res:,}", pct(res)))

        total = sum(sys_parts.values()) + sum(
            self._buckets.values()
        ) + res
        usage = total / W if W else 0
        rows.append((("Total", "total"), (f"{total:,}", "total"), (f"{usage*100:.0f}%", "total")))
        self._context.set_rows(rows)
        self._context_bar.setValue(round(min(usage, 1.0) * 1000))
        self._context_bar.setToolTip(f"{total:,} of {W:,} tokens ({usage*100:.0f}%)")
