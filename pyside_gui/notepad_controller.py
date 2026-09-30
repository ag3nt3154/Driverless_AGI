from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from agent import notepad_store as store

_LOGGER = logging.getLogger(__name__)

AUTOSAVE_MS = 1000


class NotepadController(QObject):
    """Owns the notepad text: debounced autosave, flush, external-change handling.

    Widget-free so the save/watch/conflict rules can be tested without a web view.
    The editor reports edits via ``on_editor_changed``; external reloads are pushed
    back through ``external_reload``.
    """

    dirty_changed = Signal(bool)
    external_reload = Signal(str)
    conflict_saved = Signal(object)  # Path of the backup holding the losing disk version

    def __init__(self, root: Path = store.NOTEPAD_DIR, autosave_ms: int = AUTOSAVE_MS, parent=None) -> None:
        super().__init__(parent)
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = store.notepad_path(root)
        self._text = store.read_text(root)
        self._saved_hash = store.content_hash(self._text)
        self._dirty = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(autosave_ms)
        self._timer.timeout.connect(self.save)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_disk_changed)
        # Watching the directory catches the file being (re)created by atomic replaces.
        self._watcher.directoryChanged.connect(self._on_disk_changed)
        self._watcher.addPath(str(self._root))
        self._rewatch()

    # ── State ────────────────────────────────────────────────────────────────

    def text(self) -> str:
        return self._text

    def is_dirty(self) -> bool:
        return self._dirty

    def _set_dirty(self, dirty: bool) -> None:
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    # ── Editing and saving ───────────────────────────────────────────────────

    def on_editor_changed(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text
        self._set_dirty(store.content_hash(text) != self._saved_hash)
        self._timer.start()

    def save(self) -> None:
        self._timer.stop()
        if not self._dirty:
            return
        self._write(self._text)

    def flush(self, text: str | None = None) -> None:
        """Persist immediately, optionally with the editor's latest text first."""
        if text is not None and text != self._text:
            self._text = text
            self._set_dirty(store.content_hash(text) != self._saved_hash)
        self.save()

    def save_as(self, path: Path) -> Path:
        """Write a copy of the note elsewhere; the backing file is unaffected."""
        return store.atomic_write(Path(path), self._text)

    def _write(self, text: str) -> None:
        # Record the hash first so the watcher event from our own write is ignored.
        self._saved_hash = store.content_hash(text)
        try:
            store.write_text(text, self._root)
        except OSError:
            _LOGGER.exception("Failed to save notepad")
            return
        self._set_dirty(False)
        self._rewatch()

    # ── External changes ─────────────────────────────────────────────────────

    def _rewatch(self) -> None:
        # os.replace swaps the inode, which drops the file from the watch list.
        if self._path.exists() and str(self._path) not in self._watcher.files():
            self._watcher.addPath(str(self._path))

    def _on_disk_changed(self, _path: str = "") -> None:
        self._rewatch()
        if not self._path.exists():
            return  # transient during another tool's atomic replace, or deleted
        try:
            disk = store.read_text(self._root)
        except OSError:
            return  # locked mid-replace; the writer's own change event follows
        disk_hash = store.content_hash(disk)
        if disk_hash == self._saved_hash:
            return  # our own write, or no real change
        if not self._dirty:
            self._timer.stop()
            self._text = disk
            self._saved_hash = disk_hash
            self.external_reload.emit(disk)
            return
        backup = store.backup_conflict(disk, self._root)
        _LOGGER.info("Notepad changed on disk during local edits; kept local, backed up %s", backup)
        self.conflict_saved.emit(backup)
        self._write(self._text)
