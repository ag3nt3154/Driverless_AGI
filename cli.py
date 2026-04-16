"""
cli.py — Rich interactive CLI for Driverless AGI.

Usage (always use --no-capture-output for real-time output):
    conda run --no-capture-output -n dagi python cli.py
    conda run --no-capture-output -n dagi python cli.py "list files in src/"
    conda run --no-capture-output -n dagi python cli.py --sync "run tests"
    conda run --no-capture-output -n dagi python cli.py --verbose
    echo "task" | conda run --no-capture-output -n dagi python cli.py
"""
from __future__ import annotations

import queue
import sys
import textwrap
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from dotenv import load_dotenv

load_dotenv()

from agent.config_loader import (
    CliConfig,
    get_model_display_name,
    load_cli_config,
    resolve_model_config,
)
from agent.loop import AgentCallbacks, AgentLoop

console = Console()
app = typer.Typer(
    name="dagi",
    help="[bold cyan]Driverless AGI[/bold cyan] — an agentic coding assistant.",
    rich_markup_mode="rich",
    add_completion=False,
)

# ── Rendering constants ───────────────────────────────────────────────────────

_TOOL_COLOURS = {
    "bash": "yellow",
    "read": "blue",
    "write": "green",
    "edit": "magenta",
    "grep": "cyan",
    "find": "cyan",
    "skill": "bright_magenta",
}
_MAX_COMPACT_LEN = 120


def _colour(tool_name: str) -> str:
    return _TOOL_COLOURS.get(tool_name.lower(), "cyan")


def _truncate(text: str, length: int = _MAX_COMPACT_LEN) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= length else text[:length] + "…"


# ── Stats accumulator ─────────────────────────────────────────────────────────

class _Stats:
    def __init__(self) -> None:
        self.input_tok = 0
        self.output_tok = 0
        self.thinking_tok = 0
        self.cost: float | None = None
        self.tool_counts: dict[str, int] = {}

    def update_tokens(self, inp: int, out: int, cost: float | None, thinking: int = 0) -> None:
        self.input_tok    += inp
        self.output_tok   += out
        self.thinking_tok += thinking
        if cost is not None:
            self.cost = (self.cost or 0.0) + cost

    def record_tool(self, name: str) -> None:
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1

    def footer(self, model_name: str, cwd: Path | None = None) -> str:
        parts = [model_name]
        tok_seg = f"in {self.input_tok:,}"
        if self.thinking_tok > 0:
            tok_seg += f"  think {self.thinking_tok:,}"
        tok_seg += f"  out {self.output_tok:,}"
        parts.append(tok_seg)
        if self.cost is not None:
            parts.append(f"${self.cost:.5f}")
        if cwd is not None:
            try:
                display = "~/" + str(cwd.relative_to(Path.home()))
            except ValueError:
                display = str(cwd)
            parts.append(display)
        return "  ·  ".join(parts)


# ── Sync callbacks (fire directly on the agent thread) ───────────────────────

def _make_sync_callbacks(
    stats: _Stats, model_name: str, verbose: bool,
    get_cwd: Callable[[], Path],
) -> AgentCallbacks:
    def on_tool_start(name: str, _desc: str, args: str) -> None:
        col = _colour(name)
        args_display = args if verbose else _truncate(args)
        console.print(
            Panel(
                f"[dim]{args_display}[/dim]",
                title=f"[{col}]▶ {name}[/{col}]",
                title_align="left",
                border_style=col,
                padding=(0, 1),
            )
        )

    def on_tool_end(name: str, result: str) -> None:
        stats.record_tool(name)
        col = _colour(name)
        if verbose:
            console.print(
                Panel(
                    result,
                    title=f"[{col}]✓ {name}[/{col}]",
                    title_align="left",
                    border_style="dim",
                    padding=(0, 1),
                )
            )
        else:
            console.print(f"  [dim green]✓ {len(result)} chars[/dim green]")

    def on_assistant_text(text: str) -> None:
        if text.strip():
            console.print(Markdown(text))

    def on_token_update(inp: int, out: int, cost: float | None, thinking: int = 0) -> None:
        stats.update_tokens(inp, out, cost, thinking)

    def on_compaction(kept: int, removed: int) -> None:
        console.print(
            f"[yellow]⚡ Context compacted — removed {removed} messages, kept {kept}[/yellow]"
        )

    def on_reasoning(text: str) -> None:
        if text.strip():
            console.print(
                Panel(
                    f"[dim italic]{text}[/dim italic]",
                    title="[dim bold]🧠 Thinking[/dim bold]",
                    title_align="left",
                    border_style="dim",
                    padding=(0, 1),
                )
            )

    def on_error(exc: Exception) -> None:
        console.print_exception()

    def on_done(_result: str) -> None:
        console.print(f"[dim]{stats.footer(model_name, cwd=get_cwd())}[/dim]")

    return AgentCallbacks(
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text,
        on_token_update=on_token_update,
        on_compaction=on_compaction,
        on_reasoning=on_reasoning,
        on_error=on_error,
        on_done=on_done,
    )


