from __future__ import annotations

from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog

from .utils import _colour, _truncate


class ConversationPane(RichLog):
    """Scrollable Rich log. auto_scroll pauses when user scrolls up."""

    def on_mount(self) -> None:
        self.auto_scroll = True

    def append_tool_start(self, name: str, args: str, verbose: bool) -> None:
        col = _colour(name)
        self.write(Panel(
            f"[dim]{args if verbose else _truncate(args)}[/dim]",
            title=f"[{col}]▶ {name}[/{col}]",
            title_align="left", border_style=col, padding=(0, 1),
        ))

    def append_tool_end(self, name: str, result: str, verbose: bool) -> None:
        col = _colour(name)
        if verbose:
            self.write(Panel(result, title=f"[{col}]✓ {name}[/{col}]",
                             title_align="left", border_style="dim", padding=(0, 1)))
        else:
            self.write(Text(f"  ✓ {len(result)} chars", style="dim green"))

    def append_assistant(self, text: str) -> None:
        self.write(Markdown(text))

    def append_reasoning(self, text: str) -> None:
        self.write(Panel(
            f"[dim italic]{text}[/dim italic]",
            title="[dim bold]🧠 Thinking[/dim bold]",
            title_align="left", border_style="dim", padding=(0, 1),
        ))

    def append_info(self, markup: str) -> None:
        self.write(Text.from_markup(markup))

    def append_error(self, msg: str) -> None:
        self.write(Text(f"Error: {msg}", style="bold red"))

    def append_question(self, question: str, options: list[dict], timeout: float | None) -> None:
        self.write(Panel(question, title="[bold cyan]Question from Dagi[/bold cyan]",
                         border_style="cyan", padding=(0, 2)))
        if options:
            tbl = Table(border_style="dim", padding=(0, 1))
            tbl.add_column("#", style="bold cyan", width=3)
            tbl.add_column("Option", style="bold")
            tbl.add_column("Description", style="dim")
            for i, opt in enumerate(options, 1):
                rec = " [bold green](recommended)[/bold green]" if opt.get("recommended") else ""
                tbl.add_row(str(i), opt["label"] + rec, opt.get("description", ""))
            self.write(tbl)
        hint = f"auto-selects in {int(timeout)}s — " if timeout else ""
        self.write(Text(f"{hint}type your answer:", style="dim"))
