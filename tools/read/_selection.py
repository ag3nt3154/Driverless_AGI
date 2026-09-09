"""tools/read/_selection.py — Immutable source-selection snapshot.

Separates source loading and selection from presentation and delegation so the
reader subprocess receives an exact, frozen view of what the parent selected.
Chunking (subtask 3) and reader transport (subtask 5) build on these types.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING


@dataclass(frozen=True)
class ReadOptions:
    """External dependencies for load_selection — no parallel or budget fields."""
    cwd: Path
    allowed_roots: list[Path] | None
    project_path: Path | None
    service_url: str | None


@dataclass(frozen=True)
class SourceSpan:
    """Half-open character offsets mapping a selected region back to source.

    All offsets are in the normalized text (LF-only, after UTF-8 decode or
    converter output). They are NOT raw PDF byte offsets or DOCX coordinates.

    Attributes
    ----------
    start       Half-open start in ReadSelection.text (0-indexed).
    end         Exclusive end in ReadSelection.text.
    source_start Character offset of this span's first byte in the full
                 normalized source text (before offset/limit slicing).
    line_start  1-indexed line number of the first line of this span in
                 the original file (or converter Markdown).
    page        PDF page number this span came from, or None.
    """
    start: int
    end: int
    source_start: int
    line_start: int
    page: int | None = None


@dataclass(frozen=True)
class ReadSelection:
    """Immutable snapshot of exactly what the parent read and may delegate.

    Attributes
    ----------
    path         Absolute path to the source file.
    text         Selected text, newline-normalised (LF only, no trailing NL).
                 For cat-n rendering, split on ``\\n``.
    spans        Ordered source-coverage spans. For plain text and single-page
                 PDF selections this is a single span. Multi-page disjoint
                 selections produce one span per page group.
    header       Document header line (e.g. "[PDF: report.pdf | 20 pages]")
                 or None for plain text.
    editable_path Converter-cache path for doc files, or None for plain text.
    scope        Human-readable description of the selection
                 (e.g. "lines 1-2000 of 5432").
    """
    path: Path
    text: str
    spans: tuple[SourceSpan, ...]
    header: str | None
    editable_path: Path | None
    scope: str


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_inline(selection: ReadSelection) -> str:
    """Reproduce cat-n style output from an immutable selection snapshot.

    Matches the existing ReadTool output format exactly so parent-fit checks
    operate on the same bytes that would have been returned inline.
    """
    lines = selection.text.split("\n") if selection.text else []
    line_start = selection.spans[0].line_start if selection.spans else 1
    numbered = "\n".join(
        f"{i:6d}\t{line}"
        for i, line in enumerate(lines, line_start)
    )
    if selection.header:
        return f"{selection.header}\n{numbered}"
    return numbered


# ---------------------------------------------------------------------------
# Source selection helpers (used by _read.py and chunking module)
# ---------------------------------------------------------------------------

def _char_offset_before_line(lines: list[str], line_idx: int) -> int:
    """Character offset in ``"\\n".join(lines)`` at which line_idx starts."""
    return sum(len(lines[i]) + 1 for i in range(line_idx))  # +1 for \n


def references_for_range(
    selection: ReadSelection,
    start: int,
    end: int,
) -> tuple[SourceSpan, ...]:
    """Return SourceSpans covering [start, end) in selection.text.

    Each returned span has start/end offsets local to the chunk (0-indexed from
    chunk start), source_start pointing into the full normalized source, and
    line_start derived from counting newlines between the span's origin and the
    overlap boundary.
    """
    result: list[SourceSpan] = []
    for span in selection.spans:
        overlap_start = max(span.start, start)
        overlap_end = min(span.end, end)
        if overlap_start >= overlap_end:
            continue

        span_offset = overlap_start - span.start
        new_source_start = span.source_start + span_offset
        preceding = selection.text[span.start:overlap_start]
        new_line_start = span.line_start + preceding.count("\n")

        result.append(SourceSpan(
            start=overlap_start - start,
            end=overlap_end - start,
            source_start=new_source_start,
            line_start=new_line_start,
            page=span.page,
        ))

    return tuple(result)


def make_selection(
    path: Path,
    lines: list[str],
    *,
    offset: int,
    limit: int,
    header: str | None,
    editable_path: Path | None,
    page: int | None = None,
) -> ReadSelection:
    """Build a ReadSelection from already-split source lines.

    Parameters
    ----------
    path         Absolute source file path.
    lines        All lines of the normalized source (after page filtering).
    offset       1-indexed first line of the selection (same as ReadTool param).
    limit        Maximum number of lines to include.
    header       Document header string or None.
    editable_path Converter cache path or None.
    page         PDF page number if lines are from a single-page selection,
                 else None.
    """
    start_idx = max(0, offset - 1)
    selected = lines[start_idx : start_idx + limit]
    text = "\n".join(selected)

    total = len(lines)
    end_line = start_idx + len(selected)  # exclusive, 0-indexed

    # Character offsets into the full (unselected) text
    full_text = "\n".join(lines)
    source_start = _char_offset_before_line(lines, start_idx)
    source_end = source_start + len(text)

    span = SourceSpan(
        start=0,
        end=len(text),
        source_start=source_start,
        line_start=offset,
        page=page,
    )

    actual_end_line = start_idx + len(selected)
    if len(selected) == total:
        scope = f"all {total} lines of {path.name}"
    else:
        scope = f"lines {offset}–{actual_end_line} of {total} in {path.name}"

    return ReadSelection(
        path=path,
        text=text,
        spans=(span,),
        header=header,
        editable_path=editable_path,
        scope=scope,
    )
