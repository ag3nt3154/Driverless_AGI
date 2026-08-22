from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from agent.history import build_copyable_messages

_OVERLAY_CSS = """
QWidget#overlay-backdrop {
    background: rgba(0, 0, 0, 180);
}
QWidget#overlay-panel {
    background: #282839;
    border: 1px solid #45475a;
    border-radius: 12px;
    padding: 16px;
}
QLabel { color: #cdd6f4; font-size: 14px; }
QLabel#overlay-title {
    color: #94e2d5;
    font-weight: bold;
    font-size: 16px;
}
QLineEdit {
    background: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 8px;
    font-size: 14px;
}
QLineEdit:focus { border-color: #89b4fa; }
QPushButton {
    background: #89b4fa;
    color: #1e1e2e;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 14px;
}
QPushButton:hover { background: #74c7ec; }
QListWidget {
    background: #1e1e2e;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    font-size: 13px;
}
QListWidget::item { padding: 8px; }
QListWidget::item:hover { background: #313147; }
QListWidget::item:selected { background: #1a3a5c; }
"""


class AskUserDialog(QWidget):
    answered = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("overlay-backdrop")
        self.setStyleSheet(_OVERLAY_CSS)
        self.hide()

        self._event: threading.Event | None = None
        self._container: list | None = None
        self._timer: object = None  # reserved for future timeout countdown

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel = QWidget()
        panel.setObjectName("overlay-panel")
        panel.setFixedWidth(500)
        panel_layout = QVBoxLayout(panel)

        self._title = QLabel("Question from Dagi")
        self._title.setObjectName("overlay-title")
        panel_layout.addWidget(self._title)

        self._question_label = QLabel()
        self._question_label.setWordWrap(True)
        panel_layout.addWidget(self._question_label)

        self._options_list = QListWidget()
        self._options_list.setMaximumHeight(200)
        panel_layout.addWidget(self._options_list)

        self._timeout_label = QLabel()
        panel_layout.addWidget(self._timeout_label)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type your answer...")
        self._input.returnPressed.connect(self._submit)
        input_row.addWidget(self._input)

        submit_btn = QPushButton("Submit")
        submit_btn.clicked.connect(self._submit)
        input_row.addWidget(submit_btn)
        panel_layout.addLayout(input_row)

        layout.addWidget(panel)

    def show_question(
        self,
        question: str,
        options: list[dict],
        timeout: float | None,
        event: threading.Event,
        container: list,
    ) -> None:
        self._event = event
        self._container = container
        self._question_label.setText(question)
        self._options_list.clear()
        for i, opt in enumerate(options, 1):
            rec = " (recommended)" if opt.get("recommended") else ""
            label = f"{i}. {opt['label']}{rec}"
            desc = opt.get("description", "")
            if desc:
                label += f" — {desc}"
            self._options_list.addItem(label)
        self._options_list.setVisible(bool(options))
        if timeout:
            self._timeout_label.setText(
                f"Auto-selects in {int(timeout)}s"
            )
            self._timeout_label.show()
        else:
            self._timeout_label.hide()
        self._input.clear()
        self._input.setFocus()
        self.show()
        self.raise_()

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        if self._container is not None:
            self._container.append(text)
        if self._event is not None:
            self._event.set()
        self.hide()
        self.answered.emit(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setGeometry(self.parent().rect())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._submit_default()
        super().keyPressEvent(event)

    def _submit_default(self) -> None:
        if self._container is not None and not self._container:
            self._container.append("")
        if self._event is not None:
            self._event.set()
        self.hide()


class CopyPicker(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("overlay-backdrop")
        self.setStyleSheet(_OVERLAY_CSS)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        panel = QWidget()
        panel.setObjectName("overlay-panel")
        panel.setFixedWidth(600)
        panel_layout = QVBoxLayout(panel)

        title = QLabel("Copy a message")
        title.setObjectName("overlay-title")
        panel_layout.addWidget(title)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._on_copy)
        panel_layout.addWidget(self._list)

        self._messages_data: list[dict] = []
        layout.addWidget(panel)

    def show_messages(self, messages: list[dict]) -> None:
        self._list.clear()
        self._messages_data = build_copyable_messages(messages)
        for m in self._messages_data:
            preview = m.get("content", "")[:80].replace("\n", " ")
            label = f"[{m.get('label', '?')}] {preview}"
            self._list.addItem(label)
        self.show()
        self.raise_()

    def _on_copy(self, item: QListWidgetItem) -> None:
        idx = self._list.row(item)
        if 0 <= idx < len(self._messages_data):
            text = self._messages_data[idx].get("content", "")
            # Use Qt's cross-platform clipboard so this works on all OSes.
            clipboard = QGuiApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(text)
            self.hide()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setGeometry(self.parent().rect())
