from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pyside_gui.expression_widget import ExpressionWidget
from tui.utils import _system_breakdown


def _path_tail(path: Path | str, max_chars: int = 30) -> str:
    s = str(path)
    return s if len(s) <= max_chars else "..." + s[-(max_chars - 1):]


_STATUS_DOTS = {
    "running": ("●", "#a6e3a1", "running"),
    "paused":  ("⏸", "#f9e2af", "paused"),
    "idle":    ("○", "#6c7086", "idle"),
}

_SIDEBAR_CSS = """
QWidget#right-sidebar {
    background: #1e1e2e;
    border-left: 1px solid #45475a;
}
QLabel {
    color: #cdd6f4;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
}
QLabel#expression-image {
    color: #89b4fa;
    font-size: 11px;
    padding: 4px;
}
QLabel#expression-caption {
    color: #6c7086;
    font-size: 11px;
    padding-bottom: 4px;
}
QLabel#status-label { font-weight: bold; }
QLabel#model-label {
    font-weight: bold;
    font-size: 13px;
    font-family: 'Segoe UI', system-ui, sans-serif;
}
QLabel#section-header {
    color: #6c7086;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding-top: 8px;
}
"""


class RightSidebar(QScrollArea):
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
        self._subtasks: list[dict] = []
        self._plan_title = ""

        self.setObjectName("right-sidebar")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self.setStyleSheet(_SIDEBAR_CSS)

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(8, 8, 8, 8)

        self.expression_widget = ExpressionWidget(
            self._dagi_root / ".dagi" / "emotes"
        )
        self._layout.addWidget(self.expression_widget)

        # Status
        self._status_label = QLabel()
        self._status_label.setObjectName("status-label")
        self._layout.addWidget(self._status_label)

        # Model
        self._model_label = QLabel(model_name)
        self._model_label.setObjectName("model-label")
        self._layout.addWidget(self._model_label)

        # Paths
        self._paths_label = QLabel()
        self._layout.addWidget(self._paths_label)

        # Tokens header
        tok_header = QLabel("TOKENS")
        tok_header.setObjectName("section-header")
        self._layout.addWidget(tok_header)
        self._tokens_label = QLabel()
        self._layout.addWidget(self._tokens_label)

        # Context header
        ctx_header = QLabel("CONTEXT")
        ctx_header.setObjectName("section-header")
        self._layout.addWidget(ctx_header)
        self._context_label = QLabel()
        self._layout.addWidget(self._context_label)

        # Plan header
        plan_header = QLabel("PLAN")
        plan_header.setObjectName("section-header")
        self._layout.addWidget(plan_header)
        self._plan_label = QLabel()
        self._layout.addWidget(self._plan_label)

        self._layout.addStretch()
        self.setWidget(container)
        self._refresh_all()

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

    def update_plan(
        self, subtasks: list[dict], title: str = ""
    ) -> None:
        self._subtasks = subtasks
        self._plan_title = title
        self._refresh_plan()

    def _refresh_all(self) -> None:
        self._refresh_status()
        self._refresh_paths()
        self._refresh_tokens()
        self._refresh_context()
        self._refresh_plan()

    def _refresh_status(self) -> None:
        dot, colour, label = _STATUS_DOTS.get(
            self._status, ("○", "#6c7086", "idle")
        )
        self._status_label.setText(
            f'<span style="color:{colour}">{dot} {label}</span>'
        )

    def _refresh_paths(self) -> None:
        lines = [f"{'cwd':<4}{_path_tail(self._project_path)}"]
        lines.append(f"{'app':<4}{_path_tail(self._dagi_root)}")
        if self._memory_root:
            lines.append(f"{'mem':<4}{_path_tail(self._memory_root)}")
        self._paths_label.setText("\n".join(lines))

    def _refresh_tokens(self) -> None:
        cost = (
            f"${self._cost:.5f}" if self._cost is not None
            else "$—"
        )
        parts = [
            f"{'in':<6}~{self._input_tok:>8,}",
            f"{'out':<6}~{self._output_tok:>8,}",
        ]
        if self._thinking_tok:
            parts.append(f"{'think':<6}~{self._thinking_tok:>8,}")
        if self._cached_tok:
            parts.append(f"{'cache':<6}~{self._cached_tok:>8,}")
        parts.append(cost)
        self._tokens_label.setText("\n".join(parts))

    def _refresh_context(self) -> None:
        W = self._context_window
        sys_parts = _system_breakdown(
            self._dagi_root, self._project_path
        )

        def pct(n: int) -> str:
            return f"{n / W * 100:.0f}%" if W else "—"

        lines: list[str] = []
        for key in ("sys-prompt", "dagi/ag", "proj/ag"):
            n = sys_parts.get(key, 0)
            lines.append(f"{key:<11}~{n:>6,} {pct(n):>3}")

        for key in ("summary", "user", "assistant", "tools"):
            n = self._buckets.get(key, 0)
            lines.append(f"{key:<11}~{n:>6,} {pct(n):>3}")

        res = self._reserve_tokens
        lines.append(f"{'reserve':<11}~{res:>6,} {pct(res):>3}")

        total = sum(sys_parts.values()) + sum(
            self._buckets.values()
        ) + res
        usage = total / W if W else 0
        lines.append(f"{'total':<11}~{total:>6,} {usage*100:.0f}%")
        self._context_label.setText("\n".join(lines))

    def _refresh_plan(self) -> None:
        if not self._subtasks:
            self._plan_label.setText("")
            return
        icons = {
            "pending": "[ ]", "in_progress": "[~]",
            "complete": "[x]", "failed": "[!]",
        }
        lines: list[str] = []
        if self._plan_title:
            lines.append(self._plan_title)
        for sub in self._subtasks:
            icon = icons.get(sub["status"], "[?]")
            lines.append(f"{icon} {sub['name']}")
        self._plan_label.setText("\n".join(lines))
