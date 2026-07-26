from tools import _hashline as H


class TestLineHash:
    def test_is_deterministic(self):
        assert H.line_hash("a", "b", "c") == H.line_hash("a", "b", "c")

    def test_length_is_three(self):
        assert len(H.line_hash("a", "b", "c")) == 3

    def test_uses_alphabet_only(self):
        h = H.line_hash("x", "y", "z")
        assert all(ch in H._ALPHABET for ch in h)

    def test_neighbours_change_the_hash(self):
        assert H.line_hash("a", "same", "c") != H.line_hash("q", "same", "c")
        assert H.line_hash("a", "same", "c") != H.line_hash("a", "same", "q")

    def test_retry_changes_the_hash(self):
        assert H.line_hash("a", "b", "c", 0) != H.line_hash("a", "b", "c", 1)


class TestBuildAnchors:
    def test_one_anchor_per_line(self):
        assert len(H.build_anchors(["a", "b", "c"])) == 3

    def test_empty_file_gives_no_anchors(self):
        assert H.build_anchors([]) == []

    def test_boundary_lines_use_empty_neighbours(self):
        anchors = H.build_anchors(["only"])
        assert anchors[0] == H.line_hash("", "only", "")

    def test_identical_lines_get_distinct_anchors(self):
        anchors = H.build_anchors(["}", "}", "}", "}"])
        assert len(set(anchors)) == 4

    def test_all_anchors_unique_on_repetitive_file(self):
        anchors = H.build_anchors([""] * 200)
        assert len(set(anchors)) == 200


class TestFormatRegion:
    def test_renders_anchor_prefixed_lines(self):
        lines = ["alpha", "beta", "gamma"]
        anchors = H.build_anchors(lines)
        out = H.format_region(lines, anchors, 1, 3)
        assert out.splitlines() == [
            f"1#{anchors[0]}:alpha",
            f"2#{anchors[1]}:beta",
            f"3#{anchors[2]}:gamma",
        ]

    def test_line_numbers_right_aligned_to_end_width(self):
        lines = [f"L{i}" for i in range(1, 11)]
        anchors = H.build_anchors(lines)
        out = H.format_region(lines, anchors, 9, 10).splitlines()
        assert out[0].startswith(" 9#")
        assert out[1].startswith("10#")

    def test_renders_a_subrange_only(self):
        lines = ["a", "b", "c", "d"]
        anchors = H.build_anchors(lines)
        assert len(H.format_region(lines, anchors, 2, 3).splitlines()) == 2

    def test_preserves_content_containing_colons(self):
        lines = ["key: value"]
        anchors = H.build_anchors(lines)
        assert H.format_region(lines, anchors, 1, 1).endswith(":key: value")


class TestComputeAffectedRange:
    def test_pads_by_context_lines(self):
        assert H.compute_affected_range(5, 5, 20) == (3, 7)

    def test_clamps_to_file_bounds(self):
        assert H.compute_affected_range(1, 1, 3) == (1, 3)

    def test_returns_none_when_span_exceeds_budget(self):
        assert H.compute_affected_range(1, 40, 100) is None

    def test_returns_none_when_bounds_missing(self):
        assert H.compute_affected_range(None, 5, 10) is None
        assert H.compute_affected_range(5, None, 10) is None

    def test_returns_none_on_degenerate_range(self):
        assert H.compute_affected_range(5, 0, 10) is None


import pytest


class TestParseAnchor:
    def test_parses_line_and_hash(self):
        assert H.parse_anchor("18#aB3") == (18, "aB3")

    def test_tolerates_surrounding_whitespace(self):
        assert H.parse_anchor("  7#xY-  ") == (7, "xY-")

    def test_rejects_missing_hash(self):
        with pytest.raises(H.AnchorError) as exc:
            H.parse_anchor("18")
        assert exc.value.code == "E_INVALID_ANCHOR"

    def test_rejects_wrong_hash_length(self):
        with pytest.raises(H.AnchorError) as exc:
            H.parse_anchor("18#aB")
        assert exc.value.code == "E_INVALID_ANCHOR"


class TestResolveAnchor:
    def test_returns_zero_based_index(self):
        anchors = H.build_anchors(["a", "b", "c"])
        assert H.resolve_anchor(f"2#{anchors[1]}", anchors) == 1

    def test_stale_hash_raises_stale_anchor(self):
        anchors = H.build_anchors(["a", "b", "c"])
        with pytest.raises(H.AnchorError) as exc:
            H.resolve_anchor(f"2#{anchors[0]}", anchors)
        assert exc.value.code == "E_STALE_ANCHOR"
        assert "re-read" in exc.value.message

    def test_out_of_range_line_raises_invalid_anchor(self):
        anchors = H.build_anchors(["a"])
        with pytest.raises(H.AnchorError) as exc:
            H.resolve_anchor(f"9#{anchors[0]}", anchors)
        assert exc.value.code == "E_INVALID_ANCHOR"


class TestContainsDisplayPrefix:
    def test_detects_anchor_prefix_in_content(self):
        assert H.contains_display_prefix(["12#aB3:x = 1"]) is not None

    def test_detects_diff_hunk_header(self):
        assert H.contains_display_prefix(["@@ -1,2 +1,3 @@"]) is not None

    def test_allows_yaml_frontmatter_delimiter(self):
        assert H.contains_display_prefix(["---"]) is None

    def test_allows_ordinary_content(self):
        assert H.contains_display_prefix(["def f():", "    return 1"]) is None
