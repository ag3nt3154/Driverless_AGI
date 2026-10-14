"""pyside_gui/sidebars/settings_view.py — left-sidebar editor for {DAGI_ROOT}/.dagi/config.yaml.

A thin view over one ``agent.config_editor.ConfigDocument``, the single source
of truth. The "Raw YAML" tab edits the document's text; leaving it re-parses
the text (an invalid document keeps the user on the tab). The "Form" tab has
one widget per agreed key; each change is written to the document at once
(text fields on editingFinished) and marks the view dirty. The form is
re-populated from the document (``_sync_form_from_doc``) on load and whenever
it is shown, under the ``_populating`` guard so populating never marks dirty.
Absent keys show the loader default and are written only when changed.

Tool checklists toggle entries by commenting their lines
(``ConfigDocument.set_item_enabled``). With no ``tools`` key (= all tools)
the Tools checklist edits ``disabled_tools`` instead: the form never writes a
``tools:`` snapshot, which would silently drop project and future tools.
``tools: null`` (or a non-list value) shows a read-only checklist and a note.

Save parses pending raw text, runs the strict ``validate()`` (errors block the
write, warnings are shown) and writes conflict-checked; a file changed on disk
offers Reload / Overwrite. ``validate()`` runs synchronously on the GUI thread
(it may execute a model client script). Changes apply to new sessions only.

A ``QFileSystemWatcher`` watches the config file (re-added after every event
and save: os.replace drops it on Windows); its parent directory is watched
only while the file is missing, to notice it being re-created. Events are
debounced into ``_check_disk``: a missing file or an unchanged hash (own save,
no-op touch) is ignored; otherwise pending text-field input is committed, then
a clean view reloads silently and a dirty one shows the conflict banner. The
conflict banner is sticky (``_conflict``):
other messages are shown under it and clearing the banner re-shows it, until
Reload / Revert or a successful Save / Overwrite.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QFileSystemWatcher, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from ruamel.yaml.comments import CommentedMap

from agent.config_editor import (
    ConfigConflictError,
    ConfigDocument,
    ConfigParseError,
    file_hash,
    tool_catalog,
    validate,
)
from pyside_gui.theme import qss
from services.message_board.lifecycle import DEFAULT_URL as _BOARD_DEFAULT_URL
from services.message_board.settings import DEFAULT_BIND as _BOARD_DEFAULT_BIND

_SAVED_MS = 2500
_WATCH_DEBOUNCE_MS = 200
_WATCH_RETRIES = 10  # re-checks while the file cannot be read (e.g. locked mid-write)
_CONFLICT_TEXT = "config.yaml changed on disk."
_FOOTER_TEXT = "Changes apply to new sessions."
_MISSING: Any = object()

# Loader defaults (agent.config_loader._build_config_from_entry) shown for absent keys.
_SPIN_FIELDS: tuple[tuple[str, str, str, int, int, int], ...] = (
    # (group, key, label, minimum, maximum, default)
    ("Context", "context_window", "Context window (tokens)", 1, 10_000_000, 128_000),
    ("Context", "keep_recent_tokens", "Keep recent (tokens)", 1, 10_000_000, 20_000),
    ("Context", "reserve_tokens", "Reserve (tokens)", 1, 10_000_000, 16_384),
    ("Reliability", "null_response_retries", "Null-response retries", 0, 100, 3),
    ("Reliability", "api_error_retries", "API-error retries", 0, 100, 3),
)
_FEATURE_FIELDS: tuple[tuple[str, str, bool, str], ...] = (
    ("sandbox_mode", "Sandbox mode", False,
     "On: file tools have no path restrictions (allowed_roots=None). Default: off."),
    ("code_mode", "Code mode", True,
     "Off: the `code` tool is not registered. Default: on."),
    ("computer_use", "Computer use", False,
     "On: register the computer_use_* window tools (they still pass the tools "
     "allowlist). Default: off."),
)
_MODEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("default_model", "Default model"),
    ("worker_model", "Worker model"),
    ("advanced_model", "Advanced model"),
)
_SAME_AS_DEFAULT = "(same as default)"
_TEXT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("memory_root", "Memory root", "Built-in default"),
    ("services.message_board.url", "Message board URL", _BOARD_DEFAULT_URL),
    ("services.message_board.bind", "Message board bind", _BOARD_DEFAULT_BIND),
)
_NOTE_ALL_TOOLS = "All tools enabled (no `tools:` list) — unchecking adds to disabled_tools."
_NOTE_TOOLS_NULL = "tools: null — remove the key to enable all tools (Save will refuse null)."
_NOTE_TOOLS_NOT_LIST = "tools is not a list — edit it in Raw YAML."
_UNKNOWN_TOOL_TIP = "Not a known built-in or subagent tool"
# With computer_use on, these pass the `tools:` allowlist (agent/tools.py
# _apply_filters_and_handoff); only disabled_tools can turn them off.
_ALLOWLIST_BYPASS_PREFIXES = ("computer_use_", "rpa_")
_BYPASS_TIP = (
    "Always available while Computer use is on: computer_use_* and rpa_* tools "
    "bypass the tools: allowlist. Use Disabled tools to turn it off."
)

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
QWidget#settings-form {
    background: @app_bg;
}
QGroupBox {
    color: @fg_secondary;
    font-family: @font_ui;
    font-size: 11px;
    font-weight: bold;
    border: 1px solid @border;
    border-radius: 6px;
    margin-top: 14px;
    padding: 6px 6px 6px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QLabel#settings-field-label, QLabel#settings-note {
    color: @fg_secondary;
    font-family: @font_ui;
    font-size: 11px;
    font-weight: normal;
}
QLabel#settings-note { color: @fg_tertiary; }
QLabel#settings-warning { color: @warn; font-family: @font_ui; font-size: 11px; }
QCheckBox {
    color: @fg;
    font-family: @font_ui;
    font-size: 12px;
    font-weight: normal;
    spacing: 6px;
}
QCheckBox:disabled, QLabel:disabled { color: @fg_tertiary; }
QLineEdit, QSpinBox, QComboBox {
    color: @fg;
    background: @well_bg;
    border: 1px solid @border;
    border-radius: 4px;
    padding: 3px 6px;
    font-family: @font_ui;
    font-size: 12px;
    font-weight: normal;
    selection-background-color: @selection;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid @accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: @fg_tertiary; }
QComboBox QAbstractItemView {
    color: @fg;
    background: @menu_bg;
    selection-background-color: @active_bg;
}
QToolButton#settings-disclosure {
    color: @fg_secondary;
    background: transparent;
    border: none;
    font-family: @font_ui;
    font-size: 12px;
    font-weight: normal;
    padding: 2px 0;
}
QToolButton#settings-disclosure:hover { color: @fg; }
QFrame#settings-banner {
    border-radius: 6px;
    background: @well_bg;
}
QFrame#settings-banner[kind="error"] { border: 1px solid @danger; }
QFrame#settings-banner[kind="warn"] { border: 1px solid @warn; }
QFrame#settings-banner[kind="info"] { border: 1px solid @success; }
QFrame#settings-banner[kind="conflict"] { border: 1px solid @danger; }
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


def _expanding(widget: QWidget) -> QWidget:
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setMinimumWidth(0)
    return widget


def _checklist_order(listed: list[str], catalog: list[str]) -> list[str]:
    """Listed names in file order (de-duplicated), then the rest of the catalog
    alphabetically."""
    names = list(dict.fromkeys(listed))
    seen = set(names)
    return names + sorted(n for n in catalog if n not in seen)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _WheelGuard(QObject):
    """Ignore wheel events on unfocused spin boxes / combos.

    The form lives in a scroll area: scrolling the panel over a field must not
    silently change (and write) a config value. The wheel event is forwarded
    to the scroll area so the panel still scrolls.
    """

    def __init__(self, parent: QObject, scroll: Callable[[], QScrollArea | None]) -> None:
        super().__init__(parent)
        self._scroll = scroll

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Wheel and isinstance(obj, QWidget) and not obj.hasFocus():
            scroll = self._scroll()
            if scroll is not None:
                QApplication.sendEvent(scroll.verticalScrollBar(), event)
            return True
        return False


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
        self._conflict = False  # sticky "changed on disk" banner pending
        self._populating = False
        self._catalog: list[str] | None = None  # tool_catalog(), computed on first use
        self._scroll: QScrollArea | None = None
        self._wheel_guard = _WheelGuard(self, lambda: self._scroll)

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
        self._scroll = scroll

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
        self._form_page = self._build_form()
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

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_watch_event)
        self._watcher.directoryChanged.connect(self._on_watch_event)
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(_WATCH_DEBOUNCE_MS)
        self._watch_timer.timeout.connect(self._check_disk)
        self._watch_retries = _WATCH_RETRIES

        self.reload()
        self._watch()

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
        self._conflict = False
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
        self._form_body.setEnabled(not unreadable)

    # ── Form tab ──

    def _build_form(self) -> QWidget:
        page = QWidget()
        page.setObjectName("settings-form")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(6, 6, 6, 6)
        page_layout.setSpacing(0)
        self._form_body = QWidget()
        self._form_body.setObjectName("settings-form")
        body = QVBoxLayout(self._form_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        page_layout.addWidget(self._form_body)
        page_layout.addStretch()

        groups: dict[str, QVBoxLayout] = {}

        def group(title: str) -> QVBoxLayout:
            if title not in groups:
                box = QGroupBox(title)
                lay = QVBoxLayout(box)
                lay.setContentsMargins(6, 10, 6, 6)
                lay.setSpacing(3)
                body.addWidget(box)
                groups[title] = lay
            return groups[title]

        # Models
        self._model_combos: dict[str, QComboBox] = {}
        for key, label in _MODEL_FIELDS:
            combo = QComboBox()
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.currentIndexChanged.connect(lambda _i, k=key: self._on_model_changed(k))
            self._add_field(group("Models"), label, combo)
            self._model_combos[key] = combo

        # Context / Reliability
        self._spins: dict[str, QSpinBox] = {}
        self._spin_defaults: dict[str, int] = {}
        self._spin_warnings: dict[str, QLabel] = {}
        for grp, key, label, lo, hi, default in _SPIN_FIELDS:
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setGroupSeparatorShown(True)
            spin.setKeyboardTracking(False)  # commit on Enter / focus-out / arrows
            spin.setToolTip(f"{key} — default {default:,}")
            spin.valueChanged.connect(lambda v, k=key: self._on_spin_changed(k, int(v)))
            self._add_field(group(grp), label, spin)
            warning = _plain("", "settings-warning")
            warning.setWordWrap(True)
            warning.hide()
            group(grp).addWidget(warning)
            self._spins[key] = spin
            self._spin_defaults[key] = default
            self._spin_warnings[key] = warning

        # Features
        self._checks: dict[str, QCheckBox] = {}
        self._check_defaults: dict[str, bool] = {}
        for key, label, default, tip in _FEATURE_FIELDS:
            check = QCheckBox(label)
            check.setToolTip(f"{key}: {tip}")
            check.toggled.connect(lambda on, k=key: self._commit(k, bool(on)))
            group("Features").addWidget(check)
            self._checks[key] = check
            self._check_defaults[key] = default
        self._checks["computer_use"].toggled.connect(lambda _on: self._refresh_tool_states())

        # Tools
        tools = group("Tools")
        self._tools_note = _plain("", "settings-note")
        self._tools_note.setWordWrap(True)
        tools.addWidget(self._tools_note)
        self._tools_list = QWidget()
        self._tools_list_layout = QVBoxLayout(self._tools_list)
        self._tools_list_layout.setContentsMargins(0, 0, 0, 0)
        self._tools_list_layout.setSpacing(1)
        tools.addWidget(self._tools_list)
        self._tool_checks: dict[str, QCheckBox] = {}
        self._tools_mode = "absent"  # "list" | "absent" (all tools) | "locked" (null / not a list)

        self._disabled_toggle = QToolButton()
        self._disabled_toggle.setObjectName("settings-disclosure")
        self._disabled_toggle.setText("Disabled tools (always off)")
        self._disabled_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._disabled_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self._disabled_toggle.setCheckable(True)
        self._disabled_toggle.setToolTip(
            "disabled_tools: always off, even if a project config enables all tools")
        self._disabled_toggle.toggled.connect(self._on_disabled_toggled)
        tools.addWidget(self._disabled_toggle)
        self._disabled_box = QWidget()
        self._disabled_layout = QVBoxLayout(self._disabled_box)
        self._disabled_layout.setContentsMargins(12, 0, 0, 0)
        self._disabled_layout.setSpacing(1)
        self._disabled_box.hide()
        tools.addWidget(self._disabled_box)
        self._disabled_checks: dict[str, QCheckBox] = {}

        # Paths & services
        paths = group("Paths && services")
        self._text_fields: dict[str, QLineEdit] = {}
        for key, label, placeholder in _TEXT_FIELDS:
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            field.setToolTip(f"{key} — leave empty to remove the key (default: {placeholder})")
            field.editingFinished.connect(lambda k=key: self._on_text_committed(k))
            self._text_fields[key] = field
            if key == "memory_root":
                row = QWidget()
                row_layout = QHBoxLayout(row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(4)
                row_layout.addWidget(_expanding(field), 1)
                self._browse_btn = QPushButton("Browse…")
                self._browse_btn.clicked.connect(self._on_browse_memory_root)
                row_layout.addWidget(self._browse_btn)
                self._add_field(paths, label, row)
            else:
                self._add_field(paths, label, field)
        return page

    def _add_field(self, layout: QVBoxLayout, label: str, widget: QWidget) -> None:
        """Label above its widget: stays usable in the narrow side panel."""
        layout.addWidget(_plain(label, "settings-field-label"))
        _expanding(widget)
        if isinstance(widget, (QSpinBox, QComboBox)):
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            widget.installEventFilter(self._wheel_guard)
        layout.addWidget(widget)

    def _tool_names(self) -> list[str]:
        if self._catalog is None:
            try:
                self._catalog = tool_catalog()
            except Exception:  # noqa: BLE001 — an unusable catalog must not break the view
                self._catalog = []
        return self._catalog

    def _model_ids(self) -> list[str]:
        """Model IDs from the catalog next to this view's config, plus inline models."""
        from agent import config_loader

        ids: list[str] = []
        try:
            ids = list((config_loader.load_raw_config(config_path=self._path).get("models") or {}))
        except Exception:  # noqa: BLE001 — unreadable catalog: show what the doc has
            ids = []
        inline = self._doc.get("models")
        if isinstance(inline, dict):
            ids += [str(k) for k in inline if str(k) not in ids]
        return ids

    def _sync_form_from_doc(self) -> None:
        """Re-populate every Form widget from the document without marking dirty."""
        was, self._populating = self._populating, True
        try:
            self._populate_models()
            for key, spin in self._spins.items():
                value = self._doc.get(key)
                spin.setValue(value if _is_int(value) else self._spin_defaults[key])
                self._update_spin_warning(key)
            for key, check in self._checks.items():
                value = self._doc.get(key)
                check.setChecked(value if isinstance(value, bool) else self._check_defaults[key])
            self._populate_tools()
            for key, field in self._text_fields.items():
                value = self._doc.get(key)
                field.setText("" if value is None else str(value))
        finally:
            self._populating = was

    def _populate_models(self) -> None:
        from agent.config_loader import _FALLBACK_MODEL_ID

        ids = self._model_ids()
        for key, combo in self._model_combos.items():
            combo.clear()
            current = self._doc.get(key)
            if key != "default_model":
                combo.addItem(_SAME_AS_DEFAULT, None)
            elif current in (None, ""):
                current = _FALLBACK_MODEL_ID  # what the loader picks when absent
            for model_id in ids:
                combo.addItem(model_id, model_id)
            if current not in (None, "") and combo.findData(current) < 0:
                combo.addItem(f"{current} (missing)", current)
            combo.setCurrentIndex(max(0, combo.findData(current)))

    def _update_spin_warning(self, key: str) -> None:
        """Flag a file value the spin box cannot show (non-int or out of range)."""
        spin, warning = self._spins[key], self._spin_warnings[key]
        raw = self._doc.get(key, _MISSING)
        bad = raw is not _MISSING and not (
            _is_int(raw) and spin.minimum() <= raw <= spin.maximum())
        if bad:
            shown = "null" if raw is None else str(raw)
            warning.setText(
                f"File value: {shown} — not valid here, showing {spin.value():,}. "
                "Left unchanged until you edit this field.")
        warning.setVisible(bad)

    def _on_spin_changed(self, key: str, value: int) -> None:
        if self._populating:
            return
        self._commit(key, value)
        self._update_spin_warning(key)

    # ── Tool checklists ──
    # `tools` list present ("list"): boxes edit `tools` by commenting entries.
    # `tools` absent ("absent", = all tools): boxes edit `disabled_tools`; the
    # form never writes a `tools:` snapshot (it would drop project tools).
    # `tools: null` or a non-list value ("locked"): shown all-checked, read-only.

    def _populate_tools(self) -> None:
        catalog = self._tool_names()
        known = set(catalog)
        value = self._doc.get("tools", _MISSING)
        tool_items = self._doc.list_items("tools")
        disabled_items = self._doc.list_items("disabled_tools")
        if value is _MISSING:
            self._tools_mode = "absent"
            note = _NOTE_ALL_TOOLS
        elif isinstance(value, list) or tool_items:
            self._tools_mode = "list"  # incl. every entry commented out
            note = ""
        else:
            self._tools_mode = "locked"
            note = _NOTE_TOOLS_NULL if value is None else _NOTE_TOOLS_NOT_LIST
        self._tools_note.setText(note)
        self._tools_note.setVisible(bool(note))

        if self._tools_mode == "list":
            tool_names = _checklist_order([n for n, _ in tool_items], catalog)
        else:
            tool_names = _checklist_order([], catalog)
            if self._tools_mode == "absent":
                tool_names += [n for n, _ in disabled_items if n not in tool_names]
        self._fill_checklist(self._tools_list_layout, self._tool_checks, "tools", tool_names, known)
        self._fill_checklist(
            self._disabled_layout, self._disabled_checks, "disabled_tools",
            _checklist_order([n for n, _ in disabled_items], catalog), known,
        )
        self._refresh_tool_states()

    def _fill_checklist(
        self, layout: QVBoxLayout, checks: dict[str, QCheckBox], key: str,
        names: list[str], known: set[str],
    ) -> None:
        for check in checks.values():
            layout.removeWidget(check)
            check.deleteLater()
        checks.clear()
        for name in names:
            check = QCheckBox(name if name in known else f"{name}  (unknown)")
            check.setProperty("unknown", name not in known)
            check.toggled.connect(lambda on, k=key, n=name: self._on_tool_toggled(k, n, on))
            layout.addWidget(check)
            checks[name] = check

    def _refresh_tool_states(self) -> None:
        """Set every tool box's checked/enabled state and tooltip from the document."""
        active = {n for n, on in self._doc.list_items("tools") if on}
        disabled = {n for n, on in self._doc.list_items("disabled_tools") if on}
        bypass_on = self._tools_mode == "list" and self._checks["computer_use"].isChecked()
        was, self._populating = self._populating, True
        try:
            for name, check in self._tool_checks.items():
                if self._tools_mode == "list":
                    check.setChecked(name in active)
                elif self._tools_mode == "absent":
                    check.setChecked(name not in disabled)
                else:
                    check.setChecked(True)
                bypass = bypass_on and name.startswith(_ALLOWLIST_BYPASS_PREFIXES)
                check.setEnabled(not bypass)
                tips = [_UNKNOWN_TOOL_TIP] if check.property("unknown") else []
                if bypass:
                    tips.append(_BYPASS_TIP)
                check.setToolTip("\n".join(tips))
            for name, check in self._disabled_checks.items():
                check.setChecked(name in disabled)
                check.setToolTip(_UNKNOWN_TOOL_TIP if check.property("unknown") else "")
        finally:
            self._populating = was
        self._tools_list.setEnabled(self._tools_mode != "locked")

    def _on_tool_toggled(self, key: str, name: str, checked: bool) -> None:
        if self._populating:
            return
        if key == "tools" and self._tools_mode == "absent":
            key, checked = "disabled_tools", not checked  # unchecked = add to disabled_tools
        elif key == "tools" and self._tools_mode == "locked":
            self._refresh_tool_states()
            return
        self._apply_edit(lambda: self._doc.set_item_enabled(key, name, checked))
        self._refresh_tool_states()  # keeps both checklists in sync (or reverts on failure)

    # ── Scalar fields ──

    def _apply_edit(self, edit: Callable[[], None]) -> bool:
        """Run a document edit; mark dirty if the text changed, banner on failure."""
        before = self._doc.text()
        try:
            edit()
        except (TypeError, ValueError) as exc:
            self._show_banner("error", f"Could not apply the change: {exc}")
            return False
        if self._doc.text() != before:
            self._set_dirty(True)
        return True

    def _commit(self, key: str, value: Any) -> None:
        """Write one Form value (``None`` deletes the key).

        On failure the form is re-populated so no widget shows a value that
        was not applied.
        """
        if self._populating:
            return
        if not self._apply_edit(lambda: self._doc.set(key, value)):
            self._sync_form_from_doc()

    def _on_model_changed(self, key: str) -> None:
        if self._populating:
            return
        self._commit(key, self._model_combos[key].currentData())

    def _on_text_committed(self, key: str) -> None:
        if self._populating:
            return
        text = self._text_fields[key].text().strip()
        current = self._doc.get(key)
        if text == ("" if current is None else str(current)):
            return
        # An empty value deletes the key only when committed, never mid-edit.
        self._commit(key, text or None)

    def _on_browse_memory_root(self) -> None:
        field = self._text_fields["memory_root"]
        start = field.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose memory root", start)
        if not chosen:
            return
        field.setText(str(Path(chosen)))
        self._on_text_committed("memory_root")

    def _on_disabled_toggled(self, expanded: bool) -> None:
        self._disabled_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._disabled_box.setVisible(expanded)

    # ── Raw text ──

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
            self._show_banner("conflict", _CONFLICT_TEXT, conflict=True)
            return
        except OSError as exc:
            self._show_banner("error", f"Could not save: {exc}")
            return
        finally:
            self._watch()  # os.replace drops the file from the watcher on Windows
        self._conflict = False
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

    # ── File watcher ──

    def _watch(self) -> None:
        """Watch the config file; watch its directory only while the file is missing.

        Re-adds the file after Windows dropped it (os.replace). The directory
        watch exists only to notice the file being (re)created: kept next to
        a watched file, it makes ``os.replace`` intermittently fail with
        "Access is denied" on Windows.
        """
        file_s, dir_s = str(self._path), str(self._path.parent)
        if self._path.exists():
            if file_s not in self._watcher.files():
                self._watcher.addPath(file_s)
            if dir_s in self._watcher.directories():
                self._watcher.removePath(dir_s)
        elif dir_s not in self._watcher.directories() and self._path.parent.is_dir():
            self._watcher.addPath(dir_s)

    def _on_watch_event(self, _path: str) -> None:
        self._watch()
        self._watch_retries = _WATCH_RETRIES
        self._watch_timer.start()  # restarts: a burst of events is checked once

    def _check_disk(self) -> None:
        """Debounced: react to the file on disk differing from the document."""
        self._watch()
        try:
            disk_hash = file_hash(self._path)
        except OSError:
            # Unreadable for now (e.g. locked mid-write): look again shortly.
            if self._watch_retries > 0:
                self._watch_retries -= 1
                self._watch_timer.start()
            return
        if disk_hash is None:
            return  # missing (e.g. mid delete/recreate): wait for it to reappear
        if disk_hash == self._doc.base_hash:
            # Own save or a no-op touch — or the file went back to what was
            # loaded, so Save no longer conflicts.
            if self._conflict:
                self._conflict = False
                self._clear_banner()
            return
        if not self._unreadable:
            # A text field being typed in commits only on editingFinished:
            # commit it now so it counts as an edit instead of being reloaded over.
            for key in self._text_fields:
                self._on_text_committed(key)
        if self._dirty:
            self._show_banner("conflict", _CONFLICT_TEXT, conflict=True)
        else:
            self.reload()

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
        """Show a message; ``conflict=True`` makes the conflict banner sticky.

        While a conflict is pending, other messages appear under its text and
        its Reload / Overwrite actions stay visible.
        """
        self._banner_timer.stop()
        if conflict:
            self._conflict = True
        if self._conflict and text != _CONFLICT_TEXT:
            text = f"{_CONFLICT_TEXT}\n{text}"
        self._banner.setProperty("kind", kind)
        self._banner.style().unpolish(self._banner)
        self._banner.style().polish(self._banner)
        self._banner_label.setText(text)
        self._reload_btn.setVisible(self._conflict)
        self._overwrite_btn.setVisible(self._conflict)
        self._banner_wrap.show()

    def _clear_banner(self) -> None:
        """Hide the banner, or fall back to the conflict banner while one is pending."""
        if self._conflict:
            self._show_banner("conflict", _CONFLICT_TEXT)
            return
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
