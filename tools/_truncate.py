"""tools/_truncate.py — Head + marker + tail truncation for oversized text.

Shared by the read tool (marker points at the source file) and the output
filter (marker points at the saved full tool output). Head and tail are cut on
whole lines so the omitted range can be addressed with read(offset/limit).

Public API
----------
DEFAULT_EDGE_CHARS
effective_edge_chars(configured, reserve_tokens) -> int
truncate_middle(lines, *, source, edge_chars, ...) -> str
"""
from __future__ import annotations

DEFAULT_EDGE_CHARS = 4000
_CHARS_PER_TOKEN = 4
_ELLIPSIS = "…"


def effective_edge_chars(configured: int, reserve_tokens: int) -> int:
    """Clamp the per-end budget so head + tail stay at most half of reserve_tokens."""
    if reserve_tokens <= 0:
        return max(1, configured)
    return max(1, min(configured, reserve_tokens * _CHARS_PER_TOKEN // 4))


def _render(line: str, number: int, numbered: bool) -> str:
    return f"{number:6d}\t{line}" if numbered else line


def truncate_middle(
    lines: list[str],
    *,
    source: str | None,
    edge_chars: int = DEFAULT_EDGE_CHARS,
    line_offset: int = 1,
    total_lines: int | None = None,
    numbered: bool = False,
    header: str | None = None,
    hint: str = "",
    unsaved_reason: str = "",
) -> str:
    """Render ``lines`` keeping at most ``edge_chars`` at each end.

    Parameters
    ----------
    lines         The selected lines (no trailing newlines).
    source        Path the agent can use to reach the full text, or None when
                  the full text was not saved (see ``unsaved_reason``).
    edge_chars    Character budget for the head and, separately, the tail.
    line_offset   1-indexed line number of ``lines[0]`` in ``source``.
    total_lines   Line count of the whole source (defaults to len(lines)).
    numbered      Render ``cat -n`` style line numbers.
    header        Optional first line (e.g. a document header).
    hint          Extra guidance appended inside the marker (e.g. PDF pages).
    unsaved_reason Why the full text is unavailable when ``source`` is None.

    Returns the full rendering unchanged when everything fits.
    """
    n = len(lines)
    total = total_lines if total_lines is not None else n
    rendered = [_render(line, line_offset + i, numbered) for i, line in enumerate(lines)]
    prefix = f"{header}\n" if header else ""

    if sum(len(r) + 1 for r in rendered) <= 2 * edge_chars:
        return prefix + "\n".join(rendered)

    if n == 1:
        return prefix + _truncate_single_line(
            lines[0], line_offset, total, source, edge_chars, numbered, hint, unsaved_reason,
        )

    # Head: whole lines; if the first line alone is too long, cut it.
    head: list[str] = []
    used = 0
    h_end = 0
    while h_end < n and used + len(rendered[h_end]) + 1 <= edge_chars:
        head.append(rendered[h_end])
        used += len(rendered[h_end]) + 1
        h_end += 1
    if h_end == 0:
        head = [rendered[0][:edge_chars] + _ELLIPSIS]
        h_end = 1

    # Tail: whole lines that don't overlap the head; cut the last line if needed.
    tail: list[str] = []
    used = 0
    t_start = n
    while t_start - 1 >= h_end and used + len(rendered[t_start - 1]) + 1 <= edge_chars:
        t_start -= 1
        tail.insert(0, rendered[t_start])
        used += len(rendered[t_start]) + 1
    if t_start == n and n - 1 >= h_end:
        tail = [_ELLIPSIS + rendered[n - 1][-edge_chars:]]
        t_start = n - 1

    omitted = lines[h_end:t_start]
    omitted_tokens = sum(len(line) + 1 for line in omitted) // _CHARS_PER_TOKEN
    if omitted:
        first = line_offset + h_end
        last = line_offset + t_start - 1
        what = f"lines {first:,}–{last:,} of {total:,} omitted"
    else:
        # Only partial edge lines were cut.
        omitted_tokens = (
            sum(len(r) + 1 for r in rendered) - sum(len(r) + 1 for r in head + tail)
        ) // _CHARS_PER_TOKEN
        what = f"parts of long lines omitted ({total:,} lines total)"

    marker = _marker(what, omitted_tokens, source, hint, unsaved_reason,
                     offset=line_offset + h_end)
    return prefix + "\n".join(head) + "\n" + marker + "\n" + "\n".join(tail)


def _truncate_single_line(
    line: str,
    line_number: int,
    total: int,
    source: str | None,
    edge_chars: int,
    numbered: bool,
    hint: str,
    unsaved_reason: str,
) -> str:
    rendered = _render(line, line_number, numbered)
    omitted_chars = len(rendered) - 2 * edge_chars
    what = (
        f"{omitted_chars:,} characters of line {line_number:,} omitted "
        f"({total:,} lines total)"
    )
    marker = _marker(what, omitted_chars // _CHARS_PER_TOKEN, source, hint,
                     unsaved_reason, offset=line_number)
    return (
        rendered[:edge_chars] + _ELLIPSIS + "\n" + marker + "\n"
        + _ELLIPSIS + rendered[-edge_chars:]
    )


def _marker(
    what: str,
    omitted_tokens: int,
    source: str | None,
    hint: str,
    unsaved_reason: str,
    *,
    offset: int,
) -> str:
    if source is None:
        reason = f" ({unsaved_reason})" if unsaved_reason else ""
        body = f"[{_ELLIPSIS} {what} (~{omitted_tokens:,} tokens). Full text was NOT saved{reason}."
        if hint:
            body += f"\n {hint}"
        return body + "]"
    body = (
        f"[{_ELLIPSIS} {what} (~{omitted_tokens:,} tokens). Full text: {source}\n"
        f" Use read(path, offset={offset}, limit=…) for a range, grep to locate content, "
        f"or read_large_file(path, query=…) for an indexed digest."
    )
    if hint:
        body += f"\n {hint}"
    return body + "]"
