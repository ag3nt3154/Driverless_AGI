from __future__ import annotations

from collections.abc import Callable

from agent.base_tool import BaseTool

EMOTES = ["default", "confused", "happy", "serious", "funny"]


class EmoteTool(BaseTool):
    name = "emote"
    description = (
        "Display an emote on the sidebar to express your current state or mood. "
        "Use this to react to what is happening — a task result, user feedback, or your own situation."
        "Available emotes: " + ", ".join(EMOTES)
    )
    _parameters = {
        "type": "object",
        "properties": {
            "emote": {
                "type": "string",
                "enum": EMOTES,
                "description": "The emote to display.",
            }
        },
        "required": ["emote"],
    }

    def __init__(self, on_emote: Callable[[str], None] | None = None) -> None:
        self._on_emote = on_emote

    def run(self, emote: str) -> str:
        if emote not in EMOTES:
            return f"Unknown emote '{emote}'. Valid: {', '.join(EMOTES)}"
        if self._on_emote:
            self._on_emote(emote)
        return f"*{emote}*"
