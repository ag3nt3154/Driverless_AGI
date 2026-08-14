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
from datetime import datetime
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

from agent import DAGI_ROOT as _DAGI_ROOT

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
    "cli_subagent": "bright_blue",
}
_MAX_COMPACT_LEN = 120


def _colour(tool_name: str) -> str:
    return _TOOL_COLOURS.get(tool_name.lower(), "cyan")


def _truncate(text: str, length: int = _MAX_COMPACT_LEN) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= length else text[:length] + "…"


def _resolve_option(raw: str, options: list[dict]) -> str:
    """Map user input (number or label string) to an option label. Falls back to recommended/first."""
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]["label"]
    for opt in options:
        if opt["label"].lower() == raw.lower():
            return opt["label"]
    return next(
        (o["label"] for o in options if o.get("recommended")),
        options[0]["label"] if options else "",
    )


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

    def footer(self, model_name: str, cwd: Path | None = None, plan_mode: bool = False) -> str:
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
        if plan_mode:
            parts.append("📋 plan mode")
        return "  ·  ".join(parts)


# ── Sync callbacks (fire directly on the agent thread) ───────────────────────

def _make_sync_callbacks(
    stats: _Stats, model_name: str, verbose: bool,
    get_cwd: Callable[[], Path], plan_mode: bool = False,
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

    def on_model_switch(from_name: str, to_name: str) -> None:
        console.print(
            f"[bold cyan]⇄ Model switch:[/bold cyan] [dim]{from_name}[/dim] → [bold]{to_name}[/bold]"
        )

    def on_error(exc: Exception) -> None:
        console.print_exception()

    def on_done(_result: str) -> None:
        console.print(f"[dim]{stats.footer(model_name, cwd=get_cwd(), plan_mode=plan_mode)}[/dim]")

    def on_ask_user(question: str, options: list[dict], effective_timeout: float | None) -> str:
        console.print()
        console.print(Panel(
            question,
            title="[bold cyan]Question from Dagi[/bold cyan]",
            border_style="cyan",
            padding=(0, 2),
        ))
        if options:
            table = Table(border_style="dim", padding=(0, 1))
            table.add_column("#", style="bold cyan", width=3)
            table.add_column("Option", style="bold")
            table.add_column("Description", style="dim")
            for i, opt in enumerate(options, 1):
                rec = " [bold green](recommended)[/bold green]" if opt.get("recommended") else ""
                table.add_row(str(i), opt["label"] + rec, opt.get("description", ""))
            console.print(table)
        timeout_hint = f" — auto-selects in {int(effective_timeout)}s" if effective_timeout is not None else ""
        raw = console.input(f"[dim]Your answer{timeout_hint}: [/dim]").strip()
        return raw

    return AgentCallbacks(
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text,
        on_token_update=on_token_update,
        on_compaction=on_compaction,
        on_reasoning=on_reasoning,
        on_model_switch=on_model_switch,
        on_error=on_error,
        on_done=on_done,
        on_ask_user=on_ask_user,
    )


# ── Threaded callbacks (post events to queue; main thread renders) ────────────

_EVT_TOOL_START   = "tool_start"
_EVT_TOOL_END     = "tool_end"
_EVT_ASSISTANT    = "assistant"
_EVT_TOKENS       = "tokens"
_EVT_COMPACTION   = "compaction"
_EVT_REASONING    = "reasoning"
_EVT_ERROR        = "error"
_EVT_DONE         = "done"
_EVT_ASK_USER     = "ask_user"
_EVT_MODEL_SWITCH = "model_switch"


def _make_threaded_callbacks(q: queue.Queue, stats: _Stats) -> AgentCallbacks:
    import threading

    def put(tag: str, *payload) -> None:
        q.put((tag, *payload))

    def on_ask_user(question: str, options: list[dict], effective_timeout: float | None) -> str:
        response_event = threading.Event()
        answer_container: list[str] = []
        q.put((_EVT_ASK_USER, question, options, response_event, answer_container, effective_timeout))
        safety = (effective_timeout + 60) if effective_timeout is not None else None
        response_event.wait(timeout=safety)
        if answer_container:
            return answer_container[0]
        return next((o["label"] for o in options if o.get("recommended")), options[0]["label"] if options else "")

    return AgentCallbacks(
        on_tool_start     = lambda n, d, a: put(_EVT_TOOL_START, n, d, a),
        on_tool_end       = lambda n, r:    put(_EVT_TOOL_END, n, r),
        on_assistant_text = lambda t:       put(_EVT_ASSISTANT, t),
        on_token_update   = lambda i, o, c, t=0, ca=0: put(_EVT_TOKENS, i, o, c, t),
        on_compaction     = lambda k, r:    put(_EVT_COMPACTION, k, r),
        on_reasoning      = lambda t:       put(_EVT_REASONING, t),
        on_model_switch   = lambda f, t:    put(_EVT_MODEL_SWITCH, f, t),
        on_error          = lambda e:       put(_EVT_ERROR, str(e)),
        on_done           = lambda r:       put(_EVT_DONE, r),
        on_ask_user       = on_ask_user,
    )


def _render_queue(
    q: queue.Queue,
    stats: _Stats,
    model_name: str,
    verbose: bool,
    get_cwd: Callable[[], Path],
    plan_mode: bool = False,
) -> None:
    """Drain the event queue and render output. Runs on the main thread."""
    spinner_text = Text("Thinking…", style="dim")
    spinner = Spinner("dots", text=spinner_text)

    with Live(spinner, console=console, refresh_per_second=10, transient=True) as live:
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

            elif tag == _EVT_ASK_USER:
                import threading as _threading
                question, options, response_event, answer_container, effective_timeout = payload
                live.stop()
                try:
                    console.print()
                    console.print(Panel(
                        question,
                        title="[bold cyan]Question from Dagi[/bold cyan]",
                        border_style="cyan",
                        padding=(0, 2),
                    ))
                    if options:
                        tbl = Table(border_style="dim", padding=(0, 1))
                        tbl.add_column("#", style="bold cyan", width=3)
                        tbl.add_column("Option", style="bold")
                        tbl.add_column("Description", style="dim")
                        for i, opt in enumerate(options, 1):
                            rec = " [bold green](recommended)[/bold green]" if opt.get("recommended") else ""
                            tbl.add_row(str(i), opt["label"] + rec, opt.get("description", ""))
                        console.print(tbl)
                    timeout_hint = f" — auto-selects in {int(effective_timeout)}s" if effective_timeout is not None else ""
                    console.print(f"[dim]Type your answer{timeout_hint}[/dim]")

                    user_answer: list[str] = []
                    input_done = _threading.Event()

                    def _get_input() -> None:
                        try:
                            raw = console.input("[bold cyan]>[/bold cyan] ").strip()
                            user_answer.append(raw)
                        except (EOFError, KeyboardInterrupt):
                            pass
                        finally:
                            input_done.set()

                    _threading.Thread(target=_get_input, daemon=True).start()
                    timed_out = not input_done.wait(timeout=effective_timeout)

                    if user_answer and not timed_out:
                        chosen = user_answer[0]
                    else:
                        chosen = next(
                            (o["label"] for o in options if o.get("recommended")),
                            options[0]["label"] if options else "[timed out]",
                        )
                        console.print(f"[dim]No response — auto-selected: {chosen}[/dim]")
                    answer_container.append(chosen)
                finally:
                    response_event.set()
                    live.start()
                spinner_text.plain = "Thinking…"

            elif tag == _EVT_MODEL_SWITCH:
                from_name, to_name = payload
                console.print(
                    f"[bold cyan]⇄ Model switch:[/bold cyan] [dim]{from_name}[/dim] → [bold]{to_name}[/bold]"
                )

            elif tag == _EVT_DONE:
                console.print(f"[dim]{stats.footer(model_name, cwd=get_cwd(), plan_mode=plan_mode)}[/dim]")


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
    plan_mode: bool = False,
    plan_file: Path | None = None,
    existing_tracker: "SessionTracker | None" = None,
) -> tuple[list, "AgentLoop"]:
    """Run one agent task. Returns (updated conversation messages, loop) for multi-turn."""
    config = resolve_model_config(model_id, project_path=project_path)
    config.plan_mode = plan_mode
    config.plan_file = str(plan_file) if plan_file else None
    use_threaded = (cli_cfg.threading == "threaded") and not force_sync

    get_cwd: Callable[[], Path] = lambda: project_path

    if use_threaded:
        q: queue.Queue = queue.Queue()
        callbacks = _make_threaded_callbacks(q, stats)
        loop = AgentLoop(
            config, callbacks,
            initial_messages=conversation_msgs or None,
            _tracker=existing_tracker,
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
            _render_queue(q, stats, model_name, verbose, get_cwd, plan_mode=plan_mode)
    else:
        callbacks = _make_sync_callbacks(stats, model_name, verbose, get_cwd, plan_mode=plan_mode)
        loop = AgentLoop(
            config, callbacks,
            initial_messages=conversation_msgs or None,
            _tracker=existing_tracker,
        )
        try:
            loop.run(task)
        except Exception:
            console.print_exception()

    return loop._messages, loop




# ── Slash commands ─────────────────────────────────────────────────────────────

_SLASH_COMMANDS: dict[str, str] = {
    "/help":         "Show this list of commands",
    "/exit":         "Exit the session (same as exit/quit/q)",
    "/clear":        "Clear conversation context and start a fresh session",
    "/wd":           "Show or set working directory  (/wd <path>)",
    "/compact":      "Force-compact conversation context into a summary",
    "/tools":        "List all registered agent tools",
    "/skills":       "List all loaded skills",
    "/workflows":    "List all loaded workflows",
    "/init":         "Initialise .dagi/ scaffold and dagi-memory/ wiki (dirs, AGENTS.md, stubs)",
    "/hist":         "Show the 20 most recent agent sessions  (/hist [n])",
    "/plan":         "Enter plan mode — agent explores and writes a plan doc (read-only except plan file)",
    "/exit-plan":    "Exit plan mode and begin implementation based on the plan",
}

_EXIT_SENTINEL = object()  # returned by /exit handler to signal the REPL to break


def _cmd_help(skill_slash_map: "dict | None" = None, workflow_slash_map: "dict | None" = None) -> None:
    table = Table(title="Slash Commands", border_style="dim", padding=(0, 1))
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="dim")
    for cmd, desc in _SLASH_COMMANDS.items():
        table.add_row(cmd, desc)
    console.print(table)
    if skill_slash_map:
        skill_table = Table(title="Skill Commands", border_style="dim", padding=(0, 1))
        skill_table.add_column("Command", style="bold bright_magenta")
        skill_table.add_column("Description", style="dim")
        for slash_cmd, skill in sorted(skill_slash_map.items()):
            skill_table.add_row(slash_cmd, skill.description or "—")
        console.print(skill_table)
    if workflow_slash_map:
        wf_table = Table(title="Workflow Commands", border_style="dim", padding=(0, 1))
        wf_table.add_column("Command", style="bold yellow")
        wf_table.add_column("Description", style="dim")
        for slash_cmd, wf in sorted(workflow_slash_map.items()):
            wf_table.add_row(slash_cmd, wf.description or "—")
        console.print(wf_table)


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


