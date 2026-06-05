from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from agent.base_tool import BaseTool

if TYPE_CHECKING:
    from agent.session import SessionTracker


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
        from tools._subagent_runner import run_subagent
        from uuid import uuid4 as _uuid4

        full_task = task if not paths else f"{task}\n\nFocus on these paths: {paths}"
        subagent_id = _uuid4().hex[:8]
        handoff_path = self._config.project_path / ".dagi" / "handoffs" / f"explore_files_{subagent_id}.md"
        depth = self._tracker._depth if self._tracker else 0

        if self._tracker:
            self._tracker.record_subagent_start(subagent_id, "explore_files", full_task, depth)

        result = run_subagent("explore_files", full_task, self._config.project_path, handoff_path, 300)

        if self._tracker:
            self._tracker.record_subagent_end(subagent_id, str(result), depth)

        if result["status"] == "ok":
            return Path(result["handoff"]).read_text(encoding="utf-8")
        return f"[explore_files error] {result.get('message', result['status'])}"
