from tools.grep import GrepTool


def _make_tool(tmp_path):
    return GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestGrepBasic:
    def test_match_returns_file_line_content(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "alpha\nneedle\ngamma", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle")

        assert "f.txt:2:" in result
        assert "needle" in result

    def test_no_matches_message(self, tmp_path):
        (tmp_path / "f.txt").write_text("alpha", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        assert tool.run(pattern="zzzz") == "[no matches]"

    def test_literal_mode(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "a.b\naXb", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="a.b", literal=True)

        assert "a.b" in result
        # literal mode should not match aXb via regex dot