# ── Threaded callbacks (post events to queue; main thread renders) ────────────

_EVT_TOOL_START = "tool_start"
_EVT_TOOL_END   = "tool_end"
_EVT_ASSISTANT  = "assistant"
_EVT_TOKENS     = "tokens"
_EVT_COMPACTION = "compaction"
_EVT_REASONING  = "reasoning"
_EVT_ERROR      = "error"
_EVT_DONE       = "done"


def _make_threaded_callbacks(q: queue.Queue, stats: _Stats) -> AgentCallbacks:
    def put(tag: str, *payload) -> None:
        q.put((tag, *payload))

    return AgentCallbacks(
        on_tool_start     = lambda n, d, a: put(_EVT_TOOL_START, n, d, a),
        on_tool_end       = lambda n, r:    put(_EVT_TOOL_END, n, r),
        on_assistant_text = lambda t:       put(_EVT_ASSISTANT, t),
        on_token_update   = lambda i, o, c, t=0: put(_EVT_TOKENS, i, o, c, t),
        on_compaction     = lambda k, r:    put(_EVT_COMPACTION, k, r),
        on_reasoning      = lambda t:       put(_EVT_REASONING, t),
        on_error          = lambda e:       put(_EVT_ERROR, str(e)),
        on_done           = lambda r:       put(_EVT_DONE, r),
    )


def _render_queue(
    q: queue.Queue,
    stats: _Stats,
    model_name: str,
    verbose: bool,
    get_cwd: Callable[[], Path],
) -> None:
    """Drain the event queue and render output. Runs on the main thread."""
    spinner_text = Text("Thinking…", style="dim")
    spinner = Spinner("dots", text=spinner_text)

    with Live(spinner, console=console, refresh_per_second=10, transient=True):
        while True:
            try:
                event = q.get(timeout=0.05)
            except queue.Empty:
                continue

            if event is None:
                break

            tag, *payload = event

            if tag == _EVT_TOOL_START:
                name, _desc, args = payload
                col = _colour(name)
                args_display = args if verbose else _truncate(args)
                console.print(
                    Panel(
                        f"[dim]{args_display}[/dim]",
                        title=f"[{col}]▶ {name}[/{col}]",
                        title_align="left",
                        border_style=col,
                        padding=(0, 1),
                    )
                )
                spinner_text.plain = f"Running {name}…"

            elif tag == _EVT_TOOL_END:
                name, result = payload
                stats.record_tool(name)
                col = _colour(name)
                if verbose:
                    console.print(
                        Panel(
                            result,
                            title=f"[{col}]✓ {name}[/{col}]",
                            title_align="left",
                            border_style="dim",
                            padding=(0, 1),
                        )
                    )
                else:
                    console.print(f"  [dim green]✓ {len(result)} chars[/dim green]")
                spinner_text.plain = "Thinking…"

            elif tag == _EVT_ASSISTANT:
                text = payload[0]
                if text.strip():
                    console.print(Markdown(text))

            elif tag == _EVT_TOKENS:
                inp, out, cost = payload[0], payload[1], payload[2]
                thinking = payload[3] if len(payload) > 3 else 0
                stats.update_tokens(inp, out, cost, thinking)

            elif tag == _EVT_COMPACTION:
                kept, removed = payload
                console.print(
                    f"[yellow]⚡ Context compacted — removed {removed} messages, kept {kept}[/yellow]"
                )

            elif tag == _EVT_REASONING:
                text = payload[0]
                if text.strip():
                    console.print(
                        Panel(
                            f"[dim italic]{text}[/dim italic]",
                            title="[dim bold]🧠 Thinking[/dim bold]",
                            title_align="left",
                            border_style="dim",
                            padding=(0, 1),
                        )
                    )

            elif tag == _EVT_ERROR:
                err_msg = payload[0] if payload and payload[0] else "Unknown error"
                console.print(f"[bold red]Error:[/bold red] {err_msg}")

            elif tag == _EVT_DONE:
                console.print(f"[dim]{stats.footer(model_name, cwd=get_cwd())}[/dim]")


