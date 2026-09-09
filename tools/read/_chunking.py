"""tools/read/_chunking.py — Source text chunking for the large-file reader.

Provides Chonkie-backed and pure-Python fallback chunkers. Both backends
produce the same ReaderChunk contract, validated by validate_chunks.

Chonkie 1.7.0 with tokenizer='character' counts characters, so chunk_size is
in characters. We map chunk_tokens → chunk_chars = chunk_tokens * 4 to match
the estimate_reader_text (len // 4) convention throughout the reader.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tools.read._selection import ReadSelection, SourceSpan, references_for_range

if TYPE_CHECKING:
    pass

_HEADING_RE = re.compile(r"^#{1,6} ", re.MULTILINE)
_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|", re.MULTILINE)


# ---------------------------------------------------------------------------
# Output type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReaderChunk:
    """One ordered, non-overlapping slice of a ReadSelection's text.

    Attributes
    ----------
    index           0-indexed position in the ordered chunk sequence.
    start           Start character offset in ReadSelection.text (inclusive).
    end             End character offset (exclusive). text == selection.text[start:end].
    text            The actual source text for this chunk.
    references      SourceSpan objects mapping this chunk back to the original file.
    estimated_tokens Conservative token estimate (len(text) // 4).
    """
    index: int
    start: int
    end: int
    text: str
    references: tuple[SourceSpan, ...]
    estimated_tokens: int


# ---------------------------------------------------------------------------
# Structural span detection
# ---------------------------------------------------------------------------

def structural_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Find coarse structural boundaries in Markdown text.

    Returns a tuple of (start, end) half-open character pairs covering the
    entire text with no gaps or overlaps. Each span is a structural unit:
    a heading section, fenced code block, contiguous table, or blank-delimited
    paragraph. Does NOT claim to be a complete AST parser.

    Plain text with no Markdown structure returns a single span (0, len(text)).
    """
    if not text:
        return ((0, 0),)

    boundaries: set[int] = {0, len(text)}

    # Blank paragraph breaks
    for m in re.finditer(r"\n{2,}", text):
        boundaries.add(m.end())

    # Markdown headings start a new span
    for m in _HEADING_RE.finditer(text):
        boundaries.add(m.start())

    # Fenced code blocks: keep entire block together by marking start/end as boundaries
    in_fence = False
    for m in _CODE_FENCE_RE.finditer(text):
        if not in_fence:
            boundaries.add(m.start())
            in_fence = True
        else:
            end = text.find("\n", m.end())
            boundaries.add(end + 1 if end >= 0 else len(text))
            in_fence = False

    sorted_bounds = sorted(boundaries)
    spans: list[tuple[int, int]] = []
    for i in range(len(sorted_bounds) - 1):
        s, e = sorted_bounds[i], sorted_bounds[i + 1]
        if s < e:
            spans.append((s, e))

    return tuple(spans) if spans else ((0, len(text)),)


# ---------------------------------------------------------------------------
# Chonkie-backed chunker
# ---------------------------------------------------------------------------

def build_recursive_chunker(chunk_tokens: int):  # -> RecursiveChunker
    """Build a RecursiveChunker using character counting (chunk_size=chunk_tokens*4).

    Uses explicit rules (no online recipe download) and min_characters_per_chunk=1
    so a single-character span is never rejected. The 'character' tokenizer means
    token_count is the character count; estimated_tokens = token_count // 4 matches
    estimate_reader_text.

    Raises ImportError if chonkie is not installed.
    """
    from chonkie import RecursiveChunker, RecursiveLevel, RecursiveRules

    rules = RecursiveRules(levels=[
        RecursiveLevel(delimiters=["\n\n"],      include_delim="prev"),
        RecursiveLevel(delimiters=["\n"],        include_delim="prev"),
        RecursiveLevel(delimiters=[". ", "! ", "? "], include_delim="prev"),
        RecursiveLevel(whitespace=True,          include_delim="prev"),
        RecursiveLevel(whitespace=False,         include_delim="prev"),
    ])

    return RecursiveChunker(
        tokenizer="character",
        chunk_size=chunk_tokens * 4,   # chars = tokens * 4 (matches //4 estimator)
        rules=rules,
        min_characters_per_chunk=1,
    )


def _chonkie_chunks(text: str, chunk_tokens: int) -> list[tuple[int, int, str]]:
    """Run Chonkie and return list of (start, end, text) triples.

    Validates text[start:end] == chunk.text for every chunk and that chunks
    form a complete, non-overlapping cover of [0, len(text)]. Raises
    ValueError on any mismatch.
    """
    chunker = build_recursive_chunker(chunk_tokens)
    raw = chunker.chunk(text)

    if not raw:
        return [(0, len(text), text)] if text else []

    result: list[tuple[int, int, str]] = []
    prev_end = 0

    for chunk in raw:
        start: int = chunk.start_index
        end: int = chunk.end_index
        chunk_text: str = chunk.text

        # Validate offset integrity
        if text[start:end] != chunk_text:
            raise ValueError(
                f"Chonkie offset mismatch at [{start}:{end}]: "
                f"expected {chunk_text[:50]!r} got {text[start:end][:50]!r}"
            )
        if start < prev_end:
            raise ValueError(
                f"Chonkie overlap: chunk starts at {start} before prev end {prev_end}"
            )

        # Fill any gap Chonkie left (should not happen, but defensive)
        if start > prev_end:
            gap = text[prev_end:start]
            result.append((prev_end, start, gap))

        result.append((start, end, chunk_text))
        prev_end = end

    # Fill any trailing gap
    if prev_end < len(text):
        result.append((prev_end, len(text), text[prev_end:]))

    return result


# ---------------------------------------------------------------------------
# Public chunking entrypoints
# ---------------------------------------------------------------------------

def chunk_selection(
    selection: ReadSelection,
    *,
    chunk_tokens: int,
) -> tuple[ReaderChunk, ...]:
    """Split selection.text into ordered ReaderChunks using Chonkie.

    Falls back to stdlib_chunk_selection on ImportError with a logged warning.
    Calls validate_chunks before returning.

    Parameters
    ----------
    selection     Immutable ReadSelection from _selection.py.
    chunk_tokens  Target token budget per chunk (estimate_reader_text units).
    """
    try:
        raw_chunks = _chonkie_chunks(selection.text, chunk_tokens)
    except ImportError:
        import warnings
        warnings.warn(
            "chonkie not installed; falling back to stdlib chunker. "
            "Install with: pip install 'chonkie==1.7.0'",
            ImportWarning,
            stacklevel=2,
        )
        return stdlib_chunk_selection(selection, chunk_chars=chunk_tokens * 4)

    return _build_reader_chunks(selection, raw_chunks)


def stdlib_chunk_selection(
    selection: ReadSelection,
    *,
    chunk_chars: int,
) -> tuple[ReaderChunk, ...]:
    """Pure-Python fallback chunker. No external dependencies.

    Recursively splits on paragraph breaks → newlines → sentence boundaries
    → whitespace → fixed codepoint slices. Uses character counting only.
    Calls validate_chunks before returning.
    """
    if not selection.text:
        return ()

    raw_chunks = _stdlib_split(selection.text, chunk_chars)
    return _build_reader_chunks(selection, raw_chunks)


# ---------------------------------------------------------------------------
# Stdlib recursive split
# ---------------------------------------------------------------------------

_SPLIT_DELIMITERS = ["\n\n", "\n", ". ", "! ", "? "]


def _stdlib_split(text: str, max_chars: int) -> list[tuple[int, int, str]]:
    """Recursively split text into (start, end, text) triples <= max_chars."""
    if max_chars <= 0:
        raise ValueError(f"chunk_chars must be positive, got {max_chars}")

    result: list[tuple[int, int, str]] = []
    _split_recursive(text, 0, max_chars, result)
    return result


def _split_recursive(
    text: str,
    base_offset: int,
    max_chars: int,
    result: list[tuple[int, int, str]],
) -> None:
    """Recursively split text, appending (global_start, global_end, text) to result."""
    if not text:
        return

    if len(text) <= max_chars:
        result.append((base_offset, base_offset + len(text), text))
        return

    # Try each delimiter in order
    for delim in _SPLIT_DELIMITERS:
        parts = _split_keeping_delim(text, delim)
        if len(parts) > 1:
            offset = base_offset
            for part in _merge_small(parts, max_chars):
                _split_recursive(part, offset, max_chars, result)
                offset += len(part)
            return

    # Fallback: split on whitespace
    idx = text.rfind(" ", 0, max_chars)
    if idx > 0:
        _split_recursive(text[:idx + 1], base_offset, max_chars, result)
        _split_recursive(text[idx + 1:], base_offset + idx + 1, max_chars, result)
        return

    # Last resort: fixed codepoint slices (handles CJK, emoji, etc.)
    _fixed_codepoint_split(text, base_offset, max_chars, result)


def _split_keeping_delim(text: str, delim: str) -> list[str]:
    """Split text on delim, keeping the delimiter at the end of each part."""
    parts: list[str] = []
    start = 0
    while True:
        idx = text.find(delim, start)
        if idx == -1:
            rest = text[start:]
            if rest:
                parts.append(rest)
            break
        parts.append(text[start : idx + len(delim)])
        start = idx + len(delim)
    return parts


def _merge_small(parts: list[str], max_chars: int) -> list[str]:
    """Greedily merge consecutive parts that together fit in max_chars."""
    merged: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) <= max_chars:
            current += part
        else:
            if current:
                merged.append(current)
            current = part
    if current:
        merged.append(current)
    return merged


