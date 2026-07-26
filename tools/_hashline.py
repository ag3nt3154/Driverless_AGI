"""Hash-anchored line addressing shared by read, edit, and grep.

Single source of truth for the LINE#HASH anchor format. No tool computes a
line hash independently — an anchor from any tool must resolve in any other.
"""
from __future__ import annotations

import hashlib
import re

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

    ``_ctx_next`` tracks the next retry index to try per (prev, curr, nxt)
    triple, so lines sharing an identical context (e.g. runs of the same
    content) jump directly to their retry rather than rescanning all prior
    retries, keeping the algorithm O(n) instead of O(n²).
    """
    seen: set[str] = set()
    out: list[str] = []
    _ctx_next: dict[tuple[str, str, str], int] = {}
    for i, curr in enumerate(lines):
        prev = lines[i - 1] if i > 0 else ""
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        ctx = (prev, curr, nxt)
        retry = _ctx_next.get(ctx, 0)
        h = line_hash(prev, curr, nxt, retry)
        while h in seen:
            retry += 1
            h = line_hash(prev, curr, nxt, retry)
        seen.add(h)
        _ctx_next[ctx] = retry + 1
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


_ANCHOR_RE = re.compile(rf"^(\d+)#([A-Za-z0-9_-]{{{HASH_LEN}}})$")
_ANCHOR_PREFIX_RE = re.compile(rf"^\s*\d+#[A-Za-z0-9_-]{{{HASH_LEN}}}:")
_HUNK_RE = re.compile(r"^@@ .* @@")


class AnchorError(Exception):
    """Raised when an anchor is malformed, out of range, or stale."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def parse_anchor(anchor: str) -> tuple[int, str]:
    match = _ANCHOR_RE.match(anchor.strip())
    if not match:
        raise AnchorError(
            "E_INVALID_ANCHOR",
            f"malformed anchor {anchor!r}; expected LINE#HASH, e.g. 18#aB3",
        )
    return int(match.group(1)), match.group(2)


def resolve_anchor(anchor: str, anchors: list[str]) -> int:
    """Resolve an anchor to a 0-based line index against a fresh anchor table."""
    lineno, want = parse_anchor(anchor)
    if lineno < 1 or lineno > len(anchors):
        raise AnchorError(
            "E_INVALID_ANCHOR",
            f"line {lineno} out of range; file has {len(anchors)} lines",
        )
    got = anchors[lineno - 1]
    if got != want:
        raise AnchorError(
            "E_STALE_ANCHOR",
            f"anchor {anchor} no longer matches; line {lineno} is now "
            f"{lineno}#{got}. re-read the file to get current anchors.",
        )
    return lineno - 1


def contains_display_prefix(lines: list[str]) -> str | None:
    """Return the first line that looks like tool display output, else None.

    Only anchor prefixes and diff hunk headers are treated as suspicious.
    Bare `---` and `+++` are deliberately allowed: they are legitimate content
    in this repo (YAML frontmatter, markdown horizontal rules).
    """
    for line in lines:
        if _ANCHOR_PREFIX_RE.match(line) or _HUNK_RE.match(line):
            return line
    return None