# ── Agent runner ──────────────────────────────────────────────────────────────

def _run_task(
    task: str,
    conversation_msgs: list,
    cli_cfg: CliConfig,
    model_id: str | None,
    model_name: str,
    verbose: bool,
    force_sync: bool,
    stats: _Stats,
    project_path: Path,
) -> tuple[list, "AgentLoop"]:
    """Run one agent task. Returns (updated conversation messages, loop) for multi-turn."""
    config = resolve_model_config(model_id)
    config.project_path = project_path
    use_threaded = (cli_cfg.threading == "threaded") and not force_sync

    get_cwd: Callable[[], Path] = lambda: project_path

    if use_threaded:
        q: queue.Queue = queue.Queue()
        callbacks = _make_threaded_callbacks(q, stats)
        loop = AgentLoop(
            config, callbacks,
            initial_messages=conversation_msgs or None,
        )

        def _agent_thread() -> None:
            try:
                loop.run(task)
            except Exception:
                pass  # on_error callback already posted the error event
            finally:
                q.put(None)

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(_agent_thread)
            _render_queue(q, stats, model_name, verbose, get_cwd)
    else:
        callbacks = _make_sync_callbacks(stats, model_name, verbose, get_cwd)
        loop = AgentLoop(
            config, callbacks,
            initial_messages=conversation_msgs or None,
        )
        try:
            loop.run(task)
        except Exception:
            console.print_exception()

    return loop._messages, loop


# ── Slash commands ─────────────────────────────────────────────────────────────

_SLASH_COMMANDS: dict[str, str] = {
    "/help":    "Show this list of commands",
    "/exit":    "Exit the session (same as exit/quit/q)",
    "/wd":      "Show or set working directory  (/wd <path>)",
    "/compact": "Force-compact conversation context into a summary",
    "/tools":   "List all registered agent tools",
    "/skills":  "List all loaded skills",
    "/init":    "Initialise .dagi/ scaffold in the project directory",
}

_EXIT_SENTINEL = object()  # returned by /exit handler to signal the REPL to break


def _cmd_help() -> None:
    table = Table(title="Slash Commands", border_style="dim", padding=(0, 1))
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="dim")
    for cmd, desc in _SLASH_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)


def _cmd_tools(loop: "AgentLoop | None" = None) -> None:
    if loop is None:
        console.print("[dim]No active session — start a task first.[/dim]")
        return
    tools = loop.registry.list_tools()
    table = Table(title="Registered Tools", border_style="dim", padding=(0, 1))
    table.add_column("Name", style="bold green")
    table.add_column("Description", style="dim")
    for name, desc in tools:
        table.add_row(name, desc)
    console.print(table)


def _cmd_skills(loop: "AgentLoop | None" = None) -> None:
    if loop is None:
        console.print("[dim]No active session — start a task first.[/dim]")
        return
    skills = loop.skills
    if not skills:
        console.print("[dim]No skills loaded.[/dim]")
        return
    table = Table(title="Loaded Skills", border_style="dim", padding=(0, 1))
    table.add_column("Name", style="bold bright_magenta")
    table.add_column("Description", style="dim")
    table.add_column("Source", style="dim italic")
    for s in sorted(skills, key=lambda x: x.name):
        table.add_row(s.name, s.description or "—", s.source)
    console.print(table)


def _cmd_init(project_path: Path) -> None:
    dagi_dir = project_path / ".dagi"
    skills_dir = dagi_dir / "skills"
    agents_file = dagi_dir / "AGENTS.md"

    created: list[str] = []

    skills_dir.mkdir(parents=True, exist_ok=True)
    if not agents_file.exists():
        agents_file.write_text("", encoding="utf-8")
        created.append(str(agents_file.relative_to(project_path)))

    if created:
        console.print(f"[green]✓ Initialised[/green] [dim]{dagi_dir}[/dim]")
        for p in created:
            console.print(f"  [dim]created:[/dim] {p}")
    else:
        console.print(f"[dim]Already initialised: {dagi_dir}[/dim]")


