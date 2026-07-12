from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptInput(TextArea):
    """Single-submit text area: Enter submits, Shift+Enter inserts newline."""

    class Submitted(Message):
        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text
            if text.strip():
                self.post_message(self.Submitted(text))
            self.load_text("")
        elif event.key in ("shift+enter", "ctrl+n", "ctrl+enter"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
