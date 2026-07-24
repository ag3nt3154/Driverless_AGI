"""tools/escalate_issue.py — Let a worker/review subagent raise a blocking issue to the main agent.

Writes a sidecar "<handoff-stem>_escalation.md" file next to the subagent's own
handoff path. This file is the escalation channel's data format: a planned change
to tools/_subagent_runner.py will poll for it and, on finding it, terminate the
subagent subprocess; a planned change to tools/spawn_subagent.py will then surface
its contents to the main agent as a tool result. Until those changes land, this
tool only writes the file — nothing yet consumes it. This is designed as a
fast-fail channel, not live Q&A: the subagent's turn should end the moment it
calls this tool.
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool


class EscalateIssueTool(BaseTool):
    """Write an escalation report next to the subagent's handoff file."""

    name = "escalate_issue"
    description = (
        "Raise a blocking question or issue to the main agent immediately, "
        "without waiting for your handoff report to be read. Use this when you "
        "hit an ambiguity, missing dependency, or blocker you cannot resolve on "
        "your own. After calling this tool, immediately end your turn — do not "
        "continue working."
    )

    _parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The specific question or blocking issue to raise to the main agent.",
            },
            "context": {
                "type": "string",
                "description": (
                    "Relevant context: what you were doing, what you tried, and "
                    "why you are blocked."
                ),
            },
        },
        "required": ["question", "context"],
    }

    def __init__(self, handoff_path: Path) -> None:
        self._handoff_path = Path(handoff_path)

    def run(self, question: str, context: str) -> str:
        escalation_path = self._handoff_path.with_name(
            self._handoff_path.stem + "_escalation.md"
        )
        escalation_path.parent.mkdir(parents=True, exist_ok=True)
        escalation_path.write_text(
            f"# Escalation\n\n## Question\n{question}\n\n## Context\n{context}\n",
            encoding="utf-8",
        )
        return (
            "Escalation recorded. End your turn now — do not continue working. "
            "The main agent will answer and, if needed, re-spawn you with guidance."
        )
