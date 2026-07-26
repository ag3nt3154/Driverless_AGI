"""tools/write_handoff.py — Let a worker/review subagent submit its final handoff report.

Writes `content` verbatim to the handoff path baked in at construction. The model
never sees or chooses the path — the tool's schema exposes only a `content`
parameter. `agent/loop.py` scans tool results for the `<<HANDOFF_WRITTEN>>`
sentinel returned here and terminates the subagent's turn the moment it appears
(see `AgentLoop._handle_write_handoff`).
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool


class WriteHandoffTool(BaseTool):
    """Write a subagent's final handoff report to its baked-in path."""

    name = "write_handoff"
    description = (
        "Submit your final handoff report. Write your complete report as free-form "
        "markdown in `content` — there is no required structure. This overwrites any "
        "previous handoff you wrote. After calling this tool, immediately end your "
        "turn — do not continue working."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The full handoff report, written verbatim to the handoff file.",
            },
        },
        "required": ["content"],
    }

    def __init__(self, handoff_path: Path) -> None:
        self._handoff_path = Path(handoff_path)

    def run(self, content: str) -> str:
        self._handoff_path.parent.mkdir(parents=True, exist_ok=True)
        self._handoff_path.write_text(content, encoding="utf-8")
        return "Handoff written. <<HANDOFF_WRITTEN>> Your turn ends now."
