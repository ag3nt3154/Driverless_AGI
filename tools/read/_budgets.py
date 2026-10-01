"""tools/read/_budgets.py — Budget arithmetic for the large-file reader.

Owns all capacity numbers derived from parent snapshot P and child AgentConfig.
Never reads YAML directly; callers pass already-resolved config objects.

Terminology
-----------
P  — parent's effective reserve_tokens at invocation (immutable snapshot).
C  — child's context_window.
R  — child's reserve_tokens.
O  — tightest output cap: min(R, max_output_tokens if set, client-script cap).
M  — estimator margin: ceil(R / 8).
E  — token estimator for a JSON request dict (//4 rule over the serialised request).
F  — shared output-filter estimator from output_filter.estimate_tool_output (//4 rule).
S  — running-summary cap (chars) carried from chunk to chunk.

Each reader call holds only base prompt + running summary + one chunk, so the
per-call fit check is the only context bound; file length is unlimited.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent._loop_config import AgentConfig


# ---------------------------------------------------------------------------
# Structured capacity failure
# ---------------------------------------------------------------------------

class ReaderCapacityError(Exception):
    """Raised when a reader budget check fails.

    Carries machine-readable fields so the parent can format an actionable
    message without string parsing. recommendation must be one of the three
    canonical strings so tests can assert failure modes unambiguously.
    """

    NARROW_RANGE = "narrow the selected range"
    LARGER_MODEL = "configure a larger context_window model"
    FEWER_PAGES  = "reduce the number of selected pages"

    def __init__(
        self,
        *,
        required_tokens: int,
        available_tokens: int,
        recommendation: str,
    ) -> None:
        self.required_tokens  = required_tokens
        self.available_tokens = available_tokens
        self.recommendation   = recommendation

    def __str__(self) -> str:
        return (
            f"Reader capacity exceeded: needs ~{self.required_tokens:,} tokens "
            f"but only {self.available_tokens:,} available. "
            f"Recommendation: {self.recommendation}"
        )


# ---------------------------------------------------------------------------
# Immutable budget snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReaderLimits:
    """Immutable derived budget numbers for one reader invocation."""
    parent_reserve:   int   # P
    context_window:   int   # C
    output_reserve:   int   # O
    estimator_margin: int   # M
    max_repairs:      int   # from config.max_continuations


# ---------------------------------------------------------------------------
# Budget resolution
# ---------------------------------------------------------------------------

def resolve_reader_limits(
    parent_reserve: int,
    config: AgentConfig,
    *,
    request_kwargs: dict,
) -> ReaderLimits:
    """Derive ReaderLimits from the parent snapshot and the child's config.

    Parameters
    ----------
    parent_reserve
        P — the parent's effective reserve_tokens at the moment of invocation.
        Must be positive; non-positive disables the reader.
    config
        Child's resolved AgentConfig (worker or inherited).
    request_kwargs
        Spread kwargs from the child's client script or config, may contain
        ``max_tokens`` or ``max_completion_tokens`` to tighten O.
    """
    C = config.context_window
    R = config.reserve_tokens

    # Derive O: tighten with max_output_tokens then client-script cap.
    O = R
    if config.max_output_tokens is not None and config.max_output_tokens > 0:
        O = min(O, config.max_output_tokens)
    client_cap = request_kwargs.get("max_tokens") or request_kwargs.get("max_completion_tokens")
    if client_cap is not None and int(client_cap) > 0:
        O = min(O, int(client_cap))

    M = math.ceil(R / 8)

    if C <= 0:
        raise ValueError(f"context_window must be positive, got {C}")
    if R <= 0:
        raise ValueError(f"reserve_tokens must be positive, got {R}")
    if R >= C:
        raise ValueError(f"reserve_tokens ({R}) must be less than context_window ({C})")
    if O <= 0:
        raise ValueError(f"derived output_reserve must be positive, got {O}")
    if parent_reserve <= 0:
        raise ReaderCapacityError(
            required_tokens=1,
            available_tokens=parent_reserve,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )

    return ReaderLimits(
        parent_reserve=parent_reserve,
        context_window=C,
        output_reserve=O,
        estimator_margin=M,
        max_repairs=config.max_continuations,
    )


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------

def estimate_reader_request(request: dict) -> int:
    """E: token estimate for a request — //4 over its canonical JSON.

    Same units as every other budget number (C, O, M), matching the parent's
    F estimator. The margin M absorbs tokenizer variance.
    """
    return len(json.dumps(request, ensure_ascii=False)) // 4


def estimate_reader_text(text: str) -> int:
    """Token estimate for raw text: len // 4, matching the parent F estimator.

    Used to supply Chonkie's count_callable and for per-chunk estimates.
    Deliberate consistency with output_filter._CHARS_PER_TOKEN.
    """
    return len(text) // 4


# ---------------------------------------------------------------------------
# Per-call fit guard
# ---------------------------------------------------------------------------

def require_context_fit(request: dict, limits: ReaderLimits) -> None:
    """Raise ReaderCapacityError if E(request) + O + M > C.

    Called before every provider API call. An unexpected response may still
    exceed the budget, but this prevents obviously doomed calls.
    """
    e = estimate_reader_request(request)
    needed = e + limits.output_reserve + limits.estimator_margin
    if needed > limits.context_window:
        raise ReaderCapacityError(
            required_tokens=needed,
            available_tokens=limits.context_window,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )


# ---------------------------------------------------------------------------
# Chunk sizing
# ---------------------------------------------------------------------------

# Upper bound on one chunk: bigger chunks make for thinner notes per line.
MAX_CHUNK_TOKENS = 32_000


def chunk_token_budget(limits: ReaderLimits, *, fixed_tokens: int) -> int:
    """K: source tokens per chunk so one call fits C.

    fixed_tokens is everything in the request except the chunk itself
    (system prompt, instructions, running summary at its cap). The result is
    scaled by 0.8 because chunks are sent with line-number prefixes.
    """
    room = (
        limits.context_window - fixed_tokens
        - limits.output_reserve - limits.estimator_margin
    )
    K = min(int(room * 0.8), MAX_CHUNK_TOKENS)
    if K <= 0:
        raise ReaderCapacityError(
            required_tokens=fixed_tokens + limits.output_reserve + limits.estimator_margin + 1,
            available_tokens=limits.context_window,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )
    return K


# ---------------------------------------------------------------------------
# Parent fit guard (final boundary)
# ---------------------------------------------------------------------------

def require_parent_fit(text: str, parent_reserve: int) -> None:
    """Raise ReaderCapacityError if F(text) >= parent_reserve.

    Uses the shared output_filter estimator so parent threshold and child
    check are identical. Called by the finalizer before writing the handoff.
    """
    from tools.output_filter import estimate_tool_output
    estimated = estimate_tool_output(text)
    if estimated >= parent_reserve:
        raise ReaderCapacityError(
            required_tokens=estimated,
            available_tokens=parent_reserve - 1,
            recommendation=ReaderCapacityError.NARROW_RANGE,
        )
