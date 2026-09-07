# Desktop Pet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move VAD expression emotes into a standalone desktop pet window; simplify the right sidebar ExpressionWidget to show process-state only.

**Architecture:** A new `DesktopPetWindow(QWidget)` renders VAD emotes in a frameless, always-on-top, transparent window. The existing `ExpressionWidget` is stripped of channel rotation and expression handling, becoming a simple process-state display. A `/show-pet` slash command toggles the pet window. No agent-side changes.

**Tech Stack:** PySide6 (Qt 6), Python 3.14

**Spec:** `docs/superpowers/specs/2026-09-07-desktop-pet-design.md`

---

### Task 1: Create DesktopPetWindow

**Files:**
- Create: `pyside_gui/desktop_pet.py`

- [ ] **Step 1: Create the DesktopPetWindow class**

```python
# pyside_gui/desktop_pet.py
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, Slot
from PySide6.QtGui import QImageReader, QMovie, QMouseEvent, QPixmap, QScreen
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from agent.expression import ExpressionSnapshot
from agent.expression_assets import AssetRef, ImageAsset, TextFallback

_LOGGER = logging.getLogger(__name__)

_PET_SIZE = QSize(210, 182)  # same as ExpressionWidget._GIF_BOUND
_EDGE_INSET = 20


class DesktopPetWindow(QWidget):
    """Frameless always-on-top window that displays VAD expression emotes."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_PET_SIZE)

        self._drag_origin: QPoint | None = None
        self._movie: QMovie | None = None
        self._static_pixmap: QPixmap | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFixedSize(_PET_SIZE)
        layout.addWidget(self._label)

        self._move_to_default()

    def _move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.right() - _PET_SIZE.width() - _EDGE_INSET
        y = geo.bottom() - _PET_SIZE.height() - _EDGE_INSET
        self.move(x, y)

    # ── Drag support ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        event.accept()

    # ── Expression rendering ──────────────────────────────────────────────────

    @Slot(object)
    def update_expression(self, snapshot: ExpressionSnapshot) -> None:
        self._render_asset(snapshot.asset)

    def _render_asset(self, asset: AssetRef) -> None:
        if isinstance(asset, TextFallback):
            self._clear_media()
            self._label.setText(asset.text)
            return
        if asset.path.suffix.lower() == ".gif":
            if self._show_movie(asset):
                return
        elif self._show_pixmap(asset):
            return
        self._clear_media()
        self._label.setText("?")

    def _show_movie(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            return False
        natural = QImageReader(str(asset.path)).size()
        movie = QMovie(str(asset.path))
        movie.setParent(self)
        if not movie.isValid():
            movie.setParent(None)
            movie.deleteLater()
            return False
        if natural.isValid() and not natural.isEmpty():
            scaled = natural.scaled(_PET_SIZE, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            scaled = _PET_SIZE
        movie.setScaledSize(scaled)
        self._movie = movie
        self._label.setMovie(movie)
        movie.start()
        return True

    def _show_pixmap(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            return False
        pixmap = QPixmap(str(asset.path))
        if pixmap.isNull():
            return False
        self._static_pixmap = pixmap
        self._label.setPixmap(
            pixmap.scaled(
                _PET_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        return True

    def _clear_media(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.setParent(None)
            self._movie.deleteLater()
            self._movie = None
        self._static_pixmap = None
        self._label.clear()
```

- [ ] **Step 2: Verify the module imports cleanly**

Run:
```bash
conda run -n dagi python -c "from pyside_gui.desktop_pet import DesktopPetWindow; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyside_gui/desktop_pet.py
git commit -m "feat: add DesktopPetWindow for VAD emote display"
```

---

### Task 2: Simplify ExpressionWidget to process-state only

**Files:**
- Modify: `pyside_gui/expression_widget.py`

- [ ] **Step 1: Rewrite ExpressionWidget to only handle process state**

Replace the entire contents of `pyside_gui/expression_widget.py` with:

```python
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QFont, QImageReader, QMovie, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent.expression_assets import AssetRef, ImageAsset, TextFallback, load_fallback
from agent.process_state import ProcessSnapshot

_LOGGER = logging.getLogger(__name__)


class ExpressionWidget(QWidget):
    """Renders the current process-state emote in the right sidebar."""

    n = 1.4
    _GIF_BOUND = QSize(int(150 * n), int(130 * n))

    def __init__(self, emotes_root: Path) -> None:
        super().__init__()
        self._emotes_root = emotes_root
        self._default_fallback = load_fallback(emotes_root)
        self._movie: QMovie | None = None
        self._movie_natural_size: QSize | None = None
        self._static_pixmap: QPixmap | None = None
        self._warned_media_failures: set[str] = set()
        self._process_snapshot = ProcessSnapshot("idle", self._default_fallback)

        self._image_label = QLabel()
        self._image_label.setObjectName("expression-image")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setTextFormat(Qt.TextFormat.PlainText)
        self._image_label.setWordWrap(False)
        self._image_label.setMinimumHeight(self._GIF_BOUND.height())
        self._image_label.setMaximumHeight(self._GIF_BOUND.height())
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )

        self._caption_label = QLabel()
        self._caption_label.setObjectName("expression-caption")
        self._caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        image_row = QHBoxLayout()
        image_row.setContentsMargins(0, 0, 0, 0)
        image_row.addStretch()
        image_row.addWidget(self._image_label)
        image_row.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(4)
        layout.addLayout(image_row)
        layout.addWidget(self._caption_label)

        self._render_current()

    @Slot(object)
    def update_process(self, snapshot: ProcessSnapshot) -> None:
        self._process_snapshot = snapshot
        self._render_current()

    def _render_current(self) -> None:
        self._render_asset(self._process_snapshot.asset)
        self._caption_label.setText(f"PROCESS {self._process_snapshot.state}")

    def _render_asset(self, asset: AssetRef) -> None:
        if isinstance(asset, TextFallback):
            self._show_text(asset.text)
            return
        if asset.path.suffix.lower() == ".gif":
            if self._show_movie(asset):
                return
        elif self._show_pixmap(asset):
            return
        self._show_text(self._default_fallback.text)

    def _show_text(self, text: str) -> None:
        self._clear_media()
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self._image_label.setFont(font)
        self._image_label.setText(text)

    def _show_movie(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            self._warn_media_failure("gif missing", asset.path)
            return False
        natural = QImageReader(str(asset.path)).size()
        self._movie_natural_size = natural if natural.isValid() and not natural.isEmpty() else None
        movie = QMovie(str(asset.path))
        movie.setParent(self)
        if not movie.isValid():
            self._warn_media_failure("gif decode failed", asset.path)
            self._release_movie(movie)
            self._movie_natural_size = None
            return False
        movie.setScaledSize(self._movie_scaled_size())
        self._movie = movie
        self._image_label.setMovie(movie)
        movie.start()
        return True

    def _show_pixmap(self, asset: ImageAsset) -> bool:
        self._clear_media()
        if not asset.path.is_file():
            self._warn_media_failure("pixmap missing", asset.path)
            return False
        pixmap = QPixmap(str(asset.path))
        if pixmap.isNull():
            self._warn_media_failure("pixmap decode failed", asset.path)
            return False
        self._static_pixmap = pixmap
        self._image_label.setPixmap(self._scaled_pixmap())
        return True

    def _clear_media(self) -> None:
        if self._movie is not None:
            self._release_movie(self._movie)
            self._movie = None
        self._movie_natural_size = None
        self._static_pixmap = None
        self._image_label.clear()

    def _release_movie(self, movie: QMovie) -> None:
        movie.stop()
        movie.setParent(None)
        movie.deleteLater()

    def _warn_media_failure(self, operation: str, path: Path) -> None:
        key = f"{operation}:{path}"
        if key in self._warned_media_failures:
            return
        self._warned_media_failures.add(key)
        _LOGGER.warning("process %s: %s", operation, path)

    def _scaled_pixmap(self) -> QPixmap:
        if self._static_pixmap is None:
            return QPixmap()
        return self._static_pixmap.scaled(
            self._target_size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _target_size(self) -> QSize:
        size = self._image_label.size()
        bound_h = self._GIF_BOUND.height()
        width = size.width() if size.width() > 0 else max(self.width(), 160)
        height = min(size.height() if size.height() > 0 else bound_h, bound_h)
        return QSize(max(width, 1), max(height, 1))

    def _movie_scaled_size(self) -> QSize:
        if self._movie_natural_size is not None:
            return self._movie_natural_size.scaled(
                self._GIF_BOUND, Qt.AspectRatioMode.KeepAspectRatio
            )
        return self._GIF_BOUND

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._static_pixmap is not None:
            self._image_label.setPixmap(self._scaled_pixmap())
```

- [ ] **Step 2: Verify the module imports cleanly**

Run:
```bash
conda run -n dagi python -c "from pyside_gui.expression_widget import ExpressionWidget; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add pyside_gui/expression_widget.py
git commit -m "refactor: simplify ExpressionWidget to process-state only"
```

---

### Task 3: Wire DesktopPetWindow and update signal connections in app.py

**Files:**
- Modify: `pyside_gui/app.py`

- [ ] **Step 1: Add desktop pet import**

At the top of `pyside_gui/app.py`, add to the imports:

