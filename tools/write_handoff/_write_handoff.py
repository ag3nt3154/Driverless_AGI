"""tools/write_handoff — submit a final report and end the current turn.

For subagents: writes content to a baked-in file path.
For the main agent (handoff_path=None): returns content for display in chat.
Both cases return ToolResult with SideEffect.END_TURN, which causes
agent/_tool_dispatch.handle_end_turn() to terminate the loop immediately.
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult


class WriteHandoffTool(BaseTool):
    """Submit a final report and end the current turn."""

    name = "write_handoff"
    description = (
        "Submit your final report and end your turn. Write your complete report "
        "as free-form markdown in `content`. After calling this tool your turn "
        "ends immediately — do not continue working."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full report in markdown.",
            },
        },
        "required": ["content"],
    }

    def __init__(self, handoff_path: Path | None = None) -> None:
        self._handoff_path = Path(handoff_path) if handoff_path is not None else None

    def run(self, content: str) -> ToolResult:
        if self._handoff_path is not None:
            self._handoff_path.parent.mkdir(parents=True, exist_ok=True)
            self._handoff_path.write_text(content, encoding="utf-8")
        return ToolResult(output=content, side_effect=SideEffect.END_TURN)
