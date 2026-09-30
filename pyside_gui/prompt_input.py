from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QAction, QFocusEvent, QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from agent.user_input import ImageAttachment, UserSubmission
from pyside_gui.icons import icon
from pyside_gui.menu_style import MENU_STYLESHEET
from pyside_gui.slash_completer import SlashCompleterPopup
from pyside_gui.theme import TOKENS, qss

# Mirrors agent._loop_config.AgentConfig defaults (image_input_*). Kept as
# local constants so the GUI can reject oversized pastes before they ever
# reach the agent loop / provider.
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
_SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg")
_THUMB_SIZE = 56

# The card matches the conversation's reading column (conversation.css).
CARD_MAX_WIDTH = 760
MAX_EDITOR_HEIGHT = 240
COMPOSE_MIN_HEIGHT = 320
PLACEHOLDER = "Message DAGI…  (Enter to send, Shift+Enter for newline)"

_CARD_CSS = qss("""
QFrame#composer-card {
    background: @composer_bg;
    border: 1px solid @composer_border;
    border-radius: 18px;
}
QFrame#composer-card[focused="true"] { border-color: @fg_quaternary; }
QPlainTextEdit#composer-editor {
    background: transparent;
    color: @fg;
    border: none;
    padding: 0;
    font-family: @font_ui;
    font-size: 15px;
    selection-background-color: @selection;
}
QToolButton#composer-attach {
    background: transparent;
    border: none;
    border-radius: 15px;
}
QToolButton#composer-attach:hover { background: @hover_bg; }
QToolButton#composer-model {
    background: transparent;
    color: @fg_secondary;
    border: none;
    border-radius: 14px;
    padding: 0 10px 0 6px;
    font-family: @font_ui;
    font-size: 13px;
}
QToolButton#composer-model:hover { background: @hover_bg; color: @fg; }
QToolButton#composer-model:disabled { color: @fg_tertiary; }
QToolButton#composer-model::menu-indicator { image: none; width: 0; }
QToolButton#composer-send {
    background: @accent;
    border: none;
    border-radius: 16px;
}
QToolButton#composer-send:disabled { background: @fg_quaternary; }
QLabel#attachment-pic {
    background: @well_bg;
    border-radius: 10px;
}
QToolButton#attachment-remove {
    background: @popover_bg;
    border: 1px solid @border;
    border-radius: 9px;
}
QToolButton#attachment-remove:hover { background: @danger; }
""")


def _encode_png(image: QImage) -> bytes | None:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data if ok else None


class _AttachmentThumb(QWidget):
    """A single rounded thumbnail with a small remove (✕) badge."""

    remove_requested = Signal(int)

    def __init__(self, index: int, image: QImage) -> None:
        super().__init__()
        self._index = index
        self.setFixedSize(_THUMB_SIZE + 8, _THUMB_SIZE + 8)

        pic = QLabel(self)
        pic.setObjectName("attachment-pic")
        thumb = QPixmap.fromImage(image).scaled(
            _THUMB_SIZE,
            _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pic.setPixmap(thumb)
        pic.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pic.move(0, 8)

        close_btn = QToolButton(self)
        close_btn.setObjectName("attachment-remove")
        close_btn.setIcon(icon("close", 10, stroke_width=2.4))
        close_btn.setIconSize(QSize(10, 10))
        close_btn.setFixedSize(18, 18)
        close_btn.setToolTip("Remove image")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.move(_THUMB_SIZE - 10, 0)
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self._index))


class _AttachmentStrip(QWidget):
    """Horizontal strip of attachment thumbnails; hidden when empty."""

    remove_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 6)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)
        self.hide()

    def set_images(self, images: list[QImage]) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for idx, img in enumerate(images):
            thumb = _AttachmentThumb(idx, img)
            thumb.remove_requested.connect(self.remove_requested)
            self._layout.insertWidget(idx, thumb)
        self.setVisible(bool(images))