def _cmd_skills(loop: "AgentLoop | None" = None, skill_slash_map: "dict | None" = None) -> None:
    skills = loop.skills if loop is not None else (list(skill_slash_map.values()) if skill_slash_map else [])
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
    console.print("[dim]Tip: invoke any skill as a slash command, e.g. [bold]/memory-add[/bold][/dim]")


def _cmd_workflows(workflow_slash_map: "dict | None" = None) -> None:
    workflows = list(workflow_slash_map.values()) if workflow_slash_map else []
    if not workflows:
        console.print("[dim]No workflows loaded.[/dim]")
        console.print("[dim]Add a workflow at [bold].dagi/workflow/<name>/workflow.md[/bold][/dim]")
        return
    table = Table(title="Loaded Workflows", border_style="dim", padding=(0, 1))
    table.add_column("Command", style="bold yellow")
    table.add_column("Name", style="bold")
    table.add_column("Description", style="dim")
    for w in sorted(workflows, key=lambda x: x.name):
        table.add_row(f"/{w.name}", w.name, w.description or "—")
    console.print(table)
    console.print("[dim]Tip: invoke any workflow as a slash command, e.g. [bold]/deploy-staging[/bold][/dim]")


def _cmd_init(project_path: Path) -> None:
    from datetime import date
    dagi_dir = project_path / ".dagi"
    memory = project_path / "dagi-memory"
    today = date.today().isoformat()

    for d in [
        dagi_dir / "skills",
        dagi_dir / "workflow",
        dagi_dir / "self-review",
        dagi_dir / "logs",
        memory / "raw",
        memory / "sources",
        memory / "wiki" / "projects",
        memory / "wiki" / "knowledge",
    ]:
        d.mkdir(parents=True, exist_ok=True)

    agents_file = dagi_dir / "agents.md"
    project_name = project_path.name
    agents_stub = (
        f"# Project: {project_name}\n\n"
        f"> **Last updated:** {today}\n\n"
        "## Description\n\n"
        "_What this project does and why it exists._\n\n"
        "## Objectives\n\n"
        "_Key goals and success criteria._\n\n"
        "## Directory Structure\n\n"
        f"```\n{project_name}/\n```\n\n"
        "## Environment\n\n"
        "- **Language:**\n"
        "- **Runtime / virtual env:**\n"
        "- **Install dependencies:**\n"
        "- **Run command:**\n\n"
        "## Known Issues & Resolutions\n\n"
        "_Document errors encountered and how they were resolved._\n\n"
        "## Recent Changes\n\n"
        "_Updated by the agent after each task._\n"
    )
    wiki_stubs: dict[Path, str] = {
        memory / "wiki" / ".index.md": (
            "# Wiki Index\n\n"
            f"> **Last updated:** {today}\n\n"
            "## Sections\n\n"
            "| Section | Description |\n"
            "|---------|-------------|\n"
            "| [projects](projects/.index.md) | Per-project knowledge, context, and updates |\n"
            "| [knowledge](knowledge/.index.md) | General domain knowledge and research |\n"
            "| [User TODO](user-todo.md) | Personal task and intention tracker |\n\n"
            "## Meta Files\n\n"
            "- [log.md](log.md) — Operation history\n"
            "- [open_questions.md](open_questions.md) — Research gaps\n"
        ),
        memory / "wiki" / "projects" / ".index.md": (
            "# Projects\n\n"
            f"> **Last updated:** {today}\n\n"
            "| Project | Description | Last Updated |\n"
            "|---------|-------------|-------------- |\n"
            "| — | — | — |\n"
        ),
        memory / "wiki" / "knowledge" / ".index.md": (
            "# Knowledge\n\n"
            f"> **Last updated:** {today}\n\n"
            "| Topic | Description | Pages |\n"
            "|-------|-------------|-------|\n"
            "| — | — | — |\n"
        ),
        memory / "wiki" / "log.md": (
            "# Memory Log\n\n"
            "> Append-only. Do not edit manually.\n"
            "> Each entry format: `[YYYY-MM-DD] {operation} | {title} | {path}`\n"
            "> Operations: add | add-todo | ingest | query | lint\n\n"
            "<!-- entries appended below -->\n"
        ),
        memory / "wiki" / "user-todo.md": (
            "---\n"
            "type: note\n"
            "topic: user-todos\n"
            "description: Personal task and intention tracker for the Admiral\n"
            f"date_added: {today}\n"
            "tags: todo, tasks, planning, personal\n"
            "---\n\n"
            "# User TODO\n\n"
            "> Personal intention log. Entries are appended by the memory-add skill "
            "whenever the Admiral\n"
            "> expresses a plan or goal. Never delete entries — update `Status` "
            "instead.\n\n"
            "<!-- Append new entries below. -->\n"
        ),
        memory / "wiki" / "open_questions.md": (
            "# Open Questions\n\n"
            f"> **Last updated:** {today}\n\n"
            "## Pending\n\n"
            "| # | Question | Context | Source Page | Date Raised |\n"
            "|---|----------|---------|-------------|-------------|\n"
            "| — | — | — | — | — |\n\n"
            "## Resolved\n\n"
            "| # | Question | Answer Summary | Wiki Page | Date Resolved |\n"
            "|---|----------|----------------|-----------|---------------|\n"
            "| — | — | — | — | — |\n"
        ),
    }

    created: list[str] = []
    skipped: list[str] = []

    if agents_file.exists():
        skipped.append(str(agents_file.relative_to(project_path)))
    else:
        agents_file.write_text(agents_stub, encoding="utf-8")
        created.append(str(agents_file.relative_to(project_path)))

    for path, content in wiki_stubs.items():
        rel = str(path.relative_to(project_path))
        if path.exists() and path.stat().st_size > 0:
            skipped.append(rel)
        else:
            path.write_text(content, encoding="utf-8")
            created.append(rel)

    console.print(f"[green]✓ Initialised[/green] [dim]{dagi_dir}[/dim]")
    for p in created:
        console.print(f"  [dim]created:[/dim] {p}")
    for p in skipped:
        console.print(f"  [dim]skipped (exists):[/dim] {p}")
    if not created and not skipped:
        console.print(f"[dim]Already initialised: {dagi_dir}[/dim]")
    console.print(
        "[dim]Next: use [bold]spawn_memory_add_subagent[/bold] to add knowledge, "
        "or drop files into [bold]dagi-memory/raw/[/bold] then invoke [bold]memory-ingest[/bold]. "
        "Add workflows to [bold].dagi/workflow/<name>/workflow.md[/bold].[/dim]"
    )


