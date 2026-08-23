from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from agent import DAGI_ROOT
from tui.utils import _SLASH_HELP

_DESC_WRAP = 72


def _wrap_desc(desc: str, indent: int = 4) -> list[str]:
    prefix = " " * indent
    return textwrap.wrap(desc, width=_DESC_WRAP, initial_indent=prefix,
                         subsequent_indent=prefix)

if TYPE_CHECKING:
    from agent.loop import AgentConfig
    from pyside_gui.conversation import ConversationView
    from pyside_gui.left_sidebar import LeftSidebar
    from pyside_gui.right_sidebar import RightSidebar


@dataclass
class UIWidgets:
    conversation: "ConversationView"
    right_sidebar: "RightSidebar"
    left_sidebar: "LeftSidebar"


class SlashCommandHandler:
    def __init__(
        self,
        widgets: UIWidgets,
        config: "AgentConfig",
        project_path: Path,
    ) -> None:
        self._w = widgets
        self._config = config
        self._project_path = project_path
        self._skill_map: dict = {}
        self._workflow_map: dict = {}
        self._active_loop = None
        self._worker_alive: Callable[[], bool] = lambda: False

    def set_active_loop(self, loop) -> None:
        self._active_loop = loop

    def set_worker_alive_check(self, fn: Callable[[], bool]) -> None:
        self._worker_alive = fn

    def load_maps(self) -> None:
        from agent.skills import SkillLoader
        from agent.workflows import WorkflowLoader
        dagi_root = DAGI_ROOT
        skill_roots = [
            dagi_root / ".dagi" / "skills",
            self._project_path / ".dagi" / "skills",
        ]
        self._skill_map = {
            f"/{s.name}": s
            for s in SkillLoader().load_all(skill_roots, dagi_root=dagi_root)
        }
        self._workflow_map = {
            f"/{w.name}": w
            for w in WorkflowLoader().load_all(
                [self._project_path / ".dagi" / "workflow"]
            )
        }

    def handle(self, raw: str) -> str | None:
        """Process a slash command.

        Returns a task string if the command should be dispatched to the agent
        loop, '__EXIT__' for quit, or None for commands handled in-place.
        """
        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else None

        if cmd == "/exit":
            return "__EXIT__"
        elif cmd == "/clear":
            return self._cmd_clear()
        elif cmd == "/model":
            return self._cmd_model(arg)
        elif cmd == "/wd":
            return self._cmd_wd(arg)
        elif cmd == "/compact":
            return self._cmd_compact()
        elif cmd == "/wtf":
            return self._cmd_wtf(arg)
        elif cmd == "/help":
            return self._cmd_help()
        elif cmd == "/tools":
            return self._cmd_tools()
        elif cmd == "/skills":
            return self._cmd_skills()
        elif cmd == "/workflows":
            return self._cmd_workflows()
        elif cmd == "/copy":
            return self._cmd_copy()
        elif cmd == "/hist":
            return self._cmd_hist(arg)
        elif cmd == "/init":
            return self._cmd_init()
        elif cmd in self._skill_map:
            return self._cmd_skill(cmd, arg)
        elif cmd in self._workflow_map:
            return self._cmd_workflow(cmd, arg)
        else:
            self._w.conversation.append_error(f"Unknown command: {cmd}  (type /help)")
            return None

    # ── Individual command handlers ────────────────────────────────────────────

    def _cmd_help(self) -> None:
        lines = ["Commands:"]
        for name, desc in _SLASH_HELP.items():
            lines.append(f"  {name}")
            lines.extend(_wrap_desc(desc))
        self._w.conversation.append_info("\n".join(lines))
        return None

    def _cmd_clear(self) -> None:
        if self._worker_alive():
            self._w.conversation.append_info(
                "Agent is running — press ESC to pause first"
            )
            return None
        self._w.conversation.clear()
        self._active_loop = None
        self._w.right_sidebar.update_stats(0, 0, None, 0)
        self._w.right_sidebar.update_plan([], "")
        self._w.conversation.append_info("Context cleared — new session")
        return None

    def _cmd_model(self, arg: str | None) -> None:
        from agent.config_loader import list_model_ids, resolve_model_config
        conv = self._w.conversation
        if not arg:
            ids = list_model_ids()
            lines = ["Available models:"]
            for mid in ids:
                marker = " <-- active" if mid == self._config.model_id else ""
                lines.append(f"  {mid}{marker}")
            conv.append_info("\n".join(lines))
            return None
        if arg not in list_model_ids():
            conv.append_error(f"Unknown model: {arg}")
            return None
        self._config = resolve_model_config(arg, project_path=self._project_path)
        self._w.right_sidebar.update_model(self._config.display_name)
        conv.append_info(f"Model -> {self._config.display_name}")
        return None

    def _cmd_wd(self, arg: str | None) -> None:
        conv = self._w.conversation
        if not arg:
            conv.append_info(f"Working directory: {self._project_path}")
            return None
        new = Path(arg).expanduser()
        if not new.is_absolute():
            new = self._project_path / new
        new = new.resolve()
        if not new.is_dir():
            conv.append_error(f"Not a directory: {new}")
            return None
        self._project_path = new
        from agent.config_loader import resolve_model_config
        self._config = resolve_model_config(None, project_path=new)
        self._w.right_sidebar.update_model(self._config.display_name)
        self._w.right_sidebar.set_project_path(new)
        self._w.left_sidebar.set_project_path(new)
        self._active_loop = None
        self.load_maps()
        conv.append_info(f"Working directory -> {new}")
        return None

    def _cmd_compact(self) -> str:
        return "__COMPACT__"

    def _cmd_wtf(self, arg: str | None) -> str:
        return f"__WTF__{arg or ''}"

    def _cmd_tools(self) -> None:
        conv = self._w.conversation
        if self._active_loop is None:
            conv.append_info("No active session — start a task first.")
            return None
        lines = ["Registered tools:"]
        for name, desc in self._active_loop.registry.list_tools():
            lines.append(f"  {name}")
            if desc:
                lines.extend(_wrap_desc(desc))
        conv.append_info("\n".join(lines))
        return None

    def _cmd_skills(self) -> None:
        skills = sorted(self._skill_map.values(), key=lambda s: s.name)
        if not skills:
            self._w.conversation.append_info("No skills loaded.")
            return None
        lines = ["Loaded skills:"]
        for s in skills:
            lines.append(f"  /{s.name}")
            if s.description:
                lines.extend(_wrap_desc(s.description))
        self._w.conversation.append_info("\n".join(lines))
        return None

    def _cmd_workflows(self) -> None:
        workflows = sorted(self._workflow_map.values(), key=lambda w: w.name)
        if not workflows:
            self._w.conversation.append_info("No workflows loaded.")
            return None
        lines = ["Loaded workflows:"]
        for w in workflows:
            lines.append(f"  /{w.name}")
            if w.description:
                lines.extend(_wrap_desc(w.description))
        self._w.conversation.append_info("\n".join(lines))
        return None

    def _cmd_copy(self) -> str:
        return "__COPY__"

    def _cmd_hist(self, arg: str | None) -> None:
        self._w.left_sidebar.activate_view("history")
        return None

    def _cmd_init(self) -> None:
        from agent.cli_utils import _cmd_init
        _cmd_init(self._project_path)
        self._w.conversation.append_info("Initialized .dagi/ scaffold")
        return None

    def _cmd_skill(self, cmd: str, arg: str | None) -> str:
        from agent.cli_utils import _skill_invocation_message
        return _skill_invocation_message(self._skill_map[cmd].name, arg or "")

    def _cmd_workflow(self, cmd: str, arg: str | None) -> str:
        from tools.workflow import load_workflow_content
        wf = load_workflow_content(
            self._workflow_map[cmd].name,
            [self._project_path / ".dagi" / "workflow"],
        )
        extra = f"\n\nAdditional instructions: {arg}" if arg else ""
        return wf + extra
