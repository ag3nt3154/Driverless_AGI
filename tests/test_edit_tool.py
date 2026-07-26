from pathlib import Path

from tools import _hashline as H
from tools.edit import EditTool


def _make_tool(tmp_path):
    return EditTool(cwd=tmp_path, allowed_roots=[tmp_path])


def _write(tmp_path, name, lines):
    f = tmp_path / name
    f.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return f


def _anchor_for(lines, lineno):
    return f"{lineno}#{H.build_anchors(lines)[lineno - 1]}"


class TestReplace:
    def test_replaces_a_single_line(self, tmp_path):
        lines = ["alpha", "beta", "gamma"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["BETA"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["alpha", "BETA", "gamma"]

    def test_replaces_an_inclusive_range(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{
            "op": "replace",
            "pos": _anchor_for(lines, 2),
            "end": _anchor_for(lines, 3),
            "lines": ["X"],
        }])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "d"]

    def test_replace_with_no_lines_deletes(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": []},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "c"]

    def test_targets_a_repeated_line_unambiguously(self, tmp_path):
        lines = ["}", "}", "}"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["MIDDLE"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["}", "MIDDLE", "}"]


class TestStaleAnchor:
    def test_stale_anchor_reports_error_and_leaves_file_intact(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)
        stale = _anchor_for(lines, 1).replace("1#", "2#")

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": stale, "lines": ["X"]},
        ])

        assert "E_STALE_ANCHOR" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines

    def test_writes_lf_only(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["X"]},
        ])

        assert b"\r\n" not in f.read_bytes()


class TestAppendPrepend:
    def test_append_after_position(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["NEW"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "NEW", "b", "c"]

    def test_append_without_pos_goes_to_eof(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{"op": "append", "lines": ["END"]}])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b", "END"]

    def test_prepend_before_position(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "prepend", "pos": _anchor_for(lines, 3), "lines": ["NEW"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b", "NEW", "c"]

    def test_prepend_without_pos_goes_to_bof(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[{"op": "prepend", "lines": ["TOP"]}])

        assert f.read_text(encoding="utf-8").splitlines() == ["TOP", "a", "b"]


class TestReplaceText:
    def test_replaces_unique_substring(self, tmp_path):
        lines = ["alpha", "beta", "gamma"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "beta", "newText": "BETA"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["alpha", "BETA", "gamma"]

    def test_replaces_across_multiple_lines(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "b\nc", "newText": "X"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "d"]

    def test_missing_text_reports_not_found(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["a", "b"])
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "zzz", "newText": "X"},
        ])

        assert "E_TEXT_NOT_FOUND" in result
        assert f.read_text(encoding="utf-8").splitlines() == ["a", "b"]

    def test_ambiguous_text_reports_ambiguous(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["dup", "dup"])
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "dup", "newText": "X"},
        ])

        assert "E_TEXT_AMBIGUOUS" in result
        assert f.read_text(encoding="utf-8").splitlines() == ["dup", "dup"]

    def test_normalises_crlf_in_supplied_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", ["a", "b", "c"])
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace_text", "oldText": "a\r\nb", "newText": "X"},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["X", "c"]


class TestBatching:
    def test_two_replaces_in_one_call(self, tmp_path):
        lines = ["a", "b", "c", "d"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["A"]},
            {"op": "replace", "pos": _anchor_for(lines, 4), "lines": ["D"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["A", "b", "c", "D"]

    def test_earlier_insert_does_not_shift_later_edit(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["X", "Y"]},
            {"op": "replace", "pos": _anchor_for(lines, 3), "lines": ["C"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "X", "Y", "b", "C"]

    def test_two_inserts_at_same_position_keep_caller_order(self, tmp_path):
        lines = ["a", "b"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", edits=[
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["FIRST"]},
            {"op": "append", "pos": _anchor_for(lines, 1), "lines": ["SECOND"]},
        ])

        assert f.read_text(encoding="utf-8").splitlines() == ["a", "FIRST", "SECOND", "b"]

    def test_overlapping_edits_report_conflict(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {
                "op": "replace",
                "pos": _anchor_for(lines, 1),
                "end": _anchor_for(lines, 2),
                "lines": ["X"],
            },
            {"op": "replace", "pos": _anchor_for(lines, 2), "lines": ["Y"]},
        ])

        assert "E_CONFLICT" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines

    def test_one_bad_anchor_aborts_the_whole_batch(self, tmp_path):
        lines = ["a", "b", "c"]
        f = _write(tmp_path, "f.txt", lines)
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", edits=[
            {"op": "replace", "pos": _anchor_for(lines, 1), "lines": ["A"]},
            {"op": "replace", "pos": "2#zzz", "lines": ["B"]},
        ])

        assert "E_STALE_ANCHOR" in result
        assert f.read_text(encoding="utf-8").splitlines() == lines