def _cmd_hist(project_path: Path, arg: str | None) -> None:
    from hist import run as hist_run
    try:
        n = int(arg) if arg else 20
    except ValueError:
        console.print(f"[red]Usage:[/red] /hist [n]  (n must be an integer)")
        return
    hist_run(project=project_path, n=n)


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
    skill_slash_map: "dict | None" = None,
    workflow_slash_map: "dict | None" = None,
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
        _cmd_help(skill_slash_map, workflow_slash_map)
    elif cmd == "/workflows":
        _cmd_workflows(workflow_slash_map)
    elif cmd == "/wd":
        arg = parts[1].strip() if len(parts) > 1 else None
        new_path = _cmd_wd(arg, project_path)
        return None, new_path
    elif cmd == "/compact":
        _cmd_compact(active_loop, stats)
    elif cmd == "/tools":
        _cmd_tools(active_loop)
    elif cmd == "/skills":
        _cmd_skills(active_loop, skill_slash_map)
    elif cmd == "/init":
        _cmd_init(project_path)
    elif cmd == "/hist":
        arg = parts[1].strip() if len(parts) > 1 else None
        _cmd_hist(project_path, arg)
    else:
        console.print(f"[red]Unknown command:[/red] {cmd}")
        console.print("[dim]Type [bold]/help[/bold] to see available commands.[/dim]")
    return None, project_path


