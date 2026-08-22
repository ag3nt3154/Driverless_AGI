from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from rich.table import Table

from agent import DAGI_ROOT

from .conversation import ConversationPane
from .prompt_input import PromptInput
from .sidebar import Sidebar
from .utils import _SLASH_HELP, _Stats


def _copy_to_clipboard(text: str) -> None:
    if sys.platform == "win32":
        subprocess.run(["clip"], input=text.encode("utf-16-le"), check=True)
    elif sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode(), check=True)
    else:
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)


class SlashCommandsMixin:
    """Slash-command handlers mixed into DagiApp. All methods receive the live DagiApp as self."""

    def _load_maps(self) -> None:
        from agent.skills import SkillLoader
        from agent.workflows import WorkflowLoader
        dagi_root = DAGI_ROOT
        skill_roots = [dagi_root / ".dagi" / "skills", self._project_path / ".dagi" / "skills"]
        self._skill_map = {
            f"/{s.name}": s for s in SkillLoader().load_all(skill_roots, dagi_root=dagi_root)
        }
        self._workflow_map = {
            f"/{w.name}": w for w in WorkflowLoader().load_all(
                [self._project_path / ".dagi" / "workflow"]
            )
        }

    def _handle_slash(self, raw: str) -> None:  # noqa: C901
        conv = self.query_one(ConversationPane)
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd == "/exit":
            self.exit()
        elif cmd == "/clear":
            if self._worker and self._worker.is_alive():
                conv.append_info(
                    "[yellow]⚠ Agent is running — press ESC to pause first, then /clear[/yellow]"
                )
                return
            conv.clear()
            self._active_loop = None
            self._current_loop_ref = []
            self._stats = _Stats()
            sidebar = self.query_one(Sidebar)
            sidebar.update_stats(0, 0, None, 0)
            sidebar.update_plan([], "")
            conv.append_info("[green]✓ Context cleared — new session[/green]")
        elif cmd == "/model":
            self._cmd_model(arg)
        elif cmd == "/wd":
            self._cmd_wd(arg)
        elif cmd == "/compact":
            self._cmd_compact()
        elif cmd == "/wtf":
            self._cmd_wtf(arg)
        elif cmd == "/help":
            self._cmd_help()
        elif cmd == "/tools":
            self._cmd_tools()
        elif cmd == "/skills":
            self._cmd_skills()
        elif cmd == "/workflows":
            self._cmd_workflows()
        elif cmd == "/copy":
            self._cmd_copy()
        elif cmd == "/hist":
            self._cmd_hist(arg)
        elif cmd == "/init":
            from agent.cli_utils import _cmd_init
            _cmd_init(self._project_path)
        elif cmd in self._skill_map:
            from agent.cli_utils import _skill_invocation_message
            self._dispatch_agent(_skill_invocation_message(self._skill_map[cmd].name, arg or ""))
        elif cmd in self._workflow_map:
            from tools.workflow import load_workflow_content
            wf = load_workflow_content(
                self._workflow_map[cmd].name,
                [self._project_path / ".dagi" / "workflow"],
            )
            self._dispatch_agent(wf + (f"\n\nAdditional instructions: {arg}" if arg else ""))
        else:
            conv.append_info(f"[red]Unknown command:[/red] {cmd}  · type [bold]/help[/bold]")

    def _cmd_help(self) -> None:
        conv = self.query_one(ConversationPane)
        tbl = Table(title="Commands", border_style="dim", padding=(0, 1))
        tbl.add_column("Command", style="bold cyan")
        tbl.add_column("Description", style="dim")
        for cmd, desc in _SLASH_HELP.items():
            tbl.add_row(cmd, desc)
        conv.write(tbl)

    def _cmd_model(self, arg: str | None) -> None:
        from agent.config_loader import list_model_ids, resolve_model_config
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
        self._config = resolve_model_config(arg, project_path=self._project_path)
        self._model_name = self._config.display_name
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
        from agent.config_loader import resolve_model_config
        # Pass model_id=None so the project's default_model takes precedence over the
        # previously-active model. Passing self._model_id would pin the old model and
        # prevent the project config from ever changing it.
        self._config = resolve_model_config(None, project_path=new)
        self._model_id = self._config.model_id
        self._model_name = self._config.display_name
        sidebar = self.query_one(Sidebar)
        sidebar.update_model(self._model_name)
        sidebar._context_window = self._config.context_window
        sidebar._reserve_tokens = self._config.reserve_tokens
        self._active_loop = None
        self._load_maps()
        sidebar.set_project_path(new)
        conv.append_info(f"[green]✓ Working directory →[/green] {new}")

    def _cmd_compact(self) -> None:
        conv = self.query_one(ConversationPane)
        if self._active_loop is None:
            conv.append_info("[dim]Nothing to compact — no active conversation.[/dim]")
            return
        conv.append_info("[dim]⏳ Compacting context…[/dim]")
        loop = self._active_loop

        def _do_compact() -> None:
            try:
                result = loop.compact(force=True)
            except Exception as exc:
                self.call_from_thread(conv.append_error, f"Compact failed: {exc}")
                return
            if result.did_compact:
                self._stats.update_tokens(
                    result.summary_input_tokens, result.summary_output_tokens, result.summary_cost
                )
                self.call_from_thread(
                    conv.append_info,
                    f"[yellow]⚡ Context compacted — removed {result.removed_count} messages, "
                    f"kept {len(loop._messages)}[/yellow]",
                )
            else:
                self.call_from_thread(conv.append_info, "[dim]Nothing to compact.[/dim]")

        threading.Thread(target=_do_compact, daemon=True).start()

    def _cmd_wtf(self, description: str | None) -> None:
        """Run a read-only diagnostic without changing the parent loop's state."""
        conv = self.query_one(ConversationPane)
        loop = self._active_loop
        if loop is None:
            conv.append_info("[dim]Nothing to diagnose — no active conversation.[/dim]")
            return
        if self._wtf_running:
            conv.append_info("[yellow]⚠ A /wtf diagnosis is already running.[/yellow]")
            return
        parent_is_running = bool(self._worker and self._worker.is_alive())
        paused = parent_is_running and not loop._pause_event.is_set()
        if parent_is_running and not paused:
            conv.append_info("[yellow]⚠ Agent is running — press ESC to pause before /wtf.[/yellow]")
            return

        previous_status = "paused" if paused else "idle"
        self._wtf_running = True
        self.query_one("#prompt", PromptInput).disabled = True
        self._show_running_indicator()
        self.query_one(Sidebar).set_status("running")

        def _do_wtf() -> None:
            try:
                if paused and not loop.wait_for_pause_checkpoint(timeout=5.0):
                    raise RuntimeError("paused loop did not reach its checkpoint; try /wtf again")
                result = loop.run_wtf(description)
            except Exception as exc:
                self.call_from_thread(self._finish_wtf_failure, str(exc), previous_status)
                return
            report_path = Path(result.report_path).resolve()
            self.call_from_thread(
                self._finish_wtf_success, result.description, report_path, previous_status
            )

        self._wtf_worker = threading.Thread(target=_do_wtf, daemon=True)
        self._wtf_worker.start()

    def _finish_wtf_success(self, description: str, report_path: Path, previous_status: str) -> None:
        self.query_one(ConversationPane).append_info(
            f"[green]✓ Diagnosis:[/green] {description}\n[dim]Report:[/dim] {report_path}"
        )
        self._restore_wtf_ui(previous_status)

    def _finish_wtf_failure(self, error: str, previous_status: str) -> None:
        self.query_one(ConversationPane).append_error(f"/wtf failed: {error}")
        self._restore_wtf_ui(previous_status)

    def _restore_wtf_ui(self, previous_status: str) -> None:
        self._wtf_running = False
        self._wtf_worker = None
        self._hide_running_indicator()
        self.query_one(Sidebar).set_status(previous_status)
        self._enable_input()

    def _cmd_copy(self) -> None:
        from tui.history import CopyScreen
        conv = self.query_one(ConversationPane)
        if self._worker and self._worker.is_alive():
            conv.append_info("[yellow]⚠ Agent is running — press ESC to pause first[/yellow]")
            return
        messages = self._active_loop._messages if self._active_loop else []
        self.push_screen(CopyScreen(messages))

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
        """Open the session history picker screen."""
        from tui.history import HistoryScreen
        conv = self.query_one(ConversationPane)
        if self._worker and self._worker.is_alive():
            conv.append_info("[yellow]⚠ Agent is running — press ESC to pause it first[/yellow]")
            return
        try:
            n = int(arg) if arg else 20
        except ValueError:
            n = 20
        logs_dir = self._project_path / ".dagi" / "logs"
        if not logs_dir.exists():
            conv.append_info("[dim]No session history found in .dagi/logs/[/dim]")
            return
        self.push_screen(HistoryScreen(logs_dir, max_sessions=n))
