"""tui/revise_history.py — Confirmation modal for /revise-history."""
from __future__ import annotations

from typing import Sequence

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from agent.session_log import StepInfo


def format_step_summaries(infos: Sequence[StepInfo]) -> str:
    """Format step summaries for display in the confirmation modal."""
    lines: list[str] = []
    for info in infos:
        tools = ", ".join(info.tool_names) if info.tool_names else "(no tools)"
        lines.append(
            f"  Step {info.step_number} (turn {info.turn}): "
            f"[{tools}] — \"{info.assistant_snippet}\""
        )
    return "\n".join(lines)


class ReviseConfirmScreen(ModalScreen[bool]):
    """Modal asking the user to confirm step removal."""

    CSS = """
    ReviseConfirmScreen {
        align: center middle;
    }
    #revise-dialog {
        width: 72;
        max-height: 20;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #revise-summary {
        margin-bottom: 1;
    }
    #revise-buttons {
        layout: horizontal;
        align: center middle;
        height: 3;
    }
    #revise-buttons Button {
        margin: 0 2;
    }
    """

    def __init__(self, infos: Sequence[StepInfo]) -> None:
        super().__init__()
        self._infos = infos

    def compose(self) -> ComposeResult:
        count = len(self._infos)
        header = f"Will remove {count} step{'s' if count != 1 else ''}:"
        body = format_step_summaries(self._infos)
        with Vertical(id="revise-dialog"):
            yield Label(header, id="revise-header")
            yield Static(body, id="revise-summary")
            with Center(id="revise-buttons"):
                yield Button("Yes", variant="error", id="revise-yes")
                yield Button("No", variant="primary", id="revise-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "revise-yes")