# ── Skill slash-command map ───────────────────────────────────────────────────

def _skill_invocation_message(skill_name: str, user_arg: str) -> str:
    msg = f"Invoke the `{skill_name}` skill."
    if user_arg:
        msg += f"\n\n{user_arg}"
    return msg


def _load_skill_map(proj_path: Path) -> dict:
    from agent.skills import SkillLoader
    dagi_root = _DAGI_ROOT
    roots = [dagi_root / ".dagi" / "skills", proj_path / ".dagi" / "skills"]
    skills = SkillLoader().load_all(roots, dagi_root=dagi_root)
    return {f"/{s.name}": s for s in skills}


def _load_workflow_map(proj_path: Path) -> dict:
    from agent.workflows import WorkflowLoader
    roots = [proj_path / ".dagi" / "workflow"]
    workflows = WorkflowLoader().load_all(roots)
    return {f"/{w.name}": w for w in workflows}


# ── Subagent pipe mode ────────────────────────────────────────────────────────

def _apply_worker_config(config: "AgentConfig") -> "AgentConfig":
    """Return a flattened config that uses worker_model (falls back to default)."""
    from dataclasses import replace
    w = config.worker_config or config
    return replace(
        config,
        model=w.model,
        base_url=w.base_url,
        api_key=w.api_key,
        thinking=w.thinking,
        context_window=w.context_window,
        reserve_tokens=w.reserve_tokens,
        keep_recent_tokens=w.keep_recent_tokens,
        plan_mode=False,
        plan_file=None,
        worker_config=None,
        advanced_config=None,
    )


