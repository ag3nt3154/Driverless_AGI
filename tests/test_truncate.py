"""tests/test_truncate.py — head + marker + tail truncation (tools/_truncate.py)."""
from __future__ import annotations

from tools._truncate import effective_edge_chars, truncate_middle


def _lines(n: int) -> list[str]:
    return [f"row {i:04d}" for i in range(1, n + 1)]  # 8 chars each


class TestEffectiveEdgeChars:
    def test_configured_value_when_reserve_large(self):
        assert effective_edge_chars(4000, 16_384) == 4000

    def test_clamped_to_reserve(self):
        # head + tail ≤ reserve_tokens / 2 tokens → each end ≤ reserve chars
        assert effective_edge_chars(4000, 100) == 100

    def test_zero_reserve_keeps_configured(self):
        assert effective_edge_chars(4000, 0) == 4000


class TestFits:
    def test_small_input_unchanged(self):
        out = truncate_middle(_lines(3), source="f.txt", edge_chars=100)
        assert out == "row 0001\nrow 0002\nrow 0003"

    def test_small_numbered_with_header(self):
        out = truncate_middle(
            _lines(2), source="f.txt", edge_chars=100, numbered=True, header="[H]",
        )
        assert out == "[H]\n     1\trow 0001\n     2\trow 0002"


class TestWholeLines:
    def test_head_and_tail_are_whole_lines(self):
        out = truncate_middle(_lines(100), source="f.txt", edge_chars=45)
        head, marker, tail = out.split("\n[", 1)[0], None, out.rsplit("]\n", 1)[1]
        # 9 chars per line incl. newline → 5 lines fit in 45
        assert head.split("\n") == [f"row {i:04d}" for i in range(1, 6)]
        assert tail.split("\n") == [f"row {i:04d}" for i in range(96, 101)]

    def test_marker_range_and_offset(self):
        out = truncate_middle(_lines(100), source="data/f.txt", edge_chars=45)
        assert "lines 6–95 of 100 omitted" in out
        assert "Full text: data/f.txt" in out
        assert "offset=6" in out
        assert "read_large_file" in out

    def test_line_offset_and_total(self):
        out = truncate_middle(
            _lines(100), source="f.txt", edge_chars=45, line_offset=501, total_lines=2000,
        )
        assert "lines 506–595 of 2,000 omitted" in out

    def test_numbered_keeps_real_line_numbers(self):
        out = truncate_middle(
            _lines(100), source="f.txt", edge_chars=60, numbered=True, line_offset=11,
        )
        assert out.startswith("    11\trow 0001")
        assert out.endswith("   110\trow 0100")

    def test_header_first(self):
        out = truncate_middle(_lines(100), source="f.txt", edge_chars=45, header="[PDF]")
        assert out.startswith("[PDF]\nrow 0001")

    def test_token_estimate(self):
        out = truncate_middle(_lines(100), source="f.txt", edge_chars=45)
        # 90 omitted lines × 9 chars / 4
        assert "(~202 tokens)" in out

    def test_hint_included(self):
        out = truncate_middle(_lines(100), source="f.pdf", edge_chars=45, hint="Use pages.")
        assert "Use pages." in out


class TestLongLines:
    def test_single_huge_line_keeps_both_ends(self):
        line = "A" * 50 + "B" * 1000 + "C" * 50
        out = truncate_middle([line], source="f.txt", edge_chars=50)
        assert out.startswith("A" * 50 + "…")
        assert out.endswith("…" + "C" * 50)
        assert "1,000 characters of line 1 omitted" in out

    def test_long_first_and_last_lines_cut(self):
        lines = ["H" * 500] + _lines(50) + ["T" * 500]
        out = truncate_middle(lines, source="f.txt", edge_chars=40)
        assert out.startswith("H" * 40 + "…")
        assert out.endswith("…" + "T" * 40)
        assert "lines 2–51 of 52 omitted" in out


class TestUnsaved:
    def test_no_source_says_not_saved(self):
        out = truncate_middle(
            _lines(100), source=None, edge_chars=45, unsaved_reason="disk full",
        )
        assert "NOT saved (disk full)" in out
        assert "Full text:" not in out