def _fixed_codepoint_split(
    text: str,
    base_offset: int,
    max_chars: int,
    result: list[tuple[int, int, str]],
) -> None:
    """Split by codepoint when no delimiter works. Fails if max_chars < 1."""
    if max_chars < 1:
        raise ValueError(
            f"Cannot split: max_chars={max_chars} cannot fit a single code point."
        )
    start = 0
    while start < len(text):
        slice_text = text[start : start + max_chars]
        if not slice_text:
            break
        result.append((base_offset + start, base_offset + start + len(slice_text), slice_text))
        start += len(slice_text)


# ---------------------------------------------------------------------------
# Shared chunk builder and validator
# ---------------------------------------------------------------------------

def _build_reader_chunks(
    selection: ReadSelection,
    raw_chunks: list[tuple[int, int, str]],
) -> tuple[ReaderChunk, ...]:
    """Convert (start, end, text) triples into validated ReaderChunk objects."""
    chunks: list[ReaderChunk] = []
    for idx, (start, end, text) in enumerate(raw_chunks):
        refs = references_for_range(selection, start, end)
        chunks.append(ReaderChunk(
            index=idx,
            start=start,
            end=end,
            text=text,
            references=refs,
            estimated_tokens=len(text) // 4,
        ))

    result = tuple(chunks)
    validate_chunks(selection, result)
    return result


