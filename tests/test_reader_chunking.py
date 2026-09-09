"""tests/test_reader_chunking.py — Tests for tools/read/_chunking.py.

Covers:
- references_for_range (in _selection.py, imported here for proximity)
- validate_chunks invariants
- structural_spans Markdown boundary detection
- stdlib_chunk_selection: coverage, ordering, no-gap, no-overlap
- chunk_selection: Chonkie backend (skipped if not installed)
"""
from __future__ import annotations

import pytest
from pathlib import Path

from tools.read._selection import (
    ReadSelection,
    SourceSpan,
    make_selection,
    references_for_range,
)
from tools.read._chunking import (
    ReaderChunk,
    chunk_selection,
    stdlib_chunk_selection,
    structural_spans,
    validate_chunks,
    _stdlib_split,
    _split_keeping_delim,
    _merge_small,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_selection(text: str, line_start: int = 1, page: int | None = None) -> ReadSelection:
    """Build a minimal ReadSelection from raw text."""
    span = SourceSpan(
        start=0,
        end=len(text),
        source_start=0,
        line_start=line_start,
        page=page,
    )
    return ReadSelection(
        path=Path("/fake/file.txt"),
        text=text,
        spans=(span,),
        header=None,
        editable_path=None,
        scope="all 1 lines of file.txt",
    )


def _make_multi_span_selection(parts: list[tuple[str, int]]) -> ReadSelection:
    """Build a ReadSelection from (text, line_start) pairs, concatenated with newlines."""
    spans: list[SourceSpan] = []
    offset = 0
    full_parts: list[str] = []
    for text_part, line_start in parts:
        spans.append(SourceSpan(
            start=offset,
            end=offset + len(text_part),
            source_start=offset,
            line_start=line_start,
            page=None,
        ))
        full_parts.append(text_part)
        offset += len(text_part)
    full_text = "".join(full_parts)
    return ReadSelection(
        path=Path("/fake/multi.txt"),
        text=full_text,
        spans=tuple(spans),
        header=None,
        editable_path=None,
        scope="multi-span selection",
    )


# ---------------------------------------------------------------------------
# references_for_range
# ---------------------------------------------------------------------------

class TestReferencesForRange:
    def test_single_span_full_range(self):
        sel = _make_selection("hello world")
        refs = references_for_range(sel, 0, 11)
        assert len(refs) == 1
        assert refs[0].start == 0
        assert refs[0].end == 11
        assert refs[0].source_start == 0
        assert refs[0].line_start == 1

    def test_single_span_sub_range(self):
        sel = _make_selection("hello world")
        refs = references_for_range(sel, 6, 11)
        assert len(refs) == 1
        assert refs[0].start == 0
        assert refs[0].end == 5
        assert refs[0].source_start == 6

    def test_single_span_line_tracking(self):
        # "line1\nline2\nline3"
        text = "line1\nline2\nline3"
        sel = _make_selection(text, line_start=10)
        # Range covering "line2\nline3" starts at offset 6
        refs = references_for_range(sel, 6, len(text))
        assert len(refs) == 1
        assert refs[0].line_start == 11  # line1\n pushes us to line 11

    def test_no_overlap_returns_empty(self):
        text = "abcdef"
        span_a = SourceSpan(start=0, end=3, source_start=0, line_start=1)
        span_b = SourceSpan(start=3, end=6, source_start=3, line_start=2)
        sel = ReadSelection(
            path=Path("/f.txt"), text=text,
            spans=(span_a, span_b), header=None, editable_path=None,
            scope="test",
        )
        # Ask for range entirely within span_b
        refs = references_for_range(sel, 3, 6)
        # Only span_b should appear
        assert len(refs) == 1
        assert refs[0].start == 0
        assert refs[0].end == 3
        assert refs[0].source_start == 3

    def test_multi_span_straddle(self):
        # Two spans, chunk straddles them
        text = "AAABBB"
        span_a = SourceSpan(start=0, end=3, source_start=100, line_start=5)
        span_b = SourceSpan(start=3, end=6, source_start=200, line_start=8)
        sel = ReadSelection(
            path=Path("/f.txt"), text=text,
            spans=(span_a, span_b), header=None, editable_path=None,
            scope="test",
        )
        refs = references_for_range(sel, 1, 5)
        assert len(refs) == 2
        # span_a contributes [1,3) locally → [0,2) in chunk
        assert refs[0].start == 0
        assert refs[0].end == 2
        assert refs[0].source_start == 101  # 100 + 1
        # span_b contributes [3,5) locally → [2,4) in chunk
        assert refs[1].start == 2
        assert refs[1].end == 4
        assert refs[1].source_start == 200

    def test_page_preserved(self):
        text = "page content"
        sel = _make_selection(text, page=3)
        refs = references_for_range(sel, 0, 4)
        assert refs[0].page == 3

    def test_empty_range_returns_empty(self):
        sel = _make_selection("hello")
        refs = references_for_range(sel, 2, 2)
        assert refs == ()


# ---------------------------------------------------------------------------
# validate_chunks
# ---------------------------------------------------------------------------

class TestValidateChunks:
    def _make_chunk(self, idx: int, start: int, end: int, text: str) -> ReaderChunk:
        return ReaderChunk(
            index=idx, start=start, end=end, text=text,
            references=(), estimated_tokens=len(text) // 4,
        )

    def test_valid_single_chunk(self):
        sel = _make_selection("hello")
        chunk = self._make_chunk(0, 0, 5, "hello")
        validate_chunks(sel, (chunk,))  # Should not raise

    def test_empty_chunks_empty_text(self):
        sel = _make_selection("")
        validate_chunks(sel, ())  # Should not raise

    def test_empty_chunks_nonempty_text_raises(self):
        sel = _make_selection("hello")
        with pytest.raises(ValueError, match="non-empty"):
            validate_chunks(sel, ())

    def test_first_chunk_not_at_zero_raises(self):
        sel = _make_selection("hello")
        chunk = self._make_chunk(0, 1, 5, "ello")
        with pytest.raises(ValueError, match="start at 0"):
            validate_chunks(sel, (chunk,))

    def test_last_chunk_not_at_end_raises(self):
        sel = _make_selection("hello")
        chunk = self._make_chunk(0, 0, 4, "hell")
        with pytest.raises(ValueError, match="ends at"):
            validate_chunks(sel, (chunk,))

    def test_gap_between_chunks_raises(self):
        sel = _make_selection("helloworld")
        c1 = self._make_chunk(0, 0, 4, "hell")
        c2 = self._make_chunk(1, 5, 10, "world")  # gap at position 4
        with pytest.raises(ValueError, match="Gap/overlap"):
            validate_chunks(sel, (c1, c2))

    def test_chunk_text_mismatch_raises(self):
        sel = _make_selection("hello")
        chunk = self._make_chunk(0, 0, 5, "XXXXX")
        with pytest.raises(ValueError, match="does not match"):
            validate_chunks(sel, (chunk,))

    def test_concat_mismatch_raises(self):
        sel = _make_selection("hello")
        # Individually each passes local checks but concat differs
        c1 = self._make_chunk(0, 0, 2, "he")
        c2 = self._make_chunk(1, 2, 5, "lXo")  # wrong text
        with pytest.raises(ValueError):
            validate_chunks(sel, (c1, c2))

    def test_two_valid_chunks(self):
        sel = _make_selection("hello world")
        c1 = self._make_chunk(0, 0, 6, "hello ")
        c2 = self._make_chunk(1, 6, 11, "world")
        validate_chunks(sel, (c1, c2))  # Should not raise


# ---------------------------------------------------------------------------
# structural_spans
# ---------------------------------------------------------------------------

class TestStructuralSpans:
    def test_plain_text_single_span(self):
        text = "no structure here"
        spans = structural_spans(text)
        assert len(spans) == 1
        assert spans[0] == (0, len(text))

    def test_empty_text(self):
        spans = structural_spans("")
        assert spans == ((0, 0),)

    def test_paragraph_break_creates_boundary(self):
        text = "para one\n\npara two"
        spans = structural_spans(text)
        # Should have at least 2 spans
        assert len(spans) >= 2
        # Full coverage
        assert spans[0][0] == 0
        assert spans[-1][1] == len(text)

    def test_heading_creates_boundary(self):
        text = "intro\n## Section\ncontent"
        spans = structural_spans(text)
        assert len(spans) >= 2
        assert spans[0][0] == 0
        assert spans[-1][1] == len(text)

    def test_fenced_code_block(self):
        text = "before\n```\ncode\n```\nafter"
        spans = structural_spans(text)
        assert len(spans) >= 1
        # Full coverage with no gaps
        for i in range(len(spans) - 1):
            assert spans[i][1] == spans[i + 1][0]

    def test_no_gaps_or_overlaps(self):
        text = "# H1\n\nparagraph\n\n## H2\n\n```\ncode\n```\n\nend"
        spans = structural_spans(text)
        assert spans[0][0] == 0
        assert spans[-1][1] == len(text)
        for i in range(len(spans) - 1):
            assert spans[i][1] == spans[i + 1][0], f"Gap between spans {i} and {i+1}"

    def test_table_row_included(self):
        text = "| col1 | col2 |\n|------|------|\n| a    | b    |"
        spans = structural_spans(text)
        assert spans[0][0] == 0
        assert spans[-1][1] == len(text)


# ---------------------------------------------------------------------------
# _stdlib_split helpers
# ---------------------------------------------------------------------------

class TestStdlibHelpers:
    def test_split_keeping_delim_basic(self):
        parts = _split_keeping_delim("a\n\nb\n\nc", "\n\n")
        assert parts == ["a\n\n", "b\n\n", "c"]

    def test_split_keeping_delim_no_match(self):
        parts = _split_keeping_delim("abc", "\n\n")
        assert parts == ["abc"]

    def test_merge_small_basic(self):
        parts = ["a", "b", "c"]
        merged = _merge_small(parts, 2)
        assert merged == ["ab", "c"]

    def test_merge_small_all_fit(self):
        parts = ["a", "b"]
        merged = _merge_small(parts, 10)
        assert merged == ["ab"]

    def test_stdlib_split_within_budget(self):
        text = "short text"
        result = _stdlib_split(text, 100)
        assert len(result) == 1
        assert result[0] == (0, len(text), text)

    def test_stdlib_split_paragraph_break(self):
        text = "para one\n\npara two"
        result = _stdlib_split(text, 10)
        assert len(result) >= 2
        # Verify coverage
        reconstructed = "".join(t for _, _, t in result)
        assert reconstructed == text

    def test_stdlib_split_zero_budget_raises(self):
        with pytest.raises(ValueError, match="positive"):
            _stdlib_split("text", 0)


# ---------------------------------------------------------------------------
# stdlib_chunk_selection
# ---------------------------------------------------------------------------

class TestStdlibChunkSelection:
    def test_empty_text_returns_empty(self):
        sel = _make_selection("")
        chunks = stdlib_chunk_selection(sel, chunk_chars=100)
        assert chunks == ()

    def test_small_text_single_chunk(self):
        text = "hello world"
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1000)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].start == 0
        assert chunks[0].end == len(text)
        assert chunks[0].index == 0

    def test_covers_full_text(self):
        text = "alpha\n\nbeta\n\ngamma\n\ndelta"
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=10)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text

    def test_no_gaps_or_overlaps(self):
        text = "The quick brown fox jumps over the lazy dog. " * 5
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=50)
        prev_end = 0
        for chunk in chunks:
            assert chunk.start == prev_end, f"Gap at chunk {chunk.index}"
            prev_end = chunk.end
        assert prev_end == len(text)

    def test_chunks_respect_budget(self):
        text = "word " * 100
        sel = _make_selection(text)
        budget = 50
        chunks = stdlib_chunk_selection(sel, chunk_chars=budget)
        # Most chunks should be <= budget (last may be smaller)
        oversized = [c for c in chunks if len(c.text) > budget]
        # Single indivisible tokens may exceed budget; words here are 5 chars
        # so nothing should exceed budget unless a single token is >= budget
        assert all(len(c.text) <= budget for c in oversized) or len(oversized) == 0

    def test_indices_are_sequential(self):
        text = "line\n" * 50
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=40)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_chunk_text_matches_selection(self):
        text = "The quick brown fox\njumps over\nthe lazy dog."
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=20)
        for chunk in chunks:
            assert chunk.text == sel.text[chunk.start:chunk.end]

    def test_estimated_tokens(self):
        text = "abcd" * 10  # 40 chars → 10 tokens
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1000)
        assert chunks[0].estimated_tokens == 10

    def test_references_non_empty(self):
        text = "hello world"
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1000)
        assert len(chunks[0].references) > 0

    def test_references_source_start(self):
        # Selection starting at line 10
        text = "line ten\nline eleven"
        sel = _make_selection(text, line_start=10)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1000)
        assert chunks[0].references[0].line_start == 10

    def test_multiline_chunk_references(self):
        text = "A\nB\nC\nD\nE"
        sel = _make_selection(text, line_start=5)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1000)
        # Single chunk, refs should cover from line 5
        assert chunks[0].references[0].line_start == 5

    def test_cjk_text(self):
        # CJK characters (3 bytes each in UTF-8, but 1 Python char)
        text = "日本語テスト" * 10
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=10)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text

    def test_very_small_budget(self):
        text = "hello"
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text
        assert len(chunks) == 5  # one char per chunk


