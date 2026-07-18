from __future__ import annotations

import threading
from pathlib import Path

from rich.table import Table

from agent import DAGI_ROOT

from .conversation import ConversationPane
from .prompt_input import PromptInput
from .sidebar import Sidebar
from .utils import _SLASH_HELP, _Stats


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
        from agent.config_loader import get_model_display_name, list_model_ids, resolve_model_config
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
        self._config = resolve_model_config(arg, project_path=self._project_path)
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
        from agent.config_loader import get_model_display_name, resolve_model_config
        self._config = resolve_model_config(self._model_id, project_path=new)
        # If no explicit model was chosen, pick up the new project's default_model.
        resolved_id = getattr(self._config, 'model_id', '') or self._model_id or ''
        if resolved_id and resolved_id != self._model_id:
            self._model_id = resolved_id
            self._model_name = get_model_display_name(resolved_id)
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
                result = loop.compact_tool.compact(force=True)
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
