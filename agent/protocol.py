"""agent/protocol.py — typed tool-result protocol and shared constants.

Single source of truth for all control-flow types and cross-module constants
that were previously scattered as magic strings across tool modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class SideEffect(Enum):
    """Side effects a tool can request from the agent loop."""

    END_TURN = auto()
    ALL_TASKS_RESOLVED = auto()
    RELOAD_SKILLS = auto()
    SWITCH_MODEL = auto()
    SET_ACTIVE_PLAN = auto()


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Typed return value from a tool.

    ``output`` is what the LLM sees as the tool response.
    ``side_effect`` (optional) tells the dispatch layer to trigger a
    loop-level action without in-band string matching.
    ``side_effect_data`` carries parameters for the side effect
    (e.g. ``{"tier": "plan"}`` for SWITCH_MODEL).
    """

    output: str
    side_effect: SideEffect | None = None
    side_effect_data: dict | None = field(default=None, repr=False)

    @property
    def is_plain(self) -> bool:
        return self.side_effect is None


# ── Shared constants (previously duplicated across modules) ──────────

SESSION_CONTEXT_HEADER = "## Session Context"

CONTEXT_SUMMARY_PREFIX = "[CONTEXT SUMMARY"

LIST_ENCODING_PREFIX = "__list__:"