# ---------------------------------------------------------------------------
# chunk_selection (Chonkie backend)
# ---------------------------------------------------------------------------

try:
    import chonkie  # noqa: F401
    CHONKIE_AVAILABLE = True
except ImportError:
    CHONKIE_AVAILABLE = False


@pytest.mark.skipif(not CHONKIE_AVAILABLE, reason="chonkie not installed")
class TestChonkieChunkSelection:
    def test_covers_full_text(self):
        text = "The quick brown fox. " * 30
        sel = _make_selection(text)
        chunks = chunk_selection(sel, chunk_tokens=10)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text

    def test_no_gaps_or_overlaps(self):
        text = "sentence one. sentence two. " * 20
        sel = _make_selection(text)
        chunks = chunk_selection(sel, chunk_tokens=15)
        prev_end = 0
        for chunk in chunks:
            assert chunk.start == prev_end
            prev_end = chunk.end
        assert prev_end == len(text)

    def test_chunk_text_matches_selection(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa " * 5
        sel = _make_selection(text)
        chunks = chunk_selection(sel, chunk_tokens=20)
        for chunk in chunks:
            assert chunk.text == sel.text[chunk.start:chunk.end]

    def test_indices_sequential(self):
        text = "word " * 50
        sel = _make_selection(text)
        chunks = chunk_selection(sel, chunk_tokens=10)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_empty_text_returns_empty(self):
        sel = _make_selection("")
        chunks = chunk_selection(sel, chunk_tokens=100)
        assert chunks == ()

    def test_fallback_import_error(self, monkeypatch):
        """chunk_selection falls back to stdlib when chonkie import fails."""
        import tools.read._chunking as mod
        original = mod.build_recursive_chunker

        def raise_import(*a, **kw):
            raise ImportError("simulated missing chonkie")

        monkeypatch.setattr(mod, "build_recursive_chunker", raise_import)

        text = "hello world " * 10
        sel = _make_selection(text)
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            chunks = chunk_selection(sel, chunk_tokens=5)
        assert "chonkie not installed" in str(w[0].message)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text


# ---------------------------------------------------------------------------
# Edge cases shared by both backends
# ---------------------------------------------------------------------------

class TestChunkingEdgeCases:
    def test_single_char_text(self):
        sel = _make_selection("x")
        chunks = stdlib_chunk_selection(sel, chunk_chars=1)
        assert len(chunks) == 1
        assert chunks[0].text == "x"

    def test_only_newlines(self):
        text = "\n\n\n"
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=1)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text

    def test_very_long_word(self):
        # Single word longer than budget — must still produce valid chunks
        text = "a" * 200
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=50)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text

    def test_markdown_headings(self):
        text = "# Title\n\n## Section A\n\nContent here.\n\n## Section B\n\nMore content."
        sel = _make_selection(text)
        chunks = stdlib_chunk_selection(sel, chunk_chars=20)
        reconstructed = "".join(c.text for c in chunks)
        assert reconstructed == text