def _apply_advanced_config(config: "AgentConfig", plan_mode: bool = False) -> "AgentConfig":
    """Return a flattened config that uses advanced_model (falls back to default)."""
    from dataclasses import replace
    a = config.advanced_config or config
    return replace(
        config,
        model=a.model,
        base_url=a.base_url,
        api_key=a.api_key,
        thinking=a.thinking,
        context_window=a.context_window,
        reserve_tokens=a.reserve_tokens,
        keep_recent_tokens=a.keep_recent_tokens,
        plan_mode=plan_mode,
        plan_file=None,
        worker_config=None,
        advanced_config=None,
    )


def _extract_final_assistant_text(messages: list) -> str:
    """Return the last non-empty assistant text from a message list."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [
                    blk.get("text", "")
                    for blk in content
                    if isinstance(blk, dict) and blk.get("type") == "text"
                ]
                text = "\n".join(parts).strip()
            else:
                text = (content or "").strip()
            if text:
                return text
    return ""


def _build_pipe_callbacks() -> AgentCallbacks:
    """Build callbacks that emit newline-delimited JSON events to stdout.

    Used by the subagent subprocess so the parent can relay events to the TUI.
    """
    import json as _json

    def _emit(evt: dict) -> None:
        print(_json.dumps(evt), flush=True)

    return AgentCallbacks(
        on_tool_start=lambda name, _d, args: _emit({
            "type": "tool_call", "name": name, "args": args[:200],
        }),
        on_tool_end=lambda name, result: _emit({
            "type": "tool_result", "name": name, "chars": len(result),
        }),
        on_assistant_text=lambda text: (
            _emit({"type": "message", "content": text}) if text.strip() else None
        ),
        on_reasoning=lambda text: (
            _emit({"type": "reasoning", "content": text[:120]}) if text.strip() else None
        ),
        on_model_switch=lambda _f, to: _emit({"type": "status", "text": f"→ {to}"}),
        on_error=lambda e: _emit({"type": "error", "message": str(e)}),
        on_compaction=lambda kept, removed: _emit({
            "type": "status", "text": f"compacted ({removed} msgs removed, {kept} kept)",
        }),
        on_token_update=lambda i, o, c, t, ca=0: None,  # silent in pipe mode
    )


def _run_typed_subagent_task(
    task: str,
    subagent_type: str,
    config: "AgentConfig",
    project_path: Path,
    plan_file_path: Optional[str],
    force_sync: bool,
    system_prompt_file: Optional[str] = None,
) -> str:
    """Run one task for a typed subagent terminal. Returns final assistant text."""
    import time as _time

    from agent.prompts import load_subagent_prompt
    from agent.tools import build_subagent_registry

    plan_file = Path(plan_file_path) if plan_file_path else None
    stats = _Stats()
    model_name = config.model or "unknown"
    get_cwd: Callable[[], Path] = lambda: project_path

    use_threaded = not force_sync
    if system_prompt_file:
        system_prompt = Path(system_prompt_file).read_text(encoding="utf-8")
    else:
        system_prompt = load_subagent_prompt(subagent_type)

    if use_threaded:
        q: queue.Queue = queue.Queue()
        callbacks = _make_threaded_callbacks(q, stats)
    else:
        callbacks = _make_sync_callbacks(stats, model_name, verbose=False, get_cwd=get_cwd)

    registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=config,
        project_path=project_path,
        plan_file=plan_file,
        callbacks=callbacks,
        memory_root=config.memory_root,
    )

    loop = AgentLoop(
        config=config,
        callbacks=callbacks,
        initial_messages=[{"role": "system", "content": system_prompt}],
        _registry=registry,
    )

    if use_threaded:
        def _agent_thread() -> None:
            try:
                loop.run(task)
            except Exception:
                pass
            finally:
                q.put(None)

        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(_agent_thread)
            _render_queue(q, stats, model_name, verbose=False, get_cwd=get_cwd)
    else:
        try:
            loop.run(task)
        except Exception:
            console.print_exception()

    loop.finish()
    return _extract_final_assistant_text(loop._messages)


def _render_task_prompt(console: "Console", seq: int, task: str) -> None:
    """Render a subagent task prompt as structured Rich panels.

    Splits the task string on '## ' headings and renders each section as a
    labeled Panel with Markdown content. Falls back to a single panel when no
    headings are found.
    """
    import re
    from rich.markdown import Markdown
    from rich.panel import Panel

    console.print()
    console.print(Panel(f"[bold cyan]Task #{seq}[/bold cyan]", border_style="cyan", padding=(0, 2)))

    # Split on lines that start with '## ' (top-level markdown section headings)
    parts = re.split(r"(?m)^(## .+)$", task)
    if len(parts) <= 1:
        # No ## headings found — render full task in one panel
        console.print(Panel(Markdown(task.strip()), border_style="dim", padding=(0, 1)))
        return

    # parts alternates: [preamble, heading, body, heading, body, ...]
    preamble = parts[0].strip()
    if preamble:
        console.print(Panel(Markdown(preamble), title="[dim]Preamble[/dim]", border_style="dim", padding=(0, 1)))

    it = iter(parts[1:])
    for heading in it:
        body = next(it, "").strip()
        title = heading.lstrip("# ").strip()
        content = Markdown(body) if body else ""
        console.print(Panel(content, title=f"[bold]{title}[/bold]", border_style="dim", padding=(0, 1)))


def _load_optional_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


_AGENTS_MD_TYPES = {
    "explore_files": ["cwd"],
    "worker": ["dagi", "cwd"],
    "review": ["dagi", "cwd"],
}


def _build_subagent_system_prompt(subagent_type: str, project_path: Path) -> str:
    from agent.prompts import load_subagent_prompt

    base = load_subagent_prompt(subagent_type)
    which = _AGENTS_MD_TYPES.get(subagent_type, [])
    parts = [base]
    if "dagi" in which:
        md = _load_optional_md(_DAGI_ROOT / ".dagi" / "agents.md")
        if md:
            parts.append(md)
    if "cwd" in which:
        md = _load_optional_md(project_path / ".dagi" / "agents.md")
        if md:
            parts.append(md)
    return "\n\n---\n\n".join(parts)


def _run_subagent_pipe_mode(
    subagent_type: str,
    task_file: str,
    handoff: str,
    project: Optional[str],
    model: Optional[str],
    system_prompt_file: Optional[str] = None,
) -> None:
    """Run cli.py as a piped subagent: read task from file, emit JSON events, write handoff."""
    import json as _json
    import yaml as _yaml

    from agent.tools import build_subagent_registry

    project_path = Path(project).resolve() if project else Path.cwd()
    handoff_path = Path(handoff)
    task = Path(task_file).read_text(encoding="utf-8")

    # Resolve model tier from subagent_config.yaml
    base_config = resolve_model_config(model, project_path=project_path)

    config_yaml = (
        project_path / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    )
    if config_yaml.exists():
        sa_cfg = _yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        model_tier = sa_cfg.get("model_tier", "worker")
    elif subagent_type == "custom":
        model_tier = "advanced"
    else:
        model_tier = "worker"

    typed_config = (
        _apply_advanced_config(base_config)
        if model_tier == "advanced"
        else _apply_worker_config(base_config)
    )
    typed_config.project_path = project_path

    callbacks = _build_pipe_callbacks()
    registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=typed_config,
        project_path=project_path,
        callbacks=callbacks,
        memory_root=typed_config.memory_root,
        handoff_path=handoff_path,
    )

    if system_prompt_file:
        system_prompt = Path(system_prompt_file).read_text(encoding="utf-8")
    else:
        system_prompt = _build_subagent_system_prompt(subagent_type, project_path)
    loop = AgentLoop(
        config=typed_config,
        callbacks=callbacks,
        initial_messages=[{"role": "system", "content": system_prompt}],
        _registry=registry,
    )

    try:
        loop.run(task)
    except Exception as exc:
        print(_json.dumps({"type": "error", "message": str(exc)}), flush=True)
    finally:
        loop.finish()

    # Enforce handoff — write minimal report if agent forgot
    if not handoff_path.exists():
        final_text = _extract_final_assistant_text(loop._messages)
        handoff_path.parent.mkdir(parents=True, exist_ok=True)
        handoff_path.write_text(
            f"# Handoff\n\n{final_text or '(subagent produced no output)'}",
            encoding="utf-8",
        )

    print(_json.dumps({"type": "done"}), flush=True)


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
    subagent_type: Optional[str] = typer.Option(
        None, "--subagent-type",
        help="[Internal] Typed subagent profile to run in pipe mode.",
        hidden=True,
    ),
    task_file: Optional[str] = typer.Option(
        None, "--task-file",
        help="[Internal] Path to file containing the subagent task.",
        hidden=True,
    ),
    handoff: Optional[str] = typer.Option(
        None, "--handoff",
        help="[Internal] Path where the subagent should write its handoff report.",
        hidden=True,
    ),
    system_prompt_file: Optional[str] = typer.Option(
        None, "--system-prompt-file",
        help="[Internal] Path to a file containing a custom system prompt (overrides type default).",
        hidden=True,
    ),
) -> None:
    if subagent_type and task_file and handoff:
        _run_subagent_pipe_mode(
            subagent_type=subagent_type,
            task_file=task_file,
            handoff=handoff,
            project=project,
            model=model,
            system_prompt_file=system_prompt_file,
        )
        return

    cli_cfg = load_cli_config()
    effective_verbose = verbose or cli_cfg.verbose
    stats = _Stats()
    conversation_msgs: list = []
    active_loop: "AgentLoop | None" = None
    plan_mode: bool = False
    plan_file: Path | None = None
    plan_loop: "AgentLoop | None" = None
    is_tty = sys.stdin.isatty()
    model_name = get_model_display_name(model)
    project_path = Path(project).resolve() if project else Path.cwd()
    skill_slash_map = _load_skill_map(project_path)
    workflow_slash_map = _load_workflow_map(project_path)

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

        existing_tracker = active_loop.tracker if active_loop is not None else None
        conversation_msgs, active_loop = _run_task(
            t, conversation_msgs, cli_cfg, model, model_name,
            effective_verbose, sync, stats, project_path,
            plan_mode=False,
            plan_file=None,
            existing_tracker=existing_tracker,
        )
        if active_loop.plan_mode_exited and active_loop.exited_plan_file:
            had_plan_model = active_loop.config.advanced_config is not None
            plan_label = (
                active_loop.config.advanced_config.display_name
                if had_plan_model else model_name
            )
            switch_back = (
                f"[dim]Returning to: {model_name}[/dim]\n"
                if had_plan_model and plan_label != model_name else ""
            )
            console.print(
                Panel(
                    "[bold cyan]Plan mode exited.[/bold cyan]\n"
                    f"[dim]Plan document: {active_loop.exited_plan_file}[/dim]\n\n"
                    + switch_back,
                    border_style="cyan",
                    padding=(0, 2),
                )
            )

    if task:
        run_one(task)

    if is_tty:
        while True:
            try:
                user_input = console.input("\n[bold cyan]>[/bold cyan] ").strip()
            except (EOFError, KeyboardInterrupt):
                if active_loop is not None:
                    active_loop.finish()
                break
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                if active_loop is not None:
                    active_loop.finish()
                break
            # ── Slash commands ──────────────────────────────────────────
            if user_input.startswith("/"):
                cmd_lower = user_input.split()[0].lower()

                if cmd_lower == "/plan":
                    args_str = user_input.split(maxsplit=1)[1] if " " in user_input else ""
                    task_msg = _skill_invocation_message("plan-work-review", args_str)
                    run_one(task_msg)
                    continue

                if cmd_lower == "/exit-plan":
                    if not plan_mode:
                        console.print("[dim]Not in plan mode — nothing to exit.[/dim]")
                        continue
                    plan_mode = False
                    plan_file = None
                    console.print(
                        "[bold yellow]Plan cancelled — returning to clean state.[/bold yellow]"
                    )
                    continue

                if cmd_lower == "/clear":
                    if active_loop is not None:
                        active_loop.finish()
                    conversation_msgs = []
                    active_loop = None
                    if plan_mode:
                        plan_mode = False
                        plan_file = None
                        plan_loop = None
                    console.print("[bold green]✓ Context cleared — fresh session[/bold green]")
                    continue

                # ── Skill slash commands ──────────────────────────────
                if cmd_lower in skill_slash_map:
                    skill = skill_slash_map[cmd_lower]
                    args_str = user_input.split(maxsplit=1)[1] if " " in user_input else ""
                    task_msg = _skill_invocation_message(skill.name, args_str)
                    run_one(task_msg)
                    continue

                # ── Workflow slash commands ───────────────────────────
                if cmd_lower in workflow_slash_map:
                    wf = workflow_slash_map[cmd_lower]
                    args_str = user_input.split(maxsplit=1)[1] if " " in user_input else ""
                    from tools.workflow import load_workflow_content
                    task_msg = load_workflow_content(
                        wf.name, [project_path / ".dagi" / "workflow"]
                    )
                    if args_str:
                        task_msg += f"\n\nAdditional instructions: {args_str}"
                    run_one(task_msg)
                    continue

                slash_result, new_path = _handle_slash_command(
                    user_input, conversation_msgs, model, stats,
                    project_path, active_loop, skill_slash_map,
                    workflow_slash_map,
                )
                if slash_result is _EXIT_SENTINEL:
                    if active_loop is not None:
                        active_loop.finish()
                    break
                if new_path != project_path:
                    if active_loop is not None:
                        active_loop.finish()
                    project_path = new_path
                    skill_slash_map = _load_skill_map(project_path)
                    workflow_slash_map = _load_workflow_map(project_path)
                    conversation_msgs = []
                    active_loop = None
                continue
            # ────────────────────────────────────────────────────────────
            run_one(user_input)

    console.print("\n[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    app()
