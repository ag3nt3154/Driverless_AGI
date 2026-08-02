from __future__ import annotations

import threading
import time
from pathlib import Path

from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from agent import DAGI_ROOT
from agent.config_loader import resolve_model_config
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop

from .callbacks import build_callbacks
from .commands import SlashCommandsMixin
from .conversation import ConversationPane
from .prompt_input import PromptInput
from .sidebar import Sidebar
from .streaming import StreamPreview
from .utils import _Stats


def _format_elapsed(start: float | None) -> str:
    if start is None:
        return "0s"
    secs = int(time.monotonic() - start)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60:02d}s"
    return f"{secs // 3600}h {(secs % 3600) // 60:02d}m {secs % 60:02d}s"


class DagiApp(SlashCommandsMixin, App[None]):
    _PROMPT_HEIGHT_COLLAPSED: int = 8  # must match CSS `#prompt { height: 8 }`

    CSS = """
    Screen           { layout: horizontal; }
    #main-column     { width: 1fr; layout: vertical; }
    ConversationPane { height: 1fr; }
    Sidebar          { width: 30%; max-width: 45; border-left: solid $panel; }
    #running-indicator { height: 1; display: none; color: $success; text-align: center; }
    #prompt          { dock: bottom; height: 8; border-top: solid $panel; }
    """

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("escape", "pause", "Pause"),
        ("ctrl+o", "toggle_compose", "Compose"),
    ]

    def __init__(self, model_id: str | None, project: str | None, verbose: bool) -> None:
        super().__init__()
        self._project_path = Path(project).resolve() if project else Path.cwd()
        self._verbose = verbose
        self._stats = _Stats()
        self._config: AgentConfig | None = None
        # Resolve with project-merge FIRST so _model_name matches the actual model used.
        # (get_model_display_name only reads root config.yaml — it misses project overrides.)
        self._config = resolve_model_config(model_id, project_path=self._project_path)
        self._model_id = self._config.model_id
        self._model_name = self._config.display_name
        self._active_loop: AgentLoop | None = None
        self._worker: threading.Thread | None = None
        self._pending_ask: tuple | None = None
        self._current_loop_ref: list = []
        self._skill_map: dict = {}
        self._workflow_map: dict = {}
        self._spinner_idx: int = 0
        self._run_start_time: float | None = None
        self._input_expanded: bool = False
        self._restore_initial_messages: list | None = None

    def compose(self) -> ComposeResult:
        dagi_root = DAGI_ROOT
        with Vertical(id="main-column"):
            yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
            yield StreamPreview(id="stream-preview")
            yield Static("", id="running-indicator")
            yield PromptInput(id="prompt")
        yield Sidebar(
            self._model_name, self._config.context_window, self._config.reserve_tokens,
            dagi_root=dagi_root, project_path=self._project_path,
            memory_root=getattr(self._config, "memory_root", None),
        )

    def on_mount(self) -> None:
        self._load_maps()
        conv = self.query_one(ConversationPane)
        conv.write(Text(
            f"Driverless AGI  ·  {self._model_name}  ·  {self._project_path}",
            style="bold cyan",
        ))
        conv.write(Text("Type /help for commands · /exit to leave", style="dim"))
        self.query_one("#prompt", PromptInput).focus()
        self.query_one("#prompt", PromptInput).border_title = "ctrl+n = newline · ctrl+o = compose"
        self.set_interval(2.0, self._poll_plan)
        self.set_interval(0.1, self._tick_spinner)

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        if self._input_expanded:
            self.action_toggle_compose()
        if self._pending_ask is not None:
            ask_evt, container, options, _ = self._pending_ask
            self._pending_ask = None
            container.append(raw)
            self.query_one(ConversationPane).write(
                Panel(raw, title="[bold cyan]You[/bold cyan]",
                      title_align="left", border_style="cyan", padding=(0, 1))
            )
            ask_evt.set()
            self.query_one("#prompt", PromptInput).disabled = True
            self._show_running_indicator()
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
            self._show_running_indicator()
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
        bash_tool = loop.registry._tools.get("bash")
        if bash_tool is not None:
            bash_tool.force_kill()
        from tools._subagent_runner import force_kill_active_subagents
        force_kill_active_subagents()
        loop.pause()
        self.query_one(Sidebar).set_status("paused")
        self.query_one(ConversationPane).append_info(
            "[yellow]⏸ Paused — type a message and press Enter to continue[/yellow]"
        )
        self._hide_running_indicator()
        self._enable_input()

    def action_toggle_compose(self) -> None:
        if self._worker and self._worker.is_alive() and self._pending_ask is None:
            return  # block compose toggle while agent is running
        self._input_expanded = not self._input_expanded
        conv = self.query_one(ConversationPane)
        inp = self.query_one("#prompt", PromptInput)
        bar = self.query_one("#running-indicator", Static)
        hide = self._input_expanded
        conv.display = not hide
        if hide:
            self._bar_was_visible = bar.display
            bar.display = False
        else:
            bar.display = getattr(self, "_bar_was_visible", False)
        inp.styles.height = "1fr" if hide else self._PROMPT_HEIGHT_COLLAPSED
        inp.border_title = (
            "COMPOSE — Enter to submit · ctrl+o to collapse"
            if hide else
            "ctrl+n = newline · ctrl+o = compose"
        )

    def _dispatch_agent(self, task: str) -> None:
        if self._worker and self._worker.is_alive():
            self.query_one(ConversationPane).append_info("[yellow]Agent is already running.[/yellow]")
            return
        conv = self.query_one(ConversationPane)
        conv.write(Panel(task, title="[bold cyan]You[/bold cyan]",
                         title_align="left", border_style="cyan", padding=(0, 1)))
        self.query_one("#prompt", PromptInput).disabled = True
        self._show_running_indicator()
        self._current_loop_ref = []
        callbacks = build_callbacks(self, self._current_loop_ref)
        self._worker = threading.Thread(
            target=self._agent_work, args=(task, callbacks, self._current_loop_ref), daemon=True
        )
        self._worker.start()

    def _agent_work(self, task: str, callbacks: AgentCallbacks, loop_ref: list) -> None:
        sidebar = self.query_one(Sidebar)
        self.call_from_thread(sidebar.set_status, "running")
        try:
            tracker = self._active_loop.tracker if self._active_loop else None
            # Use stashed restore messages (from /hist) if available, else continue
            # from the active loop's existing message history.
            if self._restore_initial_messages is not None:
                initial = self._restore_initial_messages
                self._restore_initial_messages = None
            else:
                initial = self._active_loop._messages if self._active_loop else None
            loop = AgentLoop(self._config, callbacks, initial_messages=initial, _tracker=tracker)
            loop_ref.append(loop)
            self._active_loop = loop  # save before run so context survives any exception
            loop.run(task)
        except Exception as exc:
            self.call_from_thread(self.query_one(ConversationPane).append_error, str(exc))
        finally:
            if loop_ref:
                try:
                    loop_ref[0].finish()
                except Exception:
                    pass
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

    def _tick_spinner(self) -> None:
        bar = self.query_one("#running-indicator", Static)
        if not bar.display:
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        elapsed = _format_elapsed(self._run_start_time)
        bar.update(f"  {self._SPINNER[self._spinner_idx]} Running…  {elapsed}")

    def _show_running_indicator(self) -> None:
        self._run_start_time = time.monotonic()
        bar = self.query_one("#running-indicator", Static)
        bar.update(f"  {self._SPINNER[0]} Running…  0s")
        bar.display = True

    def _hide_running_indicator(self) -> None:
        self._run_start_time = None
        self.query_one("#running-indicator", Static).display = False

    def _expand_stream_preview(self) -> None:
        self.query_one(ConversationPane).display = False
        self.query_one(StreamPreview).expand()

    def _collapse_stream_preview(self) -> None:
        self.query_one(ConversationPane).display = True

    def _enable_input(self) -> None:
        self._hide_running_indicator()
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
        self._enable_input()

    def on_history_screen_session_selected(
        self, event: "HistoryScreen.SessionSelected"
    ) -> None:
        """Handle session selection from the history picker."""
        self.pop_screen()
        self._restore_session(event.path, event.turn_index)

    def on_history_screen_dismissed(self, event: "HistoryScreen.Dismissed") -> None:
        """Handle dismissal of the history picker (Escape)."""
        self.pop_screen()

    def _restore_session(self, path: Path, turn_index: int) -> None:
        """Load a prior session's messages into the active loop context.

        Clears the conversation, visually replays the restored messages,
        and stashes them so the next _dispatch_agent call starts from them.
        """
        from tui.history import load_raw_messages
        raw = load_raw_messages(path)
        if not raw:
            self.query_one(ConversationPane).append_info(
                "[red]✗ Cannot restore — session has no raw_messages.[/red]"
            )
            self._enable_input()
            return
        # Slice to requested turn depth; safe for turn_index == len(raw)
        restored = raw[:turn_index + 1]
        # Reset conversation state
        self._active_loop = None
        self._current_loop_ref = []
        conv = self.query_one(ConversationPane)
        conv.clear()
        self._render_restored_session(path, restored[1:])  # skip old system msg
        self._restore_initial_messages = restored
        conv.append_info(
            f"[green]✓ Restored {len(restored) - 1} messages from [bold]{path.name}[/bold] "
            f"— type your next message to continue[/green]"
        )
        self._enable_input()

    def _render_restored_session(self, path: Path, messages: list[dict]) -> None:
        """Visually replay a slice of raw_messages into the conversation pane."""
        conv = self.query_one(ConversationPane)
        conv.append_info(f"[dim]─── Restored: {path.name} ───[/dim]")
        for msg in messages:
            role = msg.get("role")
            content = str(msg.get("content") or "").strip()
            if role == "user":
                conv.write(Panel(
                    content,
                    title="[bold cyan]You[/bold cyan]",
                    title_align="left", border_style="cyan", padding=(0, 1),
                ))
            elif role == "assistant":
                if content:
                    conv.append_assistant(content)
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    names = ", ".join(
                        tc.get("function", {}).get("name", "?") for tc in tool_calls
                    )
                    conv.append_info(f"[dim]  ↳ tool calls: {names}[/dim]")
        conv.append_info("[dim]─── end of restored context ───[/dim]")
