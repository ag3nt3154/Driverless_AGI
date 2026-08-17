"""agent/session_events.py — Session event vocabulary.

Pure constants and reason builders for the append-only session log. No logic,
no imports from ``agent.*`` — this is the base of the dependency chain
(``session_events`` <- ``session_surface`` <- ``session_log`` <- ``loop``), so
nothing here may import upward.

The event set mirrors ``deepseek-ai/deepseek-harness`` (``packages/core/session``),
trimmed by YAGNI: ``assistant/chunk``, ``request/context``, ``hook/*`` and
``llm/retry`` are deliberately omitted until a producer exists.
"""
from __future__ import annotations

# ── Format version ────────────────────────────────────────────────────────
# Single monotonic integer. Bump only when an older runtime could no longer
# read a new log with full semantic correctness. Incompatible logs are
# rejected with a directional message, never migrated.
SESSION_FORMAT_VERSION = 2

# ── Boundary events (log-only) ────────────────────────────────────────────
TURN_START = "turn/start"
TURN_END = "turn/end"
STEP_START = "step/start"
STEP_END = "step/end"

# ── Surface events (the only message-producing types) ─────────────────────
USER_MESSAGE = "user/message"
ASSISTANT_MESSAGE = "assistant/message"
TOOL_RESULT = "tool/result"
#: The summary message that replaces a compacted span. A distinct type rather
#: than a flagged ``user/message`` so that "did the human say this?" stays a
#: structural question rather than an inference over a data field.
CONTEXT_COMPACTION = "context/compaction"

# ── Log-only events ───────────────────────────────────────────────────────
TOOL_CALL = "tool/call"
REQUEST_HEADER = "request/header"
PLAN_WRITE = "plan/write"
END_SEED = "session/end-seed"
BRANCH_START = "branch/start"

#: Closed set. An event type outside this set may never enter the surface,
#: which makes it structurally impossible for bookkeeping to cost tokens.
SURFACE_EVENT_TYPES: frozenset[str] = frozenset(
    {USER_MESSAGE, ASSISTANT_MESSAGE, TOOL_RESULT, CONTEXT_COMPACTION}
)

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        TURN_START,
        TURN_END,
        STEP_START,
        STEP_END,
        USER_MESSAGE,
        ASSISTANT_MESSAGE,
        TOOL_RESULT,
        CONTEXT_COMPACTION,
        TOOL_CALL,
        REQUEST_HEADER,
        PLAN_WRITE,
        END_SEED,
        BRANCH_START,
    }
)


# ── TurnEndReason builders ────────────────────────────────────────────────
# A ``kind``-tagged sum type. Variants are producer-gated: add one only when
# something actually emits it.

def reason_completed() -> dict:
    """The turn ended on <<END_OF_RESPONSE>> or <<TASK_END>>."""
    return {"kind": "completed"}


def reason_max_continuations() -> dict:
    """The turn hit ``config.max_continuations`` without a terminal sentinel."""
    return {"kind": "max-continuations"}


def reason_aborted(cause: str) -> dict:
    """A cancellation request interrupted the live turn.

    ``cause`` is one of ``"user"``, ``"parent"``, ``"hook"``, ``"disposed"``.
    """
    return {"kind": "aborted", "cause": {"kind": cause}}


def reason_error(message: str, code: str = "UNKNOWN") -> dict:
    """The turn failed. ``error`` is always structured, never a bare string."""
    return {"kind": "error", "error": {"message": message, "code": code}}


def reason_interrupted() -> dict:
    """A crash-orphaned turn closed on reload.

    The loop never emits this — only crash repair does — so a crash is always
    distinguishable from a cancel in the durable transcript.
    """
    return {"kind": "interrupted"}
