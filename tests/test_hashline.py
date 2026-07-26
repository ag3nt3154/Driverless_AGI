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
