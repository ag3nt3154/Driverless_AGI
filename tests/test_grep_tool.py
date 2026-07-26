from tools import _hashline as H
from tools.grep import GrepTool


def _make_tool(tmp_path):
    return GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestGrepAnchors:
    def test_match_carries_an_anchor(self, tmp_path):
        lines = ["alpha", "needle", "gamma"]
        (tmp_path / "f.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle")

        anchors = H.build_anchors(lines)
        assert f"2#{anchors[1]}:needle" in result

    def test_anchor_matches_the_read_tool_anchor(self, tmp_path):
        from tools.read import ReadTool

        lines = ["}", "}", "needle", "}"]
        (tmp_path / "f.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")

        grep_out = _make_tool(tmp_path).run(pattern="needle")
        read_out = ReadTool(cwd=tmp_path, allowed_roots=[tmp_path]).run(path="f.txt")

        grep_anchor = [ln for ln in grep_out.splitlines() if "needle" in ln][0].split(":")[1]
        read_anchor = [ln for ln in read_out.splitlines() if "needle" in ln][0].split(":")[0].strip()
        assert grep_anchor == read_anchor

    def test_no_matches_message_preserved(self, tmp_path):
        (tmp_path / "f.txt").write_text("alpha", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        assert tool.run(pattern="zzzz") == "[no matches]"

    def test_path_with_colon_is_not_mangled(self, tmp_path):
        import sys
        if sys.platform.startswith("win"):
            sub = tmp_path / "ab"
        else:
            sub = tmp_path / "a:b"
        sub.mkdir()
        (sub / "f.txt").write_text("needle", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle")

        assert "needle" in result
        assert "#" in result
