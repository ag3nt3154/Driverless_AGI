"""
tools/output_filter.py — Filter large tool outputs before they enter LLM context.

If a tool result exceeds the token threshold, the full output is saved to a temp
file and a truncated preview + pointer is placed in context instead. This prevents
context-window overflow caused by unexpectedly large tool outputs (grep on a huge
codebase, bash with verbose output, read on a multi-MB file, etc.).

Public API
----------
filter_tool_output(result, reserve_tokens, temp_dir) -> (context_result, full_str)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Same heuristic used by compact.py — avoids adding a tokeniser dependency.
_CHARS_PER_TOKEN = 4


def _serialise(result: str | list) -> str:
    """Convert a raw dispatch result to a flat string for size estimation."""
    if isinstance(result, str):
        return result
    return "__list__:" + json.dumps(result)


def filter_tool_output(
    result: str | list,
    reserve_tokens: int,
    temp_dir: Path,
) -> tuple[str | list, str]:
    """
    Filter a tool result before it enters LLM context.

    Parameters
    ----------
    result        : Raw value returned by registry.dispatch() after sentinel handling.
    reserve_tokens: Token budget threshold from AgentConfig (same field used for
                    compaction). Results >= this many estimated tokens are filtered.
    temp_dir      : Directory where the full output is saved when filtering fires.
                    Created automatically if it does not exist.

    Returns
    -------
    (context_result, full_str)
        context_result — filtered value for _messages and TUI callback.
                         Same type as `result` when not filtered; always str when filtered.
        full_str       — full serialised result for JSONL tracker (never truncated).
    """
    full_str = _serialise(result)

    # Guard: zero/negative reserve means compaction is disabled; skip filtering too.
    if reserve_tokens <= 0:
        return result, full_str

    estimated_tokens = len(full_str) // _CHARS_PER_TOKEN
    if estimated_tokens < reserve_tokens:
        return result, full_str  # pass-through — small enough to enter context raw

    # ── Result is large: write to temp file, build truncated context message ──
    try:
        temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=temp_dir, prefix="tool_output_", suffix=".txt"
        )
        os.close(fd)
        Path(tmp_path).write_text(full_str, encoding="utf-8")
    except OSError:
        # Fail open: if we can't write the file, return the original result
        # unfiltered. The caller (AgentLoop) will emit a warning separately.
        return result, full_str

    preview_chars = (reserve_tokens // 2) * _CHARS_PER_TOKEN
    preview = full_str[:preview_chars]

    context_result = (
        f"{preview}\n\n"
        f"--- OUTPUT TRUNCATED ---\n"
        f"Full output saved to: {tmp_path}\n"
        f"Tool output is very large (~{estimated_tokens:,} tokens estimated). "
        f"Read it chunk by chunk using the read tool with the offset and limit parameters."
    )
    return context_result, full_str
