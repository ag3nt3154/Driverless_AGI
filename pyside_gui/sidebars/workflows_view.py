"""pyside_gui/sidebars/workflows_view.py — Workflows rail view (Subtask 18, D15).

Lists the project's RPA workflows (``rpa.api.list_workflows``) with a status
chip per row; selecting one loads its detail (``rpa.api.workflow_detail``):
a lifecycle stepper (draft -> verified -> approved), a steps table, params,
secret *names* (never values) and the last run. One primary button whose
label follows the workflow's state (see :func:`primary_action`); clicking it
emits ``action_requested`` with the exact chat message the Decision in
plan.md's Subtask 18 section specifies — this view never calls the CLI or
``rpa`` functions itself, only asks the active agent session to run its
``rpa_*`` tools, so there is exactly one process touching the desktop/browser
drivers.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from pyside_gui.icons import icon
from pyside_gui.theme import qss, solid

from rpa import RpaError
from rpa.api import Detail, list_workflows, workflow_detail

__all__ = ["WorkflowsView", "primary_action"]

_STATUS_COLORS = {
    "draft": solid("fg_secondary"),
    "approved": solid("success"),
    "degraded": solid("warn"),
    "halted": solid("danger"),
    "cancelled": solid("fg_tertiary"),
    "error": solid("danger"),
}
_UNKNOWN_STATUS_COLOR = solid("fg_secondary")
_PLACEHOLDER_TEXT = "No workflows yet"

_LIST_CSS = qss("""
QListWidget {
    background: @app_bg; color: @fg; border: none; outline: none;
    font-family: @font_ui; font-size: 13px; padding: 0 6px;
}
QListWidget::item { border: none; border-radius: 8px; padding: 4px 2px; }
QListWidget::item:hover { background: @hover_bg; }
QListWidget::item:selected { background: @active_bg; color: @fg; }
""")

_TABLE_CSS = qss("""
QTableWidget {
    background: @app_bg; color: @fg; border: 1px solid @border; gridline-color: @border;
    font-family: @font_ui; font-size: 12px;
}
QHeaderView::section {
    background: @app_bg; color: @fg_secondary; border: none; border-bottom: 1px solid @border;
    padding: 2px 4px;
}
""")

_STEPPER_STAGES = ("draft", "verified", "approved")


def _stage(detail: Detail) -> str:
    """Which lifecycle stage ``detail`` is at, independent of run health."""
    if detail.approval_status == "approved":
        return "approved"
    if detail.verified:
        return "verified"
    return "draft"


def primary_action(detail: Detail) -> tuple[str, str]:
    """(button label, chat message) for ``detail``'s current state.

    A halted last run always wins (Repair), whatever the approval stage;
    otherwise the stage decides: draft -> Verify run, verified -> Approve,
    approved -> Run.
    """
    if detail.display_status == "halted":
        return "Repair", f"Repair workflow `{detail.name}` (rpa_repair)."
    stage = _stage(detail)
    if stage == "approved":
        return "Run", f"Run workflow `{detail.name}` (rpa_run)."
    if stage == "verified":
        return "Approve", f"Approve workflow `{detail.name}` (rpa_approve)."
    return "Verify run", f"Verify workflow `{detail.name}` (rpa_run with verify=true)."


def _plain(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class WorkflowsView(QWidget):
    """Left-rail panel: workflow list + detail, shown only when `computer_use` is on."""

    action_requested = Signal(str)

    _NAME_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self) -> None:
        super().__init__()
        self._project_path: Path | None = None
        self._detail: Detail | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(8, 8, 8, 0)
        header = _plain("WORKFLOWS")
        header.setStyleSheet(qss("color: @fg_secondary; font-weight: bold;"))
        header_row.addWidget(header, 1)
        self._refresh_button = QToolButton()
        self._refresh_button.setIcon(icon("history", 16))
        self._refresh_button.setToolTip("Refresh")
        self._refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(self._refresh_button)
        outer.addLayout(header_row)

        self._list = QListWidget()
        self._list.setStyleSheet(_LIST_CSS)
        self._list.setMaximumHeight(160)
        self._list.itemClicked.connect(self._on_selected)
        outer.addWidget(self._list)

        self._detail_title = _plain("")
        self._detail_title.setStyleSheet(qss("color: @fg; font-weight: bold; padding: 4px 8px;"))
        outer.addWidget(self._detail_title)

        self._stepper_label = _plain("")
        self._stepper_label.setStyleSheet(qss("color: @fg_secondary; padding: 0 8px;"))
        outer.addWidget(self._stepper_label)

        self._steps_table = QTableWidget(0, 4)
        self._steps_table.setHorizontalHeaderLabels(["id", "act", "confirm", "last rung"])
        self._steps_table.setStyleSheet(_TABLE_CSS)
        self._steps_table.verticalHeader().setVisible(False)
        self._steps_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        outer.addWidget(self._steps_table, 1)

        self._params_label = _plain("")
        self._params_label.setStyleSheet(qss("color: @fg_secondary; padding: 2px 8px;"))
        outer.addWidget(self._params_label)

        self._secrets_label = _plain("")
        self._secrets_label.setStyleSheet(qss("color: @fg_secondary; padding: 2px 8px;"))
        outer.addWidget(self._secrets_label)

        self._last_run_label = _plain("")
        self._last_run_label.setStyleSheet(qss("color: @fg_secondary; padding: 2px 8px 6px;"))
        outer.addWidget(self._last_run_label)

        self._primary_button = QPushButton("")
        self._primary_button.setEnabled(False)
        self._primary_button.clicked.connect(self._on_primary_clicked)
        outer.addWidget(self._primary_button)

        self._show_placeholder()

    # ── data plumbing ───────────────────────────────────────────────────────────────

    def set_project(self, path: Path) -> None:
        self._project_path = Path(path)
        self._detail = None

    def refresh(self) -> None:
        """Reload the workflow list from disk; keeps the selection when still present."""
        if self._project_path is None:
            return
        current = self._detail.name if self._detail is not None else None
        summaries = list_workflows(self._project_path)
        self._list.clear()
        if not summaries:
            self._show_placeholder()
            self._clear_detail()
            return
        selected_item = None
        for summary in summaries:
            item = QListWidgetItem(f"{summary.name} — {summary.display_status}")
            colour = _STATUS_COLORS.get(summary.display_status, _UNKNOWN_STATUS_COLOR)
            item.setForeground(QBrush(QColor(colour)))
            item.setData(self._NAME_ROLE, summary.name)
            self._list.addItem(item)
            if summary.name == current:
                selected_item = item
        if selected_item is not None:
            self._list.setCurrentItem(selected_item)
            self._load_detail(current)
        else:
            self._clear_detail()

    def _on_selected(self, item: QListWidgetItem) -> None:
        name = item.data(self._NAME_ROLE)
        if name is not None:
            self._load_detail(name)

    def _load_detail(self, name: str) -> None:
        if self._project_path is None:
            return
        try:
            detail = workflow_detail(self._project_path, name)
        except RpaError as exc:  # a corrupt workflow.yaml: show why, offer no action
            self._clear_detail()
            self._detail_title.setText(name)
            self._last_run_label.setText(str(exc))
            return
        self._detail = detail
        self._render_detail(detail)

    # ── rendering ────────────────────────────────────────────────────────────────────

    def _show_placeholder(self) -> None:
        item = QListWidgetItem(_PLACEHOLDER_TEXT)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._list.addItem(item)

    def _clear_detail(self) -> None:
        self._detail = None
        self._detail_title.setText("")
        self._stepper_label.setText("")
        self._steps_table.setRowCount(0)
        self._params_label.setText("")
        self._secrets_label.setText("")
        self._last_run_label.setText("")
        self._primary_button.setText("")
        self._primary_button.setEnabled(False)

    def _render_detail(self, detail: Detail) -> None:
        self._detail_title.setText(detail.name)
        stage = _stage(detail)
        self._stepper_label.setText(
            " -> ".join(
                f"[{s}]" if s == stage else s for s in _STEPPER_STAGES
            )
        )
        self._steps_table.setRowCount(len(detail.steps))
        for row, step in enumerate(detail.steps):
            for col, text in enumerate((
                step.id, step.act or "", step.confirm or "",
                "" if step.last_rung is None else str(step.last_rung),
            )):
                self._steps_table.setItem(row, col, QTableWidgetItem(text))
        if detail.params:
            self._params_label.setText(
                "Params: " + ", ".join(f"{n}={d!r}" for n, d in detail.params)
            )
        else:
            self._params_label.setText("Params: none")
        if detail.secret_names:
            self._secrets_label.setText("Secrets: " + ", ".join(detail.secret_names))
        else:
            self._secrets_label.setText("Secrets: none")
        if detail.last_run:
            last = detail.last_run
            self._last_run_label.setText(f"Last run: {last.get('status')} ({last.get('reason') or 'ok'})")
        else:
            self._last_run_label.setText("Last run: none")
        label, _ = primary_action(detail)
        self._primary_button.setText(label)
        self._primary_button.setEnabled(True)

    def _on_primary_clicked(self) -> None:
        if self._detail is None:
            return
        _, message = primary_action(self._detail)
        self.action_requested.emit(message)
