from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widget import Widget

from .utils import _system_breakdown

_EMOTE_FALLBACK = "(◉ ᴗ ◉)"


class Sidebar(Widget):
    """Always-visible right panel: status, token stats, context breakdown."""

    DEFAULT_CSS = "Sidebar { overflow-y: auto; }"

    def __init__(
        self,
        model_name: str,
        context_window: int,
        reserve_tokens: int,
        dagi_root: Path,
        project_path: Path,
    ) -> None:
        super().__init__()
        self._status = "idle"
        self._model_name = model_name
        self._input_tok = 0
        self._output_tok = 0
        self._thinking_tok = 0
        self._cost: float | None = None
        self._buckets: dict[str, int] = {}
        self._context_window = context_window
        self._reserve_tokens = reserve_tokens
        self._dagi_root = dagi_root
        self._project_path = project_path
        self._subtasks: list[dict] = []
        self._plan_title: str = ""
        self._emote: str = "default"

    def set_status(self, status: str) -> None:
        self._status = status
        self.refresh()

    def update_model(self, name: str) -> None:
        self._model_name = name
        self.refresh()

    def update_stats(self, inp: int, out: int, cost: float | None, thinking: int) -> None:
        self._input_tok, self._output_tok, self._cost, self._thinking_tok = inp, out, cost, thinking
        self.refresh()

    def update_context(self, buckets: dict[str, int]) -> None:
        self._buckets = dict(buckets)
        self.refresh()

    def set_project_path(self, path: Path) -> None:
        self._project_path = path
        self.refresh()

    def update_plan(self, subtasks: list[dict], title: str = "") -> None:
        self._subtasks = subtasks
        self._plan_title = title
        self.refresh()

    def update_emote(self, emote: str) -> None:
        self._emote = emote
        self.refresh()

    def render(self):
        panels = [self._logo_panel(), self._model_panel(), self._token_panel(),
                  self._context_panel(), self._plan_panel()]
        return Group(*[p for p in panels if p is not None])

    def _load_face(self) -> str:
        path = self._dagi_root / ".dagi" / "emotes" / f"{self._emote}.md"
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return _EMOTE_FALLBACK

    def _logo_panel(self):
        face = self._load_face()
        art = (
            "[#4da6ff]╭[/#4da6ff]"
            "[#4da6ff]≋[/#4da6ff][#1a6bbf]≋[/#1a6bbf]"
            "[#4da6ff]≋[/#4da6ff][#1a6bbf]≋[/#1a6bbf]"
            "[#4da6ff]≋[/#4da6ff][#1a6bbf]≋[/#1a6bbf]"
            "[#4da6ff]≋[/#4da6ff]"
            f"[#4da6ff]╮[/#4da6ff]\n"
            f"[#1a6bbf]≋[/#1a6bbf]{face}[#4da6ff]≋[/#4da6ff]"
        )
        return Panel(Text.from_markup(art, justify="center"), border_style="#4da6ff", padding=(0, 1))

    def _model_panel(self):
        if self._status == "running":
            dot, label = "[bold green]●[/bold green]", "Running"
        elif self._status == "paused":
            dot, label = "[bold yellow]⏸[/bold yellow]", "Paused"
        else:
            dot, label = "[dim]○[/dim]", "Idle"
        t = Table.grid(padding=(0, 1))
        t.add_row(f"{dot} {label}", "")
        t.add_row("[dim]model[/dim]", f"[bold]{self._model_name}[/bold]")
        return Panel(t, title="[bold]Status[/bold]", border_style="dim", padding=(0, 1))

    def _token_panel(self):
        t = Table.grid(padding=(0, 1))
        t.add_column(style="dim", width=8)
        t.add_column(justify="right")
        t.add_row("in", f"[cyan]~{self._input_tok:,}[/cyan]")
        if self._thinking_tok > 0:
            t.add_row("think", f"[magenta]~{self._thinking_tok:,}[/magenta]")
        t.add_row("out", f"[green]~{self._output_tok:,}[/green]")
        cost_str = f"${self._cost:.5f}" if self._cost is not None else "$—"
        t.add_row("cost", f"[yellow]{cost_str}[/yellow]")
        return Panel(t, title="[bold]Tokens[/bold]", border_style="dim", padding=(0, 1))

    def _context_panel(self):
        W = self._context_window
        t = Table.grid(padding=(0, 1))
        t.add_column(style="dim", width=9)
        t.add_column(justify="right", width=7)
        t.add_column(justify="right", width=4)

        sys_parts = _system_breakdown(self._dagi_root, self._project_path)
        SYS_COLOURS = {"sys-prompt": "white", "dagi/ag": "magenta", "proj/ag": "bright_magenta"}
        for key, col in SYS_COLOURS.items():
            n = sys_parts.get(key, 0)
            pct = f"{n / W * 100:.0f}%" if W else "—"
            t.add_row(key, f"[{col}]~{n:,}[/{col}]", f"[dim]{pct}[/dim]")

        MSG_COLOURS = {"summary": "cyan", "user": "blue", "assistant": "green", "tools": "yellow"}
        for key, col in MSG_COLOURS.items():
            n = self._buckets.get(key, 0)
            pct = f"{n / W * 100:.0f}%" if W else "—"
            t.add_row(key, f"[{col}]~{n:,}[/{col}]", f"[dim]{pct}[/dim]")

        res = self._reserve_tokens
        res_pct = f"{res / W * 100:.0f}%" if W else "—"
        t.add_row("reserve", f"[dim]~{res:,}[/dim]", f"[dim]{res_pct}[/dim]")

        total = sum(sys_parts.values()) + sum(self._buckets.values()) + res
        usage = total / W if W else 0
        uc = "red" if usage >= 0.95 else ("yellow" if usage >= 0.80 else "green")
        t.add_row("[bold]total[/bold]", f"[{uc}]~{total:,}[/{uc}]", f"[{uc}]{usage*100:.0f}%[/{uc}]")
        return Panel(t, title="[bold]Context[/bold]", border_style="dim", padding=(0, 1))

    def _plan_panel(self):
        if not self._subtasks:
            return None
        _STATUS_STYLE = {
            "pending":     ("[dim][ ][/dim]",      "dim"),
            "in_progress": ("[yellow][~][/yellow]", "yellow"),
            "complete":    ("[green][x][/green]",   "green"),
            "failed":      ("[red][!][/red]",       "red"),
        }
        t = Table.grid(padding=(0, 1))
        t.add_column(width=5)
        t.add_column()
        if self._plan_title:
            t.add_row("", Text(self._plan_title, style="dim", overflow="ellipsis"))
        for sub in self._subtasks:
            icon, name_style = _STATUS_STYLE.get(
                sub["status"], ("[dim]?[/dim]", "dim")
            )
            t.add_row(icon, Text(sub["name"], style=name_style, overflow="ellipsis"))
        return Panel(t, title="[bold]Plan[/bold]", border_style="dim", padding=(0, 1))
