from __future__ import annotations

import threading
from pathlib import Path

from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from agent.config_loader import get_model_display_name, resolve_model_config
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop

from .callbacks import build_callbacks
from .commands import SlashCommandsMixin
from .conversation import ConversationPane
from .prompt_input import PromptInput
from .sidebar import Sidebar
from .utils import _resolve_option, _Stats


class DagiApp(SlashCommandsMixin, App[None]):
    CSS = """
    Screen   { layout: vertical; }
    #main-row { height: 1fr; }
    #conversation-col { width: 75%; }
    ConversationPane { height: 1fr; }
    Sidebar  { width: 25%; border-left: solid $panel; padding: 0 1; }
    #running-indicator { height: 1; display: none; color: $success; text-align: center; }
    #prompt  { dock: bottom; height: 5; border-top: solid $panel; }
    """

    _SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
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
        self._spinner_idx: int = 0

    def compose(self) -> ComposeResult:
        cfg = resolve_model_config(self._model_id)
        dagi_root = Path(__file__).parent.parent
        with Horizontal(id="main-row"):
            with Vertical(id="conversation-col"):
                yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
                yield Static("", id="running-indicator")
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
        self.set_interval(0.1, self._tick_spinner)

    def on_prompt_input_submitted(self, event: PromptInput.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        if self._pending_ask is not None:
            ask_evt, container, options, _ = self._pending_ask
            self._pending_ask = None
            container.append(_resolve_option(raw, options))
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
        loop.pause()
        self.query_one(Sidebar).set_status("paused")
        self.query_one(ConversationPane).append_info(
            "[yellow]⏸ Paused — type a message and press Enter to continue[/yellow]"
        )
        self._hide_running_indicator()
        self._enable_input()

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

    def _tick_spinner(self) -> None:
        bar = self.query_one("#running-indicator", Static)
        if not bar.display:
            return
        self._spinner_idx = (self._spinner_idx + 1) % len(self._SPINNER)
        bar.update(f"  {self._SPINNER[self._spinner_idx]} Running…")

    def _show_running_indicator(self) -> None:
        bar = self.query_one("#running-indicator", Static)
        bar.update(f"  {self._SPINNER[0]} Running…")
        bar.display = True

    def _hide_running_indicator(self) -> None:
        self.query_one("#running-indicator", Static).display = False

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
