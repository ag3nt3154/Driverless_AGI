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
    """

    TAIL_LINES = 12

    DEFAULT_CSS = """
    StreamPreview {
        display: none;
        height: auto;
        max-height: 14;
        padding: 0 1;
        border-top: dashed $panel;
        color: $text-muted;
    }
    """

    def show_progress(self, reasoning: str, text: str) -> None:
        """Render the accumulated stream so far and make the widget visible."""
        self.styles.display = "block"
        self.update(self._render_tail(reasoning, text))

    def finish(self) -> None:
        """Hide and clear — the final text is written to the conversation pane."""
        self.styles.display = "none"
        self.update("")

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
        if len(lines) > self.TAIL_LINES:
            lines = lines[-self.TAIL_LINES:]
        return Text("\n").join(lines)