def _cmd_wd(arg: str | None, current_path: Path) -> Path:
    """Show or change the working directory. Returns the (possibly new) path."""
    if not arg:
        console.print(f"[bold cyan]Working directory:[/bold cyan] {current_path}")
        return current_path

    new_path = Path(arg).expanduser()
    if not new_path.is_absolute():
        new_path = current_path / new_path
    new_path = new_path.resolve()

    if not new_path.exists():
        console.print(f"[red]Error:[/red] path does not exist: {new_path}")
        return current_path
    if not new_path.is_dir():
        console.print(f"[red]Error:[/red] not a directory: {new_path}")
        return current_path

    console.print(f"[green]✓ Working directory →[/green] {new_path}")
    console.print("[dim]Conversation history reset — new context will use the updated root.[/dim]")
    return new_path


def _cmd_compact(
    active_loop: "AgentLoop | None",
    stats: _Stats,
) -> None:
    if active_loop is None:
        console.print("[dim]Nothing to compact — no active conversation.[/dim]")
        return

    result = active_loop.compact_tool.compact(force=True)

    if result.did_compact:
        console.print(
            f"[yellow]⚡ Context compacted — removed {result.removed_count} messages, "
            f"kept {len(active_loop._messages)}[/yellow]"
        )
        stats.update_tokens(
            result.summary_input_tokens,
            result.summary_output_tokens,
            result.summary_cost,
        )
    else:
        console.print("[dim]Nothing to compact.[/dim]")


def _handle_slash_command(
    raw: str,
    conversation_msgs: list,
    model_id: str | None,
    stats: _Stats,
    project_path: Path,
    active_loop: "AgentLoop | None" = None,
) -> tuple[object | None, Path]:
    """Dispatch a slash command. Returns (result, project_path).
    result is _EXIT_SENTINEL to signal REPL exit, or None otherwise.
    project_path may be updated by /wd.
    """
    parts = raw.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/exit":
        return _EXIT_SENTINEL, project_path
    elif cmd == "/help":
        _cmd_help()
    elif cmd == "/wd":
        arg = parts[1].strip() if len(parts) > 1 else None
        new_path = _cmd_wd(arg, project_path)
        return None, new_path
    elif cmd == "/compact":
        _cmd_compact(active_loop, stats)
    elif cmd == "/tools":
        _cmd_tools(active_loop)
    elif cmd == "/skills":
        _cmd_skills(active_loop)
    elif cmd == "/init":
        _cmd_init(project_path)
    else:
        console.print(f"[red]Unknown command:[/red] {cmd}")
        console.print("[dim]Type [bold]/help[/bold] to see available commands.[/dim]")
    return None, project_path


# ── Typer command ─────────────────────────────────────────────────────────────

@app.command()
def run(
    task: Optional[str] = typer.Argument(
        None, help="Task to run. Omit to start an interactive REPL session."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model ID from [italic]config.yaml[/italic]."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show full tool input/output."
    ),
    sync: bool = typer.Option(
        False, "--sync", help="Force synchronous mode (no spinner)."
    ),
    project: Optional[str] = typer.Option(
        None, "--project", "-p",
        help="Project directory to work in (default: current directory).",
    ),
) -> None:
    cli_cfg = load_cli_config()
    effective_verbose = verbose or cli_cfg.verbose
    stats = _Stats()
    conversation_msgs: list = []
    active_loop: "AgentLoop | None" = None
    is_tty = sys.stdin.isatty()
    model_name = get_model_display_name(model)
    project_path = Path(project).resolve() if project else Path.cwd()

    console.print(
        Panel(
            "[bold cyan]Driverless AGI[/bold cyan]  [dim]— agentic coding assistant[/dim]\n"
            f"[dim]Project: [bold]{project_path}[/bold][/dim]\n"
            "[dim]Type [bold]/help[/bold] for commands · "
            "[bold]exit[/bold] or [bold]/exit[/bold] to leave · "
            "[bold]Ctrl-C[/bold] to interrupt[/dim]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    def run_one(t: str) -> None:
        nonlocal conversation_msgs, active_loop
        console.print()
        conversation_msgs, active_loop = _run_task(
            t, conversation_msgs, cli_cfg, model, model_name,
            effective_verbose, sync, stats, project_path,
        )

    if task:
        run_one(task)

    if is_tty:
        while True:
            try:
                user_input = console.input("\n[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                break
            # ── Slash commands ──────────────────────────────────────────
            if user_input.startswith("/"):
                slash_result, new_path = _handle_slash_command(
                    user_input, conversation_msgs, model, stats,
                    project_path, active_loop,
                )
                if slash_result is _EXIT_SENTINEL:
                    break
                if new_path != project_path:
                    project_path = new_path
                    conversation_msgs = []
                    active_loop = None
                continue
            # ────────────────────────────────────────────────────────────
            run_one(user_input)

    console.print("\n[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    app()
