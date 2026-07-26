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
