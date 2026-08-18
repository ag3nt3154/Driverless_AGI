"""Step-based tail boundary computation for subagent compaction.

Given a list of (turn, step) pairs and token counts, determines how many
recent steps to keep un-summarized. The boundary floors to whole steps
so the tail is always structurally clean.
"""
from __future__ import annotations

from dataclasses import dataclass

_CHARS_PER_TOKEN = 4
_IMAGE_PLACEHOLDER_TOKENS = 200


def estimate_tokens(msg: dict) -> int:
    """Rough token estimate for a single message (1 token ~ 4 chars).

    List-typed content (vision results with base64) uses a fixed
    placeholder to avoid base64 inflation.
    """
    content = msg.get("content")
    if isinstance(content, list):
        return _IMAGE_PLACEHOLDER_TOKENS
    text = str(content) if content else ""
    for tc in msg.get("tool_calls") or []:
        text += str(tc.get("function", {}).get("arguments", ""))
    return max(len(text) // _CHARS_PER_TOKEN, 4)


@dataclass(frozen=True, slots=True)
class TailBoundary:
    """Result of tail boundary computation."""
    tail_start_index: int
    keep_count: int
    tail_steps: list[tuple[int, int]]
    middle_steps: list[tuple[int, int]]

    @property
    def has_middle(self) -> bool:
        return len(self.middle_steps) > 0


def compute_tail_boundary(
    *,
    steps: list[tuple[int, int]],
    prompt_tokens: int,
    keep_recent_tokens: int,
) -> TailBoundary:
    """Compute the step-based tail boundary.

    Parameters
    ----------
    steps : List of (turn, step) pairs in chronological order.
    prompt_tokens : Total prompt tokens from the last API response.
    keep_recent_tokens : Token budget for the tail (from AgentConfig).

    Returns
    -------
    TailBoundary with the split point. ``tail_steps`` are the steps to
    keep; ``middle_steps`` are the steps to summarize.
    """
    n = len(steps)
    if n == 0 or prompt_tokens <= 0:
        return TailBoundary(
            tail_start_index=0,
            keep_count=n,
            tail_steps=list(steps),
            middle_steps=[],
        )

    avg_tokens_per_step = prompt_tokens / n
    keep_count = int(keep_recent_tokens / avg_tokens_per_step)
    keep_count = max(keep_count, 1)  # always keep at least one step
    keep_count = min(keep_count, n)

    if keep_count >= n:
        return TailBoundary(
            tail_start_index=0,
            keep_count=n,
            tail_steps=list(steps),
            middle_steps=[],
        )

    tail_start = n - keep_count
    return TailBoundary(
        tail_start_index=tail_start,
        keep_count=keep_count,
        tail_steps=list(steps[tail_start:]),
        middle_steps=list(steps[:tail_start]),
    )
