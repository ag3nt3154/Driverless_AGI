"""pyside_gui/sidebars/settings_view.py — left-sidebar editor for {DAGI_ROOT}/.dagi/config.yaml.

A thin view over one ``agent.config_editor.ConfigDocument``, the single source
of truth. The "Raw YAML" tab edits the document's text; leaving it re-parses
the text (an invalid document keeps the user on the tab). The "Form" tab is a
placeholder for now and re-populates from the document via
``_sync_form_from_doc`` whenever it is shown.

Save parses pending raw text, runs the strict ``validate()`` (errors block the
write, warnings are shown) and writes conflict-checked; a file changed on disk
offers Reload / Overwrite. ``validate()`` runs synchronously on the GUI thread
(it may execute a model client script). Changes apply to new sessions only.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from ruamel.yaml.comments import CommentedMap

from agent.config_editor import (
    ConfigConflictError,
    ConfigDocument,
    ConfigParseError,
    file_hash,
    validate,
)
from pyside_gui.theme import qss

_SAVED_MS = 2500
_FOOTER_TEXT = "Changes apply to new sessions."

_CSS = qss("""
QWidget#settings-view, QWidget#settings-content {
    background: @app_bg;
}
QLabel#sidebar-title {
    color: @fg_secondary;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 8px 0 8px 8px;
}
QLabel#settings-dirty {
    color: @warn;
    font-size: 11px;
    padding: 8px 0;
}
QLabel#settings-footer {
    color: @fg_tertiary;
    font-family: @font_ui;
    font-size: 11px;
    padding: 4px 8px 8px 8px;
}
QLabel#settings-placeholder {
    color: @fg_secondary;
    font-family: @font_ui;
    padding: 8px;
}
QFrame#settings-banner {
    border-radius: 6px;
    background: @well_bg;
}
QFrame#settings-banner[kind="error"] { border: 1px solid @danger; }
QFrame#settings-banner[kind="warn"] { border: 1px solid @warn; }
QFrame#settings-banner[kind="info"] { border: 1px solid @success; }
QFrame#settings-banner QLabel {
    color: @fg;
    font-family: @font_ui;
    font-size: 12px;
    background: transparent;
}
QTabWidget::pane {
    border: 1px solid @border;
    border-radius: 6px;
    background: @app_bg;
}
QTabBar::tab {
    color: @fg_secondary;
    background: transparent;
    padding: 4px 10px;
    border: none;
}
QTabBar::tab:selected {
    color: @fg;
    background: @active_bg;
    border-radius: 6px;
}
QTabBar::tab:hover:!selected {
    background: @hover_bg;
    border-radius: 6px;
}
QPlainTextEdit {
    background: @well_bg;
    color: @fg;
    border: none;
    font-family: @font_mono;
    font-size: 12px;
    selection-background-color: @selection;
}
QPushButton {
    color: @fg;
    background: @hover_bg;
    border: 1px solid @border;
    border-radius: 6px;
    padding: 4px 12px;
    font-family: @font_ui;
}
QPushButton:hover { background: @active_bg; }
QPushButton:disabled { color: @fg_tertiary; }
QPushButton#settings-save {
    color: @on_accent;
    background: @accent;
    border: none;
}
QScrollArea { border: none; background: @app_bg; }
""")


def _plain(text: str = "", name: str | None = None) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        label.setObjectName(name)
    return label


class SettingsView(QWidget):
    """Form + Raw YAML editor with one dirty flag and Save / Revert."""

    dirty_changed = Signal(bool)

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        if config_path is None:
            from agent import config_loader

            config_path = config_loader._CONFIG_PATH
        self._path = Path(config_path)
        self._doc: ConfigDocument  # set by reload()
        self._dirty = False
        self._unreadable = False
        self._populating = False

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_SAVED_MS)

        self.setObjectName("settings-view")
        self.setStyleSheet(_CSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("settings-content")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 8, 0)
        title_row.setSpacing(6)
        title_row.addWidget(_plain("SETTINGS", "sidebar-title"))
        self._dirty_dot = _plain("●", "settings-dirty")
        self._dirty_dot.setToolTip("Unsaved changes")
        self._dirty_dot.hide()
        title_row.addWidget(self._dirty_dot)
        title_row.addStretch()
        layout.addLayout(title_row)

        layout.addWidget(self._build_banner())

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._form_page = QWidget()
        form_layout = QVBoxLayout(self._form_page)
        form_layout.setContentsMargins(0, 0, 0, 0)
        placeholder = _plain("Form editor coming soon. Use Raw YAML.", "settings-placeholder")
        placeholder.setWordWrap(True)
        form_layout.addWidget(placeholder)
        form_layout.addStretch()
        self._form_index = self._tabs.addTab(self._form_page, "Form")

        self._raw = QPlainTextEdit()
        self._raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._raw.setMinimumHeight(320)
        self._raw.textChanged.connect(self._on_raw_changed)
        self._raw_index = self._tabs.addTab(self._raw, "Raw YAML")
        self._current_tab = self._tabs.currentIndex()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(8, 0, 8, 0)
        self._save_btn = QPushButton("Save")
        self._save_btn.setObjectName("settings-save")
        self._save_btn.clicked.connect(self._on_save)
        self._revert_btn = QPushButton("Revert")
        self._revert_btn.clicked.connect(self.reload)
        buttons.addWidget(self._save_btn)
        buttons.addWidget(self._revert_btn)
        buttons.addStretch()
        layout.addLayout(buttons)

        footer = _plain(_FOOTER_TEXT, "settings-footer")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self._banner_timer.timeout.connect(self._clear_banner)

        self.reload()

    # ── Public API ──

    def is_dirty(self) -> bool:
        return self._dirty

    def reload(self) -> None:
        """Discard edits and load the file from disk; the view becomes clean.

        A file that is not valid YAML is shown verbatim in the Raw tab with
        the parse error, against an empty document carrying the disk hash.
        A file that cannot be read or decoded shows an error and disables
        saving until a later reload succeeds.
        """
        self._clear_banner()
        self._set_unreadable(False)
        try:
            self._doc = ConfigDocument.load(self._path)
        except ConfigParseError as exc:
            # Valid UTF-8 (load decoded it), so the text can be shown and fixed.
            # Saving re-parses it first, so nothing is written while it is invalid.
            raw = self._path.read_bytes()
            self._doc = ConfigDocument(
                CommentedMap(), self._path, file_hash(self._path),
                newline="\r\n" if b"\r\n" in raw else "\n",
            )
            self._set_loaded(raw.decode("utf-8").replace("\r\n", "\n"), on_raw=True)
            self._show_banner("error", f"config.yaml is not valid YAML: {_parse_message(exc)}")
            return
        except (OSError, UnicodeDecodeError) as exc:
            # The text cannot be shown faithfully: lock the view so nothing overwrites it.
            self._doc = ConfigDocument(CommentedMap(), self._path, None)
            self._set_unreadable(True)
            self._set_loaded("", on_raw=True)
            self._show_banner(
                "error",
                f"Could not read {self._path}: {exc}\n"
                "Saving is disabled. Fix the file (UTF-8 YAML), then click Revert.",
            )
            return
        self._set_loaded(self._doc.text(), on_raw=False)

    # ── Document / tab sync ──

    def _set_loaded(self, raw_text: str, *, on_raw: bool) -> None:
        self._set_raw_text(raw_text)
        self._sync_form_from_doc()
        self._set_dirty(False)
        if on_raw:
            self._show_tab(self._raw_index)

    def _set_unreadable(self, unreadable: bool) -> None:
        """While the file cannot be read, saving is off and Raw is read-only."""
        self._unreadable = unreadable
        self._save_btn.setEnabled(not unreadable)
        self._raw.setReadOnly(unreadable)

    def _sync_form_from_doc(self) -> None:
        """Re-populate the Form tab from the document (no-op until Subtask 6)."""

    def _set_raw_text(self, text: str) -> None:
        self._populating = True
        try:
            self._raw.setPlainText(text)
        finally:
            self._populating = False

    def _show_tab(self, index: int) -> None:
        self._tabs.blockSignals(True)
        try:
            self._tabs.setCurrentIndex(index)
        finally:
            self._tabs.blockSignals(False)
        self._current_tab = index

    def _on_raw_changed(self) -> None:
        if not self._populating:
            self._set_dirty(True)

    def _on_tab_changed(self, index: int) -> None:
        previous, self._current_tab = self._current_tab, index
        if previous == self._raw_index and index != self._raw_index:
            if not self._apply_raw():
                self._show_tab(self._raw_index)
                return
        if index == self._raw_index:
            self._set_raw_text(self._doc.text())
        elif index == self._form_index:
            self._sync_form_from_doc()

    def _apply_raw(self) -> bool:
        """Parse the Raw tab into the document; on error show it and return False."""
        text = self._raw.toPlainText()
        if text == self._doc.text():
            return True
        try:
            self._doc.replace_text(text)
        except ConfigParseError as exc:
            self._show_banner("error", f"Invalid YAML: {_parse_message(exc)}")
            return False
        if self._banner.property("kind") == "error":
            self._clear_banner()
        return True

    # ── Save ──

    def _on_save(self) -> None:
        self._save(force=False)

    def _save(self, *, force: bool) -> None:
        if self._unreadable:
            return
        if self._tabs.currentIndex() == self._raw_index and not self._apply_raw():
            return
        result = validate(self._doc)
        if result.errors:
            self._show_banner("error", "\n".join(["Not saved:", *result.errors]))
            return
        try:
            self._doc.save(force=force)
        except ConfigConflictError:
            self._show_banner("error", "config.yaml changed on disk.", conflict=True)
            return
        except OSError as exc:
            self._show_banner("error", f"Could not save: {exc}")
            return
        if self._tabs.currentIndex() == self._raw_index:
            self._set_raw_text(self._doc.text())
        self._set_dirty(False)
        if result.warnings:
            self._show_banner("warn", "\n".join(["Saved.", *result.warnings]))
        else:
            self._show_banner("info", "Saved.")
            self._banner_timer.start()

    def _on_overwrite(self) -> None:
        self._save(force=True)

    # ── Banner / dirty state ──

    def _build_banner(self) -> QFrame:
        self._banner = QFrame()
        self._banner.setObjectName("settings-banner")
        row = QVBoxLayout(self._banner)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(4)
        self._banner_label = _plain()
        self._banner_label.setWordWrap(True)
        self._banner_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self._banner_label)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        self._reload_btn = QPushButton("Reload")
        self._reload_btn.setToolTip("Discard your edits and load the file from disk")
        self._reload_btn.clicked.connect(self.reload)
        self._overwrite_btn = QPushButton("Overwrite")
        self._overwrite_btn.setToolTip("Replace the file on disk with your edits")
        self._overwrite_btn.clicked.connect(self._on_overwrite)
        actions.addWidget(self._reload_btn)
        actions.addWidget(self._overwrite_btn)
        actions.addStretch()
        row.addLayout(actions)
        self._banner_wrap = QWidget()
        wrap = QVBoxLayout(self._banner_wrap)
        wrap.setContentsMargins(8, 0, 8, 0)
        wrap.addWidget(self._banner)
        self._clear_banner()
        return self._banner_wrap

    def _show_banner(self, kind: str, text: str, *, conflict: bool = False) -> None:
        self._banner_timer.stop()
        self._banner.setProperty("kind", kind)
        self._banner.style().unpolish(self._banner)
        self._banner.style().polish(self._banner)
        self._banner_label.setText(text)
        self._reload_btn.setVisible(conflict)
        self._overwrite_btn.setVisible(conflict)
        self._banner_wrap.show()

    def _clear_banner(self) -> None:
        self._banner.setProperty("kind", "")
        self._banner_label.setText("")
        self._reload_btn.hide()
        self._overwrite_btn.hide()
        self._banner_wrap.hide()

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty_dot.setVisible(dirty)
        if dirty == self._dirty:
            return
        self._dirty = dirty
        self.dirty_changed.emit(dirty)


def _parse_message(exc: ConfigParseError) -> str:
    return f"line {exc.line}: {exc.message}" if exc.line else exc.message
