"""tools/spawn_agent — start a peer agent in its own GUI chat (main agent only)."""
from __future__ import annotations

from agent.base_tool import BaseTool


class SpawnAgentTool(BaseTool):
    name = "spawn_agent"
    description = (
        "Start a peer agent in its own GUI chat. It is visible in the Agents view, the "
        "Admiral can steer it, and it can ask the Admiral questions. It gets your model, "
        "folder and tools. The call returns at once with its handle. The peer's result "
        "arrives later as a board message to you: [done] with the handoff attached, or "
        "[max-continuations] / [error]. Use typed subagents instead for short, isolated "
        "jobs that must return a result in this turn. Follow up with post_board @<handle>."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Short name; the handle becomes <slug>_<8 hex>",
            },
            "task": {
                "type": "string",
                "minLength": 1,
                "description": "The full task for the peer",
            },
            "close_on_done": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Close the peer after it reports [done]; it stays open after an error"
                ),
            },
        },
        "required": ["slug", "task"],
    }

    def __init__(self, *, spawn):
        self._spawn = spawn

    def run(self, slug, task, close_on_done: bool = False) -> str:
        if not isinstance(slug, str):
            raise ValueError("slug must be a string")
        if not isinstance(task, str):
            raise ValueError("task must be a string")
        if type(close_on_done) is not bool:
            raise ValueError("close_on_done must be a boolean")
        task = task.strip()
        if not task:
            raise ValueError("task must not be empty")
        return self._spawn(slug, task, close_on_done)
