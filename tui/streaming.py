from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class StreamPreview(Static):
    """Live preview of the currently-streaming assistant turn.

    ConversationPane is a RichLog — append-only, so in-flight text cannot be
    updated there without leaving stale partial copies in scrollback. This
    widget shows the growing reasoning/text while a response streams; when the
    stream ends it hides again and the final Markdown/Panel is written to the
    conversation pane exactly as before streaming existed.

    Hidden via DEFAULT_CSS until show_progress() is first called. Only the
    last TAIL_LINES lines are rendered so the preview never crowds out the
    conversation; the full text always lands in the conversation pane at the
    end of the turn.

    While expanded (see expand()), the widget fills the full window instead of
    the 14-row cap, and the visible tail grows to match its actual rendered
    height instead of the fixed TAIL_LINES constant.
    """

    TAIL_LINES = 12

    DEFAULT_CSS = """
    StreamPreview {
        display: none;
        height: auto;
        padding: 0 1;
        border-top: dashed $panel;
        color: $text-muted;
    }
    """

    _expanded: bool = False

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        # Set as an inline rule (rather than in DEFAULT_CSS) so expand() can
        # later clear_rule() it back to a genuine None instead of falling
        # back to a CSS-level default.
        self.styles.max_height = 14

    def show_progress(self, reasoning: str, text: str) -> None:
        """Render the accumulated stream so far and make the widget visible."""
        self.styles.display = "block"
        self.update(self._render_tail(reasoning, text))

    def expand(self) -> None:
        """Grow to fill available space instead of the 14-row cap."""
        self._expanded = True
        self.styles.height = "1fr"
        self.styles.clear_rule("max_height")

    def finish(self) -> None:
        """Hide, clear, and restore the collapsed 14-row/12-line defaults."""
        self.styles.display = "none"
        self.update("")
        self._expanded = False
        self.styles.height = "auto"
        self.styles.max_height = 14

    def _tail_line_count(self) -> int:
        if self._expanded and self.size.height > 0:
            return self.size.height
        return self.TAIL_LINES

    def _render_tail(self, reasoning: str, text: str) -> Text:
        out = Text()
        if reasoning:
            out.append("\U0001f9e0 ", style="dim")
            out.append(reasoning.strip(), style="dim italic")
        if reasoning and text:
            out.append("\n\n")
        if text:
            out.append(text)
        lines = out.split("\n", allow_blank=True)
        limit = self._tail_line_count()
        if len(lines) > limit:
            lines = lines[-limit:]
        return Text("\n").join(lines)