```python
from pyside_gui.desktop_pet import DesktopPetWindow
```

- [ ] **Step 2: Create the pet window in `_build_ui()`**

At the end of `_build_ui()`, after `self.setCentralWidget(self._splitter)` and before the CopyPicker line, add:

```python
        self._desktop_pet = DesktopPetWindow()
```

- [ ] **Step 3: Update signal connections in `_connect_signals()`**

Find this line:
```python
        b.expression_changed.connect(rs.expression_widget.update_expression)
```

Replace it with:
```python
        b.expression_changed.connect(self._desktop_pet.update_expression)
```

The `b.process_state_changed.connect(rs.expression_widget.update_process)` line stays unchanged.

- [ ] **Step 4: Close pet window when main window closes**

Add a `closeEvent` override to `DagiMainWindow`:

```python
    def closeEvent(self, event) -> None:
        self._desktop_pet.close()
        super().closeEvent(event)
```

- [ ] **Step 5: Verify imports**

Run:
```bash
conda run -n dagi python -c "from pyside_gui.app import DagiMainWindow; print('OK')"
```
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add pyside_gui/app.py
git commit -m "feat: wire DesktopPetWindow into main app, update signal routing"
```

---

### Task 4: Add `/show-pet` slash command

**Files:**
- Modify: `pyside_gui/commands.py`
- Modify: `tui/utils.py` (for `_SLASH_HELP`)

- [ ] **Step 1: Add pet window reference to SlashCommandHandler**

The `SlashCommandHandler` needs access to the pet window. Add a setter method after `set_on_session_cleared`:

```python
    def set_desktop_pet(self, pet: "DesktopPetWindow") -> None:
        self._desktop_pet = pet
```

And initialise `self._desktop_pet = None` in `__init__`.

- [ ] **Step 2: Add the `/show-pet` command handler**

In the `handle` method, add a new `elif` before the `self._skill_map` check:

```python
        elif cmd == "/show-pet":
            return self._cmd_show_pet()
```

Add the handler method:

```python
    def _cmd_show_pet(self) -> None:
        if self._desktop_pet is None:
            self._w.conversation.append_error("Desktop pet not available")
            return None
        if self._desktop_pet.isVisible():
            self._desktop_pet.hide()
            self._w.conversation.append_info("Desktop pet hidden")
        else:
            self._desktop_pet.show()
            self._w.conversation.append_info("Desktop pet shown")
        return None
```

- [ ] **Step 3: Add TYPE_CHECKING import for DesktopPetWindow**

In the `if TYPE_CHECKING:` block in `commands.py`, add:

```python
    from pyside_gui.desktop_pet import DesktopPetWindow
```

- [ ] **Step 4: Wire the pet reference in app.py `_build_commands()`**

In `DagiMainWindow._build_commands()`, after `self._cmd_handler.load_maps()`, add:

```python
        self._cmd_handler.set_desktop_pet(self._desktop_pet)
```

- [ ] **Step 5: Add help text**

In `tui/utils.py`, add to `_SLASH_HELP` dict:

```python
    "/show-pet": "Toggle desktop pet window",
```

- [ ] **Step 6: Verify imports**

Run:
```bash
conda run -n dagi python -c "from pyside_gui.commands import SlashCommandHandler; print('OK')"
```
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add pyside_gui/commands.py pyside_gui/app.py tui/utils.py
git commit -m "feat: add /show-pet slash command to toggle desktop pet"
```

---

### Task 5: Update existing tests

**Files:**
- Modify: `tests/test_expression_widget_meme.py`

The existing `test_expression_widget_meme.py` tests a `_FakeWidget` that models the old channel-rotation and meme-overlay logic. Since the ExpressionWidget no longer has expression/meme handling, these tests are obsolete.

- [ ] **Step 1: Remove the obsolete meme widget tests**

Delete the file `tests/test_expression_widget_meme.py` — the meme display was already moved to the message board (earlier commit), and the ExpressionWidget no longer handles expressions at all.

- [ ] **Step 2: Run the full test suite to check for breakage**

Run:
```bash
conda run -n dagi python -m pytest tests/ -x -q 2>&1 | head -40
```
Expected: All tests pass (no imports of the removed `update_expression` method or old channel logic).

- [ ] **Step 3: Commit**

```bash
git add -u tests/test_expression_widget_meme.py
git commit -m "test: remove obsolete meme widget tests (expression moved to desktop pet)"
```

---

### Task 6: Update README.md

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the PySide6 GUI section**

Find the PySide6 description paragraph and update it to mention the desktop pet and `/show-pet` command.

In the keyboard shortcuts / slash commands line for the PySide6 GUI section, add `/show-pet` to the list.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document desktop pet and /show-pet command"
```