def validate_chunks(
    selection: ReadSelection,
    chunks: tuple[ReaderChunk, ...],
) -> None:
    """Assert that chunks form a complete, ordered, non-overlapping cover.

    Raises ValueError on any structural violation. Does NOT perform semantic
    validation of summaries or coverage ledger entries.
    """
    if not chunks:
        if selection.text:
            raise ValueError("Empty chunk sequence but selection.text is non-empty.")
        return

    if chunks[0].start != 0:
        raise ValueError(f"First chunk must start at 0, got {chunks[0].start}.")

    if chunks[-1].end != len(selection.text):
        raise ValueError(
            f"Last chunk ends at {chunks[-1].end} but text length is {len(selection.text)}."
        )

    prev_end = 0
    for chunk in chunks:
        if chunk.start != prev_end:
            raise ValueError(
                f"Gap/overlap at chunk {chunk.index}: expected start {prev_end}, got {chunk.start}."
            )
        if chunk.text != selection.text[chunk.start : chunk.end]:
            raise ValueError(
                f"Chunk {chunk.index} text does not match selection.text[{chunk.start}:{chunk.end}]."
            )
        if chunk.index < 0:
            raise ValueError(f"Chunk index must be >= 0, got {chunk.index}.")
        prev_end = chunk.end

    expected_concat = "".join(c.text for c in chunks)
    if expected_concat != selection.text:
        raise ValueError("Concatenated chunks do not equal selection.text.")
