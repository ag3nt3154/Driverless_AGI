"""
tui.py — Textual TUI for Driverless AGI.

Usage:
    conda run --no-capture-output -n dagi python tui.py
    conda run --no-capture-output -n dagi python tui.py --project /path/to/project
    conda run --no-capture-output -n dagi python tui.py --model deepseek-v4-pro-openrouter
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.message import Message
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import RichLog, TextArea

load_dotenv()

from agent.config_loader import (
    get_model_display_name,
    list_model_ids,
    load_cli_config,
    resolve_model_config,
)
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop

# ── Constants ─────────────────────────────────────────────────────────────────

_TOOL_COLOURS = {
    "bash": "yellow", "read": "blue", "write": "green",
    "edit": "magenta", "grep": "cyan", "find": "cyan",
    "skill": "bright_magenta", "cli_subagent": "bright_blue",
}
_SLASH_HELP = {
    "/help": "Show this list", "/exit": "Exit",
    "/clear": "Clear conversation context", "/wd": "Show or set working directory",
    "/compact": "Force-compact context", "/tools": "List tools",
    "/skills": "List skills", "/workflows": "List workflows",
    "/init": "Initialise .dagi/ scaffold", "/hist": "Show recent sessions",
    "/plan": "Enter plan mode", "/model": "Switch model  (/model <id>)",
}


def _colour(name: str) -> str:
    return _TOOL_COLOURS.get(name.lower(), "cyan")


def _truncate(text: str, n: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _resolve_option(raw: str, options: list[dict]) -> str:
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]
    for opt in options:
        if opt["label"].lower() == raw.lower():
            return opt["label"]
    return next((o["label"] for o in options if o.get("recommended")),
                options[0]["label"] if options else "")


def _breakdown(messages: list) -> dict[str, int]:
    """Estimate token counts for user/assistant/tools/summary buckets (chars // 4).
    System messages are excluded — accounted for by _system_breakdown() from source files.
    Compaction summaries (role=user, content starts with '[CONTEXT SUMMARY') are broken out
    into a separate 'summary' bucket so they don't inflate the user row."""
    buckets: dict[str, int] = {"summary": 0, "user": 0, "assistant": 0, "tools": 0}
    role_map = {"user": "user", "assistant": "assistant", "tool": "tools"}
    for m in messages:
        bucket = role_map.get(m.get("role", ""))
        if bucket is None:
            continue
        content = m.get("content") or ""
        if isinstance(content, list):
            text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        else:
            text = str(content)
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                text += tc.get("function", {}).get("arguments", "")
        toks = max(1, len(text) // 4)
        if bucket == "user" and text.startswith("[CONTEXT SUMMARY"):
            buckets["summary"] += toks
        else:
            buckets[bucket] += toks
    return buckets


def _system_breakdown(dagi_root: Path, project_path: Path) -> dict[str, int]:
    """Estimate token counts for the three system message components from source files."""
    def _toks(path: Path) -> int:
        return max(1, len(path.read_text(encoding="utf-8")) // 4) if path.exists() else 0

    return {
        "sys-prompt": (
            _toks(dagi_root / ".dagi" / "prompts" / "main" / "main_system.md")
            + _toks(dagi_root / "soul.md")
        ),
        "dagi/ag": _toks(dagi_root / ".dagi" / "agents.md"),
        "proj/ag": _toks(project_path / ".dagi" / "agents.md"),
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

class _Stats:
    def __init__(self) -> None:
        self.input_tok = 0
        self.output_tok = 0
        self.thinking_tok = 0
        self.cost: float | None = None
        self.tool_counts: dict[str, int] = {}

    def update_tokens(self, inp: int, out: int, cost: float | None, thinking: int = 0) -> None:
        self.input_tok += inp
        self.output_tok += out
        self.thinking_tok += thinking
        if cost is not None:
            self.cost = (self.cost or 0.0) + cost

    def record_tool(self, name: str) -> None:
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1


# ── ConversationPane ──────────────────────────────────────────────────────────

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


# ── PromptInput ───────────────────────────────────────────────────────────────

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
        elif event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            self.insert("\n")


# ── Sidebar ───────────────────────────────────────────────────────────────────

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

    def render(self):
        panels = [self._model_panel(), self._token_panel(), self._context_panel(),
                  self._plan_panel()]
        return Group(*[p for p in panels if p is not None])

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


# ── DagiApp ───────────────────────────────────────────────────────────────────

class DagiApp(App[None]):
    CSS = """
    Screen   { layout: vertical; }
    #main-row { height: 1fr; }
    ConversationPane { width: 75%; }
    Sidebar  { width: 25%; border-left: solid $panel; padding: 0 1; }
    #prompt  { dock: bottom; height: 5; border-top: solid $panel; }
    """
    BINDINGS = [("ctrl+c", "quit", "Quit"), ("escape", "pause", "Pause")]

    def __init__(self, model_id: str | None, project: str | None, verbose: bool) -> None:
        super().__init__()
        self._project_path = Path(project).resolve() if project else Path.cwd()
        self._model_id = model_id
        self._verbose = verbose
        self._model_name = get_model_display_name(model_id)
        self._stats = _Stats()
        self._config: AgentConfig | None = None
        self._active_loop: AgentLoop | None = None
        self._worker: threading.Thread | None = None
        self._pending_ask: tuple | None = None
        self._current_loop_ref: list = []
        self._skill_map: dict = {}
        self._workflow_map: dict = {}

    def compose(self) -> ComposeResult:
        cfg = resolve_model_config(self._model_id)
        dagi_root = Path(__file__).parent
        with Horizontal(id="main-row"):
            yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
            yield Sidebar(
                self._model_name, cfg.context_window, cfg.reserve_tokens,
                dagi_root=dagi_root, project_path=self._project_path,
            )
        yield PromptInput(id="prompt")

    def on_mount(self) -> None:
        self._config = resolve_model_config(self._model_id)
        self._config.project_path = self._project_path
        self._load_maps()
        conv = self.query_one(ConversationPane)
        conv.write(Text(
            f"Driverless AGI  ·  {self._model_name}  ·  {self._project_path}",
            style="bold cyan",
        ))
        conv.write(Text("Type /help for commands · /exit to leave", style="dim"))
        self.query_one("#prompt", PromptInput).focus()
        self.set_interval(2.0, self._poll_plan)

    def _load_maps(self) -> None:
        from agent.skills import SkillLoader
        from agent.workflows import WorkflowLoader
        dagi_root = Path(__file__).parent
        skill_roots = [dagi_root / ".dagi" / "skills", self._project_path / ".dagi" / "skills"]
        self._skill_map = {
            f"/{s.name}": s for s in SkillLoader().load_all(skill_roots, dagi_root=dagi_root)
        }
        self._workflow_map = {
            f"/{w.name}": w for w in WorkflowLoader().load_all(
                [self._project_path / ".dagi" / "workflow"]
            )
        }

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        if self._pending_ask is not None:
            ask_evt, container, options, _ = self._pending_ask
            self._pending_ask = None
            container.append(_resolve_option(raw, options))
            ask_evt.set()
            return
        if (
            self._worker and self._worker.is_alive()
            and self._current_loop_ref
            and not self._current_loop_ref[0]._pause_event.is_set()
        ):
            loop = self._current_loop_ref[0]
            conv = self.query_one(ConversationPane)
            conv.write(Panel(raw, title="[bold cyan]You[/bold cyan]",
                             title_align="left", border_style="cyan", padding=(0, 1)))
            self.query_one("#prompt", PromptInput).disabled = True
            self.query_one(Sidebar).set_status("running")
            loop.inject_and_resume(raw)
            return
        if raw.lower() in ("exit", "quit", "q"):
            self.exit()
            return
        if raw.startswith("/"):
            self._handle_slash(raw)
        else:
            self._dispatch_agent(raw)

    def _handle_slash(self, raw: str) -> None:  # noqa: C901
        conv = self.query_one(ConversationPane)
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd == "/exit":
            self.exit()
        elif cmd == "/clear":
            conv.clear()
            self._active_loop = None
            self._stats = _Stats()
            self.query_one(Sidebar).update_stats(0, 0, None, 0)
            conv.append_info("[green]✓ Context cleared[/green]")
        elif cmd == "/model":
            self._cmd_model(arg)
        elif cmd == "/wd":
            self._cmd_wd(arg)
        elif cmd == "/compact":
            self._cmd_compact()
        elif cmd == "/plan":
            self._dispatch_agent(f"Invoke the 'plan-work-review' skill. {arg or ''}")
        elif cmd == "/help":
            self._cmd_help()
        elif cmd == "/tools":
            self._cmd_tools()
        elif cmd == "/skills":
            self._cmd_skills()
        elif cmd == "/workflows":
            self._cmd_workflows()
        elif cmd == "/hist":
            self._cmd_hist(arg)
        elif cmd == "/init":
            from cli import _cmd_init
            _cmd_init(self._project_path)
        elif cmd in self._skill_map:
            self._dispatch_agent(f"Invoke the '{self._skill_map[cmd].name}' skill. {arg or ''}")
        elif cmd in self._workflow_map:
            from tools.workflow import load_workflow_content
            wf = load_workflow_content(
                self._workflow_map[cmd].name,
                [self._project_path / ".dagi" / "workflow"],
            )
            self._dispatch_agent(wf + (f"\n\nAdditional instructions: {arg}" if arg else ""))
        else:
            self.query_one(ConversationPane).append_info(
                f"[red]Unknown command:[/red] {cmd}  · type [bold]/help[/bold]"
            )

    def _cmd_help(self) -> None:
        conv = self.query_one(ConversationPane)
        tbl = Table(title="Commands", border_style="dim", padding=(0, 1))
        tbl.add_column("Command", style="bold cyan")
        tbl.add_column("Description", style="dim")
        for cmd, desc in _SLASH_HELP.items():
            tbl.add_row(cmd, desc)
        conv.write(tbl)

    def _cmd_model(self, arg: str | None) -> None:
        conv = self.query_one(ConversationPane)
        sidebar = self.query_one(Sidebar)
        if not arg:
            ids = list_model_ids()
            tbl = Table(title="Available Models", border_style="dim", padding=(0, 1))
            tbl.add_column("ID", style="bold")
            tbl.add_column("")
            for mid in ids:
                tbl.add_row(mid, "[bold green]◀ active[/bold green]" if mid == self._model_id else "")
            conv.write(tbl)
            return
        if arg not in list_model_ids():
            conv.append_info(f"[red]Unknown model:[/red] {arg}")
            return
        self._model_id = arg
        self._model_name = get_model_display_name(arg)
        self._config = resolve_model_config(arg)
        self._config.project_path = self._project_path
        sidebar.update_model(self._model_name)
        sidebar._context_window = self._config.context_window
        sidebar._reserve_tokens = self._config.reserve_tokens
        sidebar.refresh()
        conv.append_info(f"[bold cyan]⇄ Model →[/bold cyan] [bold]{self._model_name}[/bold]")

    def _cmd_wd(self, arg: str | None) -> None:
        conv = self.query_one(ConversationPane)
        if not arg:
            conv.append_info(f"[bold cyan]Working directory:[/bold cyan] {self._project_path}")
            return
        new = Path(arg).expanduser()
        if not new.is_absolute():
            new = self._project_path / new
        new = new.resolve()
        if not new.is_dir():
            conv.append_info(f"[red]Not a directory:[/red] {new}")
            return
        self._project_path = new
        if self._config:
            self._config.project_path = new
        self._active_loop = None
        self._load_maps()
        self.query_one(Sidebar).set_project_path(new)
        conv.append_info(f"[green]✓ Working directory →[/green] {new}")

    def _cmd_compact(self) -> None:
        conv = self.query_one(ConversationPane)
        if self._active_loop is None:
            conv.append_info("[dim]Nothing to compact — no active conversation.[/dim]")
            return
        result = self._active_loop.compact_tool.compact(force=True)
        if result.did_compact:
            self._stats.update_tokens(
                result.summary_input_tokens, result.summary_output_tokens, result.summary_cost
            )
            conv.append_info(
                f"[yellow]⚡ Context compacted — removed {result.removed_count} messages, "
                f"kept {len(self._active_loop._messages)}[/yellow]"
            )
        else:
            conv.append_info("[dim]Nothing to compact.[/dim]")

    def _cmd_tools(self) -> None:
        conv = self.query_one(ConversationPane)
        if self._active_loop is None:
            conv.append_info("[dim]No active session — start a task first.[/dim]")
            return
        tbl = Table(title="Registered Tools", border_style="dim", padding=(0, 1))
        tbl.add_column("Name", style="bold green")
        tbl.add_column("Description", style="dim")
        for name, desc in self._active_loop.registry.list_tools():
            tbl.add_row(name, desc)
        conv.write(tbl)

    def _cmd_skills(self) -> None:
        conv = self.query_one(ConversationPane)
        skills = list(self._skill_map.values())
        if not skills:
            conv.append_info("[dim]No skills loaded.[/dim]")
            return
        tbl = Table(title="Loaded Skills", border_style="dim", padding=(0, 1))
        tbl.add_column("Name", style="bold bright_magenta")
        tbl.add_column("Description", style="dim")
        for s in sorted(skills, key=lambda x: x.name):
            tbl.add_row(s.name, s.description or "—")
        conv.write(tbl)

    def _cmd_workflows(self) -> None:
        conv = self.query_one(ConversationPane)
        workflows = list(self._workflow_map.values())
        if not workflows:
            conv.append_info("[dim]No workflows loaded.[/dim]")
            return
        tbl = Table(title="Loaded Workflows", border_style="dim", padding=(0, 1))
        tbl.add_column("Command", style="bold yellow")
        tbl.add_column("Description", style="dim")
        for w in sorted(workflows, key=lambda x: x.name):
            tbl.add_row(f"/{w.name}", w.description or "—")
        conv.write(tbl)

    def _cmd_hist(self, arg: str | None) -> None:
        from hist import run as hist_run
        try:
            n = int(arg) if arg else 20
        except ValueError:
            n = 20
        hist_run(project=self._project_path, n=n)

    def action_pause(self) -> None:
        if not (self._worker and self._worker.is_alive()):
            return
        if self._pending_ask is not None:
            return
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        if not loop._pause_event.is_set():
            return  # already paused
        loop.pause()
        self.query_one(Sidebar).set_status("paused")
        self.query_one(ConversationPane).append_info(
            "[yellow]⏸ Paused — type a message and press Enter to continue[/yellow]"
        )
        self._enable_input()

    def _dispatch_agent(self, task: str) -> None:
        if self._worker and self._worker.is_alive():
            self.query_one(ConversationPane).append_info("[yellow]Agent is already running.[/yellow]")
            return
        conv = self.query_one(ConversationPane)
        conv.write(Panel(task, title="[bold cyan]You[/bold cyan]",
                         title_align="left", border_style="cyan", padding=(0, 1)))
        self.query_one("#prompt", PromptInput).disabled = True
        self._current_loop_ref = []
        callbacks = self._build_callbacks(self._current_loop_ref)
        self._worker = threading.Thread(
            target=self._agent_work, args=(task, callbacks, self._current_loop_ref), daemon=True
        )
        self._worker.start()

    def _agent_work(self, task: str, callbacks: AgentCallbacks, loop_ref: list) -> None:
        sidebar = self.query_one(Sidebar)
        self.call_from_thread(sidebar.set_status, "running")
        try:
            tracker = self._active_loop.tracker if self._active_loop else None
            initial = self._active_loop._messages if self._active_loop else None
            loop = AgentLoop(self._config, callbacks, initial_messages=initial, _tracker=tracker)
            loop_ref.append(loop)
            loop.run(task)
            self._active_loop = loop
        except Exception as exc:
            self.call_from_thread(self.query_one(ConversationPane).append_error, str(exc))
        finally:
            self.call_from_thread(sidebar.set_status, "idle")
            self.call_from_thread(self._enable_input)

    def _poll_plan(self) -> None:
        from tools._plan_parser import parse_subtask_statuses
        sidebar = self.query_one(Sidebar)
        if not self._current_loop_ref:
            return
        loop = self._current_loop_ref[0]
        path = loop.config.plan_file or loop.config.active_plan_file
        if not path:
            sidebar.update_plan([])
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            return
        subtasks = parse_subtask_statuses(text)
        title = ""
        for line in text.splitlines():
            if line.startswith("# Plan"):
                title = line.lstrip("# ").removeprefix("Plan — ").strip()
                break
        sidebar.update_plan(subtasks, title)

    def _enable_input(self) -> None:
        inp = self.query_one("#prompt", PromptInput)
        inp.disabled = False
        inp.focus()

    def _show_ask_user(
        self,
        question: str,
        options: list[dict],
        timeout: float | None,
        evt: threading.Event,
        container: list,
    ) -> None:
        self.query_one(ConversationPane).append_question(question, options, timeout)
        self._pending_ask = (evt, container, options, timeout)

    def _build_callbacks(self, loop_ref: list) -> AgentCallbacks:
        sidebar = self.query_one(Sidebar)
        conv = self.query_one(ConversationPane)
        stats = self._stats
        verbose = self._verbose

        def on_tool_start(name, _desc, args):
            self.call_from_thread(conv.append_tool_start, name, args, verbose)

        def on_tool_end(name, result):
            stats.record_tool(name)
            self.call_from_thread(conv.append_tool_end, name, result, verbose)

        def on_assistant_text(text):
            if text.strip():
                self.call_from_thread(conv.append_assistant, text)

        def on_token_update(inp, out, cost, thinking=0):
            stats.update_tokens(inp, out, cost, thinking)
            self.call_from_thread(
                sidebar.update_stats, stats.input_tok, stats.output_tok, stats.cost, stats.thinking_tok
            )

        def on_reasoning(text):
            if text.strip():
                self.call_from_thread(conv.append_reasoning, text)

        def on_compaction(kept, removed):
            self.call_from_thread(conv.append_info,
                f"[yellow]⚡ Context compacted — removed {removed} messages, kept {kept}[/yellow]")
            if loop_ref:
                self.call_from_thread(sidebar.update_context, _breakdown(loop_ref[0]._messages))

        def on_model_switch(from_name, to_name):
            self.call_from_thread(conv.append_info,
                f"[bold cyan]⇄ Model switch:[/bold cyan] [dim]{from_name}[/dim] → [bold]{to_name}[/bold]")
            self.call_from_thread(sidebar.update_model, to_name)

        def on_error(exc):
            self.call_from_thread(conv.append_error, str(exc))

        def on_api_call(messages):
            self.call_from_thread(sidebar.update_context, _breakdown(messages))

        def on_ask_user(question, options, timeout):
            evt = threading.Event()
            container: list = []
            self.call_from_thread(self._show_ask_user, question, options, timeout, evt, container)
            safety = (timeout + 60) if timeout is not None else None
            evt.wait(timeout=safety)
            if container:
                return container[0]
            return next((o["label"] for o in options if o.get("recommended")),
                        options[0]["label"] if options else "")

        return AgentCallbacks(
            on_tool_start=on_tool_start, on_tool_end=on_tool_end,
            on_assistant_text=on_assistant_text, on_token_update=on_token_update,
            on_iteration=lambda _: None, on_done=lambda _: None, on_error=on_error,
            on_api_call=on_api_call, on_reasoning=on_reasoning,
            on_compaction=on_compaction, on_model_switch=on_model_switch,
            on_ask_user=on_ask_user,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

_cli = typer.Typer(name="dagi-tui", add_completion=False)


@_cli.command()
def main(
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model ID from config.yaml"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full tool output"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Project directory"),
) -> None:
    DagiApp(model_id=model, project=project, verbose=verbose).run()


if __name__ == "__main__":
    _cli()
