"""Hash-anchored line addressing shared by read, edit, and grep.

Single source of truth for the LINE#HASH anchor format. No tool computes a
line hash independently — an anchor from any tool must resolve in any other.
"""
from __future__ import annotations

import hashlib

_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
HASH_LEN = 3


def line_hash(prev: str, curr: str, nxt: str, retry: int = 0) -> str:
    """Hash a line in the context of its immediate neighbours.

    Six bits per character are masked off the digest rather than base-converting,
    so HASH_LEN is a pure knob on how many low bits are retained.
    """
    payload = f"{prev}\0{curr}\0{nxt}"
    if retry:
        payload += f":R{retry}"
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return "".join(_ALPHABET[(value >> (6 * i)) & 63] for i in range(HASH_LEN))


def build_anchors(lines: list[str]) -> list[str]:
    """Return one unique hash per line, index i holding the hash for line i+1.

    Collisions are resolved by incrementing a retry counter until the hash is
    unique within the file, so every line is independently addressable.
    """
    seen: set[str] = set()
    out: list[str] = []
    for i, curr in enumerate(lines):
        prev = lines[i - 1] if i > 0 else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        retry = 0
        h = line_hash(prev, curr, nxt)
        while h in seen:
            retry += 1
            h = line_hash(prev, curr, nxt, retry)
        seen.add(h)
        out.append(h)
    return out


ANCHOR_CONTEXT_LINES = 2
ANCHOR_MAX_OUTPUT_LINES = 12
ANCHOR_TEXT_BUDGET_BYTES = 50 * 1024
ANCHORS_OMITTED_TEXT = "Anchors omitted; use read for subsequent edits."


def format_region(
    lines: list[str],
    anchors: list[str],
    start: int,
    end: int,
) -> str:
    """Render lines start..end (1-indexed, inclusive) as LINE#HASH:content."""
    width = len(str(end))
    return "\n".join(
        f"{i:>{width}}#{anchors[i - 1]}:{lines[i - 1]}"
        for i in range(start, end + 1)
    )


def compute_affected_range(
    first_changed: int | None,
    last_changed: int | None,
    total_lines: int,
) -> tuple[int, int] | None:
    """Context window around a change, or None if unbounded or over budget."""
    if first_changed is None or last_changed is None:
        return None
    start = max(1, first_changed - ANCHOR_CONTEXT_LINES)
    end = min(total_lines, last_changed + ANCHOR_CONTEXT_LINES)
    if end < start or (end - start + 1) > ANCHOR_MAX_OUTPUT_LINES:
        return None
    return start, end
