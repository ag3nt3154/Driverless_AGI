from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QMimeData, Qt, Signal
from PySide6.QtGui import QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from agent.user_input import ImageAttachment, UserSubmission
from pyside_gui.slash_completer import SlashCompleterPopup

# Mirrors agent._loop_config.AgentConfig defaults (image_input_*). Kept as
# local constants so the GUI can reject oversized pastes before they ever
# reach the agent loop / provider.
MAX_IMAGES_PER_MESSAGE = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
_SUPPORTED_EXTENSIONS = (".png", ".jpg", ".jpeg")
_THUMB_SIZE = 64


def _encode_png(image: QImage) -> bytes | None:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data if ok else None


class _AttachmentThumb(QWidget):
    """A single thumbnail preview with a remove (X) button."""

    remove_requested = Signal(int)

    def __init__(self, index: int, image: QImage) -> None:
        super().__init__()
        self._index = index
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        pic = QLabel()
        thumb = QPixmap.fromImage(image).scaled(
            _THUMB_SIZE,
            _THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pic.setPixmap(thumb)
        pic.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pic.setStyleSheet(
            "border: 1px solid #45475a; border-radius: 4px; background: #181825;"
        )
        layout.addWidget(pic)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(
            "QPushButton { background: #45475a; color: #cdd6f4; border: none;"
            " border-radius: 9px; font-size: 10px; }"
            "QPushButton:hover { background: #f38ba8; color: #1e1e2e; }"
        )
        close_btn.clicked.connect(lambda: self.remove_requested.emit(self._index))
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignHCenter)


class _AttachmentStrip(QWidget):
    """Horizontal strip of attachment thumbnails; hidden when empty."""

    remove_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(6)
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

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        if source.hasImage() or source.hasUrls():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        self._owner._handle_paste(source)


class PromptInput(QWidget):
    """Multi-line input with image-paste support.

    Enter submits (text and/or attachments), Shift+Enter/Ctrl+Enter insert a
    newline. Emits a single ``UserSubmission`` object per submit.
    """

    submitted = Signal(object)  # UserSubmission
    attachment_error = Signal(str)

    COLLAPSED_HEIGHT = 100
    BORDER_STYLE = (
        "QPlainTextEdit {"
        "  background: #282839;"
        "  color: #cdd6f4;"
        "  border: 1px solid #45475a;"
        "  border-radius: 8px;"
        "  padding: 8px;"
        "  font-family: 'Segoe UI', system-ui, sans-serif;"
        "  font-size: 14px;"
        "}"
        "QPlainTextEdit:focus {"
        "  border-color: #89b4fa;"
        "}"
    )

    def __init__(self) -> None:
        super().__init__()
        self._attachments: list[ImageAttachment] = []
        self._draft_rejected: bool = False
        self._attachment_previews: list[QImage] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._strip = _AttachmentStrip()
        self._strip.remove_requested.connect(self._remove_attachment)
        layout.addWidget(self._strip)

        self._editor = _Editor(self)
        self._editor.setPlaceholderText(
            "Type a message… (Enter to send, Shift+Enter for newline)"
        )
        self._editor.setStyleSheet(self.BORDER_STYLE)
        self._editor.setFixedHeight(self.COLLAPSED_HEIGHT)
        layout.addWidget(self._editor)

        self._completer = SlashCompleterPopup(self)
        self._editor.textChanged.connect(self._on_text_changed)

    # ---- forwarded widget-ish API (keeps app.py's existing call sites) ----

    def setDisabled(self, disabled: bool) -> None:  # noqa: N802
        self._editor.setDisabled(disabled)

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
        if expanded:
            self._editor.setMinimumHeight(200)
            self._editor.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        else:
            self._editor.setFixedHeight(self.COLLAPSED_HEIGHT)

    def set_completions(self, items: list[tuple[str, str]]) -> None:
        """Load the list of available slash commands for autocomplete."""
        self._completer.set_items(items)

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
        """Position the popup just above the editor."""
        editor_rect = self._editor.geometry()
        popup_height = self._completer.height()
        global_pos = self.mapToGlobal(editor_rect.topLeft())
        self._completer.setFixedWidth(editor_rect.width())
        self._completer.move(global_pos.x(), global_pos.y() - popup_height)

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

    # ---- paste handling ----
    # TODO: for large batches/files, move decode+PNG-encode off the UI
    # thread (QThread/worker). Fine on the GUI thread for v1's small pastes.

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
        urls = source.urls()
        paths: list[Path] = []
        for url in urls:
            if not url.isLocalFile():
                self._report_error("Only local image files can be pasted.")
                return
            path = Path(url.toLocalFile())
            if path.suffix.lower() not in _SUPPORTED_EXTENSIONS:
                self._report_error(f"Unsupported file type: {path.name}")
                return
            paths.append(path)
        if not paths:
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
