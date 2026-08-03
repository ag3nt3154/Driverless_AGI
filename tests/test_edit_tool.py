from pathlib import Path

from tools.edit import EditTool


def _make_tool(tmp_path):
    return EditTool(cwd=tmp_path, allowed_roots=[tmp_path])


def _write(tmp_path, name, content):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8", newline="\n")
    return f


class TestBasicEdit:
    def test_replaces_unique_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "alpha\nbeta\ngamma")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="beta", newText="BETA")

        assert f.read_text(encoding="utf-8") == "alpha\nBETA\ngamma"
        assert "Edited" in result

    def test_replaces_multiline_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb\nc\nd")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="b\nc", newText="X")

        assert f.read_text(encoding="utf-8") == "a\nX\nd"

    def test_writes_lf_only(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="a", newText="X")

        assert b"\r\n" not in f.read_bytes()


class TestErrorHandling:
    def test_missing_text_reports_not_found(self, tmp_path):
        _write(tmp_path, "f.txt", "a\nb")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="zzz", newText="X")

        assert "not found" in result

    def test_ambiguous_text_reports_count(self, tmp_path):
        f = _write(tmp_path, "f.txt", "dup\ndup")
        tool = _make_tool(tmp_path)

        result = tool.run(path="f.txt", oldText="dup", newText="X")

        assert "2 times" in result
        assert f.read_text(encoding="utf-8") == "dup\ndup"


class TestCRLFNormalization:
    def test_normalises_crlf_in_supplied_text(self, tmp_path):
        f = _write(tmp_path, "f.txt", "a\nb\nc")
        tool = _make_tool(tmp_path)

        tool.run(path="f.txt", oldText="a\r\nb", newText="X")

        assert f.read_text(encoding="utf-8") == "X\nc"
