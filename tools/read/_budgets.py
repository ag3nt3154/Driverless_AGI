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
E  — byte-count estimator for a JSON request dict (conservative, no tokenizer download).
F  — shared output-filter estimator from output_filter.estimate_tool_output (//4 rule).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
    """Conservative E: UTF-8 byte count of canonical JSON (ensure_ascii=False).

    This is an explicit estimator, not a mathematically universal tokenizer
    bound. It over-estimates for ASCII-heavy content and under-estimates for
    some dense CJK payloads after tokenization. The margin M absorbs the gap
    for typical provider tokenizers; an unknown tokenizer yields explicit
    unsupported-context failure, never silent truncation.
    """
    return len(json.dumps(request, ensure_ascii=False).encode("utf-8"))


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
# Section allocation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SummaryAllocation:
    """Result of a successful preflight: per-chunk char budgets."""
    section_chars: tuple[int, ...]  # one entry per chunk
    skeleton_chars: int             # chars reserved for refs/header skeleton


def allocate_sections(
    chunks: tuple[Any, ...],
    *,
    available_chars: int,
    minimum_refs: tuple[str, ...],
) -> tuple[int, ...]:
    """Proportional per-chunk char allocation.

    Reserves ``minimum_refs`` from available_chars first, then distributes
    the remainder proportionally by each chunk's estimated_tokens. Unused
    capacity from earlier chunks carries to later ones (deterministic
    remainder goes to the last chunk).

    Parameters
    ----------
    chunks
        Ordered ReaderChunk objects (any object with an ``estimated_tokens``
        int attribute). Empty tuple returns empty tuple.
    available_chars
        Total character budget for prose summaries.
    minimum_refs
        Reference strings that must fit; subtracted from available_chars first.
    """
    if not chunks:
        return ()

    ref_chars = sum(len(r) for r in minimum_refs)
    prose_chars = max(0, available_chars - ref_chars)

    total_est = sum(max(1, getattr(c, "estimated_tokens", 1)) for c in chunks)

    allocs: list[int] = []
    remaining = prose_chars
    for i, chunk in enumerate(chunks):
        if i == len(chunks) - 1:
            allocs.append(max(0, remaining))
        else:
            chunk_est = max(1, getattr(chunk, "estimated_tokens", 1))
            share = math.floor(prose_chars * chunk_est / total_est)
            share = max(0, min(share, remaining))
            allocs.append(share)
            remaining -= share

    return tuple(allocs)


# ---------------------------------------------------------------------------
# Preflight: full-history upper bound before any provider calls
# ---------------------------------------------------------------------------

def _chunk_ref_line(chunk: Any) -> str:
    """One-line reference marker for a chunk in the minimum skeleton."""
    refs = getattr(chunk, "references", ())
    if refs:
        line_start = getattr(refs[0], "line_start", "?")
        line_end   = getattr(refs[-1], "line_start", "?")
        return f"§{chunk.index + 1} lines {line_start}–{line_end}"
    return f"§{chunk.index + 1}"


def _build_skeleton(return_format: Any, chunks: tuple[Any, ...]) -> str:
    """Minimum digest skeleton: signpost + header + one ref line per chunk.

    Used to compute skeleton_chars for preflight and section allocation.
    The signpost comes from return_format.signpost; chunks supply their
    own reference lines. This is a lower-bound estimate of the final digest
    structure.
    """
    parts = [return_format.signpost, ""]
    for chunk in chunks:
        parts.append(_chunk_ref_line(chunk))
    return "\n".join(parts)


def preflight_reader(
    base_request: dict,
    chunks: tuple[Any, ...],
    *,
    limits: ReaderLimits,
    return_format: Any,
) -> SummaryAllocation:
    """Check that the full reader plan fits before making any API calls.

    Raises ReaderCapacityError with a canonical recommendation on any of:
    - skeleton cannot fit in parent output space (P)
    - skeleton cannot fit in reader output space (O)
    - accumulated history upper bound exceeds context window (C)

    On success returns SummaryAllocation with per-chunk char budgets.

    Parameters
    ----------
    base_request
        The base API request dict (system prompt + inherited prefix + tools),
        WITHOUT any source chunks appended yet.
    chunks
        Ordered ReaderChunk objects from chunk_selection.
    limits
        Resolved ReaderLimits from resolve_reader_limits.
    return_format
        ReaderReturnFormat with .signpost (used in skeleton estimate).
    """
    skeleton = _build_skeleton(return_format, chunks)
    skeleton_tokens = len(skeleton) // 4

    if skeleton_tokens >= limits.parent_reserve:
        raise ReaderCapacityError(
            required_tokens=skeleton_tokens + 1,
            available_tokens=limits.parent_reserve,
            recommendation=ReaderCapacityError.NARROW_RANGE,
        )

    if skeleton_tokens >= limits.output_reserve:
        raise ReaderCapacityError(
            required_tokens=skeleton_tokens + 1,
            available_tokens=limits.output_reserve,
            recommendation=ReaderCapacityError.LARGER_MODEL,
        )

    e_base = estimate_reader_request(base_request)
    e_chunks_sum = sum(estimate_reader_text(getattr(c, "text", "")) for c in chunks)
    n = len(chunks)
    O = limits.output_reserve
    M = limits.estimator_margin
    C = limits.context_window
    max_rep = limits.max_repairs

    # Upper bound: base + all source chunks + one summary per chunk + condensation
    # repairs + final handoff + O+M headroom
    total_upper = e_base + e_chunks_sum + (n + max_rep + 2) * O + M
    if total_upper > C:
        raise ReaderCapacityError(
            required_tokens=total_upper,
            available_tokens=C,
            recommendation=ReaderCapacityError.NARROW_RANGE,
        )

    available_chars = limits.parent_reserve * 4 - len(skeleton)
    allocs = allocate_sections(
        chunks,
        available_chars=max(0, available_chars),
        minimum_refs=(),
    )

    return SummaryAllocation(
        section_chars=allocs,
        skeleton_chars=len(skeleton),
    )


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
