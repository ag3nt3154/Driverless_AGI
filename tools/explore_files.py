from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.base_tool import BaseTool
from agent.prompts import load_prompt

if TYPE_CHECKING:
    from agent.session import SessionTracker

_SYSTEM_PROMPT = load_prompt("explore_files.md")


class ExploreFilesTool(BaseTool):
    name = "explore_files"
    description = (
        "Delegate broad file exploration to a sub-agent with read, grep, and find. "
        "Returns a structured Markdown summary. "
        "Use for open-ended discovery: mapping a module, finding all usages of a symbol, "
        "or understanding an unfamiliar subsystem. "
        "For targeted reads of specific known files, use read/grep/find directly."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Open-ended exploration question.",
            },
            "paths": {
                "type": "string",
                "description": (
                    "Optional comma-separated directory paths to focus on "
                    "(e.g. 'src/,tests/'). Omit for whole-project search."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(self, config, callbacks=None, cwd: Path = Path("."), allowed_roots=None, tracker: "SessionTracker | None" = None):
        self._config = config
        self._callbacks = callbacks
        self._cwd = cwd
        self._allowed_roots = allowed_roots
        self._tracker = tracker

    def run(self, task: str, paths: str | None = None) -> str:
        try:
            from agent.sub_agent import SubAgentConfig, SubAgentRunner
            from tools.find import FindTool
            from tools.grep import GrepTool
            from tools.read import ReadTool

            effective_roots = self._allowed_roots or [self._cwd]
            sub_tools = [
                ReadTool(cwd=self._cwd, allowed_roots=effective_roots),
                GrepTool(cwd=self._cwd, allowed_roots=effective_roots),
                FindTool(cwd=self._cwd, allowed_roots=effective_roots),
            ]
            full_task = task if not paths else f"{task}\n\nFocus on these paths: {paths}"

            subagent_id = uuid4().hex
            depth = self._tracker._depth if self._tracker else 0

            if self._tracker:
                self._tracker.record_subagent_start(subagent_id, "explore_files", full_task, depth)

            runner = SubAgentRunner(
                config=self._config,
                tools=sub_tools,
                system_prompt=_SYSTEM_PROMPT,
                callbacks=self._callbacks,
                sub_cfg=SubAgentConfig(prefix="[explore-files]"),
                parent_tracker=self._tracker,
                subagent_id=subagent_id,
            )
            result = runner.run(full_task)

            if self._tracker:
                self._tracker.record_subagent_end(subagent_id, result, depth)

            return result
        except Exception as e:
            return f"[explore_files error] {e}"
