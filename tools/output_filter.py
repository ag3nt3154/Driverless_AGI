"""
tools/output_filter.py — Filter large tool outputs before they enter LLM context.

If a tool result exceeds the token threshold, the full text is saved to the shared
hash cache and the context gets head + marker + tail (tools/_truncate.py) instead.
The marker points at the saved file, so the agent can page through it with
read(offset/limit), grep it, or digest it with read_large_file. Keeping the tail
matters for bash: test summaries and tracebacks come last.

Public API
----------
filter_tool_output(result, reserve_tokens, project_root, edge_chars) -> (context_result, full_str)
"""
from __future__ import annotations

import json
from pathlib import Path

from tools._hash_cache import get_or_compute
from tools._truncate import DEFAULT_EDGE_CHARS, effective_edge_chars, truncate_middle

# Same heuristic used by compact.py — avoids adding a tokeniser dependency.
_CHARS_PER_TOKEN = 4


def _serialise(result: str | list) -> str:
    """Convert a raw dispatch result to a flat string for the JSONL tracker."""
    if isinstance(result, str):
        return result
    return "__list__:" + json.dumps(result)


def _text_of(result: str | list) -> str:
    """The text an oversized result is judged and truncated on.

    For multimodal lists only text parts count — images are passed through and
    budgeted separately.
    """
    if isinstance(result, str):
        return result
    return "\n".join(
        part.get("text", "") for part in result
        if isinstance(part, dict) and part.get("type") == "text"
    )


def estimate_tool_output(result: str | list) -> int:
    """Estimate token count for a raw dispatch result (shared F estimator).

    Uses the same //4 heuristic as filter_tool_output so all callers agree on
    the threshold boundary. Returns 0 for empty results.
    """
    return len(_serialise(result)) // _CHARS_PER_TOKEN


def filter_tool_output(
    result: str | list,
    reserve_tokens: int,
    project_root: Path,
    edge_chars: int = DEFAULT_EDGE_CHARS,
) -> tuple[str | list, str]:
    """
    Filter a tool result before it enters LLM context.

    Parameters
    ----------
    result        : Raw value returned by registry.dispatch() after sentinel handling.
    reserve_tokens: Token budget threshold from AgentConfig (same field used for
                    compaction). Results whose text is >= this many estimated
                    tokens are truncated.
    project_root  : Project root directory. The shared hash cache lives at
                    `<project_root>/.dagi/hash_cache/tool_output/`, created automatically.
    edge_chars    : Characters kept at each end (clamped by reserve_tokens).

    Returns
    -------
    (context_result, full_str)
        context_result — filtered value for _messages and TUI callback.
                         Same type as `result`; for lists, the text parts are
                         replaced by one truncated text part and images kept.
        full_str       — full serialised result for JSONL tracker (never truncated).
    """
    full_str = _serialise(result)

    # Guard: zero/negative reserve means compaction is disabled; skip filtering too.
    if reserve_tokens <= 0:
        return result, full_str

    text = _text_of(result)
    if len(text) // _CHARS_PER_TOKEN < reserve_tokens:
        return result, full_str  # pass-through — small enough to enter context raw

    # ── Result is large: save the raw text, build head + marker + tail ──
    edge = effective_edge_chars(edge_chars, reserve_tokens)
    source: str | None
    unsaved = ""
    try:
        _, saved_path = get_or_compute(
            text.encode("utf-8"), "tool_output", "txt", project_root, lambda: text
        )
        source = str(saved_path)
    except OSError as exc:
        source = None
        unsaved = f"cache write failed: {exc}"

    truncated = truncate_middle(
        text.splitlines(),  # same line splitting as read, so offsets match
        source=source,
        edge_chars=edge,
        unsaved_reason=unsaved,
    )
    context_text = f"[Tool output too large — showing start and end only.]\n{truncated}"

    if isinstance(result, str):
        return context_text, full_str

    filtered: list = []
    text_placed = False
    for part in result:
        if isinstance(part, dict) and part.get("type") == "text":
            if not text_placed:
                filtered.append({"type": "text", "text": context_text})
                text_placed = True
            continue
        filtered.append(part)
    return filtered, full_str