class _Editor(QPlainTextEdit):
    """The actual text surface. Delegates submission + paste routing to the
    owning ``PromptInput`` so both stay in one place."""

    def __init__(self, owner: "PromptInput") -> None:
        super().__init__()
        self._owner = owner

    def keyPressEvent(self, event: QKeyEvent) -> None:
        mods = event.modifiers()
        key = event.key()
        completer_visible = self._owner._completer.isVisible()

        if completer_visible:
            if key == Qt.Key.Key_Tab and not (mods & Qt.KeyboardModifier.ShiftModifier):
                self._owner._accept_completion()
                event.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (mods & (
                    Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.ControlModifier
                )):
                    self._owner._accept_completion()
                    event.accept()
                    return
                # Shift/Ctrl+Enter: fall through to insert newline below
            if key == Qt.Key.Key_Escape:
                self._owner._completer.hide()
                event.accept()
                return
            if key == Qt.Key.Key_Down:
                self._owner._completer.move_selection(1)
                event.accept()
                return
            if key == Qt.Key.Key_Up:
                self._owner._completer.move_selection(-1)
                event.accept()
                return

        if key == Qt.Key.Key_Tab:
            event.accept()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier
            ):
                super().keyPressEvent(event)
                return
            self._owner._submit()
            event.accept()
            return

        super().keyPressEvent(event)

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._owner._set_card_focused(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        self._owner._completer.hide()
        self._owner._set_card_focused(False)
        super().focusOutEvent(event)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        self._owner._handle_paste(source)


class PromptInput(QWidget):
    """The composer: a rounded card holding image attachments, an
    auto-growing text field and a toolbar (attach, model pill, send/stop).

    Enter submits (text and/or attachments), Shift+Enter/Ctrl+Enter insert a
    newline. Emits a single ``UserSubmission`` object per submit. While the
    agent runs with the editor locked, the send button turns into Stop and
    emits ``stop_requested``.
    """

    submitted = Signal(object)  # UserSubmission
    attachment_error = Signal(str)
    stop_requested = Signal()
    model_selected = Signal(str)  # model id

    def __init__(self) -> None:
        super().__init__()
        self._attachments: list[ImageAttachment] = []
        self._draft_rejected: bool = False
        self._attachment_previews: list[QImage] = []
        self._running = False
        self._compose = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 0, 24, 14)
        outer.setSpacing(0)

        self._card = QFrame()
        self._card.setObjectName("composer-card")
        self._card.setMaximumWidth(CARD_MAX_WIDTH)
        self._card.setStyleSheet(_CARD_CSS)
        outer.addStretch(1)
        outer.addWidget(self._card, stretch=100)
        outer.addStretch(1)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(16, 12, 10, 8)
        layout.setSpacing(6)

        self._strip = _AttachmentStrip()
        self._strip.remove_requested.connect(self._remove_attachment)
        layout.addWidget(self._strip)

        self._editor = _Editor(self)
        self._editor.setObjectName("composer-editor")
        self._editor.setPlaceholderText(PLACEHOLDER)
        self._editor.setFrameShape(QFrame.Shape.NoFrame)
        self._editor.document().setDocumentMargin(2)
        self._editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._editor.document().documentLayout().documentSizeChanged.connect(
            lambda _size: self._fit_editor()
        )
        layout.addWidget(self._editor)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(4)

        self._attach_btn = QToolButton()
        self._attach_btn.setObjectName("composer-attach")
        self._attach_btn.setIcon(icon("plus", 18))
        self._attach_btn.setIconSize(QSize(18, 18))
        self._attach_btn.setFixedSize(30, 30)
        self._attach_btn.setToolTip("Attach images")
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_btn.clicked.connect(self._pick_images)
        toolbar.addWidget(self._attach_btn)

        self._model_btn = QToolButton()
        self._model_btn.setObjectName("composer-model")
        self._model_btn.setIcon(icon("spark", 14))
        self._model_btn.setIconSize(QSize(14, 14))
        self._model_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._model_btn.setFixedHeight(28)
        self._model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_btn.setToolTip("Switch model")
        self._model_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._model_menu = QMenu(self._model_btn)
        self._model_menu.setStyleSheet(MENU_STYLESHEET)
        self._model_btn.setMenu(self._model_menu)
        self._model_btn.hide()
        toolbar.addWidget(self._model_btn)

        toolbar.addStretch(1)

        self._send_btn = QToolButton()
        self._send_btn.setObjectName("composer-send")
        self._send_btn.setFixedSize(32, 32)
        self._send_btn.setIconSize(QSize(16, 16))
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send_clicked)
        toolbar.addWidget(self._send_btn)
        layout.addLayout(toolbar)

        self._completer = SlashCompleterPopup(self)
        self._editor.textChanged.connect(self._on_text_changed)
        self._fit_editor()
        self._refresh_send_button()

    # ---- forwarded widget-ish API (keeps app.py's existing call sites) ----

    def setDisabled(self, disabled: bool) -> None:  # noqa: N802
        self._editor.setDisabled(disabled)
        self._attach_btn.setDisabled(disabled)
        self._model_btn.setDisabled(disabled)
        self._refresh_send_button()

    def setFocus(self) -> None:  # noqa: N802
        self._editor.setFocus()

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802
        self._editor.setPlaceholderText(text)

    def toPlainText(self) -> str:  # noqa: N802
        return self._editor.toPlainText()

    def clear(self) -> None:
        self._editor.clear()
        self._clear_attachments()

    def set_compose_mode(self, expanded: bool) -> None:
        self._compose = expanded
        self._fit_editor()

    def set_running(self, running: bool) -> None:
        """The agent is working: the send button can stop it."""
        self._running = running
        self._refresh_send_button()

    def set_models(self, model_ids: list[str], active_id: str, active_name: str) -> None:
        """Fill the model pill's menu and show the active model's name."""
        self._model_menu.clear()
        for model_id in model_ids:
            action = QAction(model_id, self._model_menu)
            action.setCheckable(True)
            action.setChecked(model_id == active_id)
            action.triggered.connect(
                lambda _checked=False, m=model_id: self.model_selected.emit(m)
            )
            self._model_menu.addAction(action)
        self.set_model_name(active_name)
        self._model_btn.setVisible(bool(model_ids))

    def set_model_name(self, name: str) -> None:
        self._model_btn.setText(name)

    def set_completions(self, items: list[tuple[str, str]]) -> None:
        """Load the list of available slash commands for autocomplete."""
        self._completer.set_items(items)

    # ---- layout ----

    def _fit_editor(self) -> None:
        """Grow with the text from one line up to MAX_EDITOR_HEIGHT; compose
        mode (Ctrl+O) instead gives the editor a tall fixed minimum."""
        if self._compose:
            self._editor.setMinimumHeight(COMPOSE_MIN_HEIGHT)
            self._editor.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            return
        doc = self._editor.document()
        line = self._editor.fontMetrics().lineSpacing()
        lines = max(1, int(doc.documentLayout().documentSize().height()))
        height = lines * line + 2 * int(doc.documentMargin()) + 4
        self._editor.setFixedHeight(min(max(height, line + 8), MAX_EDITOR_HEIGHT))

    def _set_card_focused(self, focused: bool) -> None:
        self._card.setProperty("focused", "true" if focused else "false")
        self._card.style().unpolish(self._card)
        self._card.style().polish(self._card)

    def _stop_mode(self) -> bool:
        return self._running and not self._editor.isEnabled()

    def _refresh_send_button(self) -> None:
        on_accent = TOKENS["on_accent"]
        if self._stop_mode():
            self._send_btn.setIcon(icon("stop", 16, color=on_accent))
            self._send_btn.setToolTip("Stop (Esc)")
        else:
            self._send_btn.setIcon(icon("arrow_up", 16, color=on_accent, stroke_width=2.4))
            self._send_btn.setToolTip("Send (Enter)")

    def _on_send_clicked(self) -> None:
        if self._stop_mode():
            self.stop_requested.emit()
        elif self._editor.isEnabled():
            self._submit()

    # ---- slash completion ----

    def _current_slash_prefix(self) -> str | None:
        """Return the /command prefix being typed, or None if not applicable."""
        text = self._editor.toPlainText()
        if not text.startswith("/"):
            return None
        # Autocomplete only applies to the first word (before any space or newline)
        if " " in text or "\n" in text:
            return None
        return text

    def _on_text_changed(self) -> None:
        prefix = self._current_slash_prefix()
        if prefix is None:
            self._completer.hide()
            return
        self._completer.apply_filter(prefix)   # resize first (updates height)
        self._position_completer()             # then position with correct height

    def _position_completer(self) -> None:
        """Position the popup just above the composer card."""
        card_rect = self._card.geometry()
        popup_height = self._completer.height()
        global_pos = self.mapToGlobal(card_rect.topLeft())
        self._completer.setFixedWidth(card_rect.width())
        self._completer.move(global_pos.x(), global_pos.y() - popup_height - 4)

    def _accept_completion(self) -> None:
        """Replace the current text with the selected command + trailing space."""
        cmd = self._completer.selected_command()
        if cmd is None:
            return
        self._completer.hide()
        self._editor.setPlainText(cmd + " ")
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)

    # ---- submission ----

    def _submit(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text and not self._attachments:
            return
        submission = UserSubmission(text=text, images=tuple(self._attachments))
        self._draft_rejected = False
        self.submitted.emit(submission)
        if not self._draft_rejected:
            self._editor.clear()
            self._clear_attachments()

    def restore_draft(self, submission: UserSubmission) -> None:
        """Put a rejected submission's content back into the editor.

        Used when the window declines to route a submission (e.g. images
        while a plain-text answer is expected) so the user doesn't lose
        what they typed/pasted. Sets _draft_rejected so _submit() skips
        its post-emit clear.
        """
        self._draft_rejected = True
        self._editor.setPlainText(submission.text)
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)
        for attachment in submission.images:
            preview = QImage()
            preview.loadFromData(attachment.data)
            self._attachments.append(attachment)
            self._attachment_previews.append(preview)
        self._strip.set_images(self._attachment_previews)
        self._editor.setFocus()

    def _clear_attachments(self) -> None:
        self._attachments.clear()
        self._attachment_previews.clear()
        self._strip.set_images([])

    def _remove_attachment(self, index: int) -> None:
        if 0 <= index < len(self._attachments):
            del self._attachments[index]
            del self._attachment_previews[index]
            self._strip.set_images(self._attachment_previews)

    # ---- paste / attach handling ----
    # TODO: for large batches/files, move decode+PNG-encode off the UI
    # thread (QThread/worker). Fine on the GUI thread for v1's small pastes.

    def _pick_images(self) -> None:
        names, _filter = QFileDialog.getOpenFileNames(
            self, "Attach images", "", "Images (*.png *.jpg *.jpeg)"
        )
        if names:
            self._add_image_paths([Path(n) for n in names])

    def _handle_paste(self, source: QMimeData) -> None:
        if source.hasImage():
            self._paste_image(source)
            return
        if source.hasUrls():
            self._paste_urls(source)
            return
        self._editor.insertPlainText(source.text())

    def _paste_image(self, source: QMimeData) -> None:
        image = QImage(source.imageData())
        if image.isNull():
            self._editor.insertPlainText(source.text())
            return
        self._try_add_image(image, name=f"pasted-{len(self._attachments) + 1}.png")

    def _paste_urls(self, source: QMimeData) -> None:
        paths: list[Path] = []
        for url in source.urls():
            if not url.isLocalFile():
                self._report_error("Only local image files can be pasted.")
                return
            paths.append(Path(url.toLocalFile()))
        self._add_image_paths(paths)

    def _add_image_paths(self, paths: list[Path]) -> None:
        for path in paths:
            if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                self._report_error(f"Unsupported file type: {path.name}")
                return
        decoded: list[tuple[QImage, str]] = []
        for path in paths:
            img = QImage(str(path))
            if img.isNull():
                self._report_error(f"Could not read image: {path.name}")
                return
            decoded.append((img, path.name))
        for img, name in decoded:
            if not self._try_add_image(img, name=name):
                return

    def _try_add_image(self, image: QImage, name: str) -> bool:
        if len(self._attachments) >= MAX_IMAGES_PER_MESSAGE:
            self._report_error(
                f"Maximum {MAX_IMAGES_PER_MESSAGE} images per message."
            )
            return False
        pixels = image.width() * image.height()
        if pixels > MAX_IMAGE_PIXELS:
            self._report_error(
                f"Image too large ({pixels:,} px) — limit is {MAX_IMAGE_PIXELS:,} px."
            )
            return False
        data = _encode_png(image)
        if not data:
            self._report_error("Failed to encode image.")
            return False
        if len(data) > MAX_IMAGE_BYTES:
            self._report_error(
                f"Image file too large ({len(data):,} bytes) — "
                f"limit is {MAX_IMAGE_BYTES:,} bytes."
            )
            return False
        attachment = ImageAttachment(
            data=data,
            mime_type="image/png",
            width=image.width(),
            height=image.height(),
            name=name,
        )
        self._attachments.append(attachment)
        self._attachment_previews.append(image)
        self._strip.set_images(self._attachment_previews)
        self._editor.setFocus()
        return True

    def _report_error(self, message: str) -> None:
        self.attachment_error.emit(message)
