from __future__ import annotations

from pathlib import Path

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.widget import Widget

from agent.process_state import ProcessSnapshot

from .utils import _system_breakdown


def _path_tail(path: Path | str, max_chars: int = 36) -> str:
    """Return the rightmost portion of a path string, prefixed with … when truncated."""
    s = str(path)
    return s if len(s) <= max_chars else "…" + s[-(max_chars - 1):]


class Sidebar(Widget):
    """Fixed-height top header: status/emote, token+context, plan — three columns."""

    DEFAULT_CSS = "Sidebar { overflow-x: hidden; overflow-y: auto; }"

    def __init__(
        self,
        model_name: str,
        context_window: int,
        reserve_tokens: int,
        dagi_root: Path,
        project_path: Path,
        memory_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._status = "idle"
        self._model_name = model_name
        self._input_tok = 0
        self._output_tok = 0
        self._thinking_tok = 0
        self._cached_tok = 0
        self._cost: float | None = None
        self._buckets: dict[str, int] = {}
        self._context_window = context_window
        self._reserve_tokens = reserve_tokens
        self._dagi_root = dagi_root
        self._project_path = project_path
        self._memory_root = memory_root
        self._subtasks: list[dict] = []
        self._plan_title: str = ""
        self._emote_display: str = "process=idle"
        self._emote_name: str = ""
        self._process_state: str = "idle"

    def set_status(self, status: str) -> None:
        self._status = status
        self.refresh()

    def update_model(self, name: str) -> None:
        self._model_name = name
        self.refresh()

    def update_stats(
        self, inp: int, out: int, cost: float | None, thinking: int, cached: int = 0
    ) -> None:
        self._input_tok = inp
        self._output_tok = out
        self._cost = cost
        self._thinking_tok = thinking
        self._cached_tok = cached
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

    def update_expression(self, snapshot) -> None:
        del snapshot

    def update_process_state(self, snapshot: ProcessSnapshot) -> None:
        self._process_state = snapshot.state
        self._emote_display = f"process={self._process_state}"
        self.refresh()

    def render(self):
        return Group(
            self._status_col(),
            Text(""),
            self._tokens_context_col(),
            Text(""),
            self._plan_col(),
        )

    def _status_col(self) -> Group:
        face = self._emote_display
        if self._status == "running":
            dot = "[bold green]●[/bold green]"
            status_mu = "[bold green]running[/bold green]"
        elif self._status == "paused":
            dot = "[bold yellow]⏸[/bold yellow]"
            status_mu = "[bold yellow]paused[/bold yellow]"
        else:
            dot = "[dim]○[/dim]"
            status_mu = "[dim]idle[/dim]"

        info = Table.grid(padding=(0, 1))
        info.add_column(style="dim", no_wrap=True)
        info.add_column(no_wrap=True)
        info.add_row(
            Text.from_markup(f"{dot} {status_mu}"),
            Text.from_markup(f"[bold]{self._model_name}[/bold]"),
        )
        info.add_row("cwd", _path_tail(self._project_path))
        info.add_row("app", _path_tail(self._dagi_root))
        if self._memory_root is not None:
            info.add_row("mem", _path_tail(self._memory_root))

        face_items = [Text(face, style="#4da6ff")]
        if self._emote_name:
            face_items.append(Text(self._emote_name, style="#4da6ff"))
        face_group = Group(*face_items)
        return Group(face_group, info)

    def _tokens_context_col(self) -> Group:
        cost_str = f"${self._cost:.5f}" if self._cost is not None else "$—"
        think_part = (
            f"  [dim]think[/dim] [magenta]~{self._thinking_tok:,}[/magenta]"
            if self._thinking_tok else ""
        )
        cache_part = (
            f"  [dim]cache[/dim] [bright_cyan]~{self._cached_tok:,}[/bright_cyan]"
            if self._cached_tok else ""
        )
        tok_line = Text.from_markup(
            f"[dim]in[/dim] [cyan]~{self._input_tok:,}[/cyan]"
            f"  [dim]out[/dim] [green]~{self._output_tok:,}[/green]"
            f"{think_part}{cache_part}  [yellow]{cost_str}[/yellow]"
        )

        W = self._context_window
        sys_parts = _system_breakdown(self._dagi_root, self._project_path)

        def _pct(n: int) -> str:
            return f"{n / W * 100:.0f}%" if W else "—"

        ctx = Table.grid(padding=(0, 1))
        ctx.add_column(style="dim", width=9)
        ctx.add_column(justify="right", width=7)
        ctx.add_column(justify="right", width=4)

        SYS_COLOURS = {"sys-prompt": "white", "dagi/ag": "magenta", "proj/ag": "bright_magenta"}
        for key, col in SYS_COLOURS.items():
            n = sys_parts.get(key, 0)
            ctx.add_row(key, f"[{col}]~{n:,}[/{col}]", f"[dim]{_pct(n)}[/dim]")

        MSG_COLOURS = {"summary": "cyan", "user": "blue", "assistant": "green", "tools": "yellow"}
        for key, col in MSG_COLOURS.items():
            n = self._buckets.get(key, 0)
            ctx.add_row(key, f"[{col}]~{n:,}[/{col}]", f"[dim]{_pct(n)}[/dim]")

        res = self._reserve_tokens
        ctx.add_row("reserve", f"[dim]~{res:,}[/dim]", f"[dim]{_pct(res)}[/dim]")

        total = sum(sys_parts.values()) + sum(self._buckets.values()) + res
        usage = total / W if W else 0
        uc = "red" if usage >= 0.95 else ("yellow" if usage >= 0.80 else "green")
        ctx.add_row(
            "[bold]total[/bold]",
            f"[{uc}]~{total:,}[/{uc}]",
            f"[{uc}]{usage*100:.0f}%[/{uc}]",
        )

        return Group(tok_line, ctx)

    def _plan_col(self) -> Table | Text:
        if not self._subtasks:
            return Text("")
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
            icon, name_style = _STATUS_STYLE.get(sub["status"], ("[dim]?[/dim]", "dim"))
            t.add_row(icon, Text(sub["name"], style=name_style, overflow="ellipsis"))
        return t
