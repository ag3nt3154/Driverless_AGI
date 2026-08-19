import subprocess as sp
from unittest.mock import patch

import pytest

from tools._path_guard import PathNotAllowedError
from tools.grep import GrepTool
from tools.grep._grep import _MAX_RESULTS


def _make_tool(tmp_path):
    return GrepTool(cwd=tmp_path, allowed_roots=[tmp_path])


class TestGrepBasic:
    def test_match_returns_file_line_content(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "alpha\nneedle\ngamma", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="needle", path=str(tmp_path))

        assert "f.txt:2:" in result
        assert "needle" in result

    def test_no_matches_message(self, tmp_path):
        (tmp_path / "f.txt").write_text("alpha", encoding="utf-8", newline="\n")
        tool = _make_tool(tmp_path)

        assert tool.run(pattern="zzzz", path=str(tmp_path)) == "[no matches]"

    def test_literal_mode(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "a.b\naXb", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="a.b", path=str(tmp_path), literal=True)

        assert "a.b" in result


class TestCaseSensitivity:
    def test_pattern_is_case_sensitive(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "Apple\napple\nAPPLE", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="apple", path=str(tmp_path))

        lines = [l for l in result.splitlines() if ":" in l]
        assert len(lines) == 1
        assert "f.txt:2:" in result


class TestHiddenFiles:
    def test_dagi_dir_is_searchable(self, tmp_path):
        dagi = tmp_path / ".dagi"
        dagi.mkdir()
        (dagi / "config.yaml").write_text(
            "model: gpt-4", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="model", path=str(tmp_path))

        assert ".dagi" in result
        assert "model" in result

    def test_git_dir_is_excluded(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "config").write_text(
            "repositoryformatversion = 0",
            encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(
            pattern="repositoryformatversion", path=str(tmp_path),
        )

        assert result == "[no matches]"

    def test_other_hidden_dirs_excluded_in_fallback(self, tmp_path):
        hidden = tmp_path / ".secretdir"
        hidden.mkdir()
        (hidden / "data.txt").write_text(
            "sensitive", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="sensitive", path=str(tmp_path))

        assert result == "[no matches]"


class TestGlobFiltering:
    def test_glob_limits_to_matching_files(self, tmp_path):
        (tmp_path / "code.py").write_text(
            "needle", encoding="utf-8", newline="\n",
        )
        (tmp_path / "notes.txt").write_text(
            "needle", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(
            pattern="needle", path=str(tmp_path), glob="*.py",
        )

        assert "code.py" in result
        assert "notes.txt" not in result


class TestPathValidation:
    def test_path_outside_allowed_roots_rejected(self, tmp_path):
        tool = _make_tool(tmp_path)

        with pytest.raises(PathNotAllowedError):
            tool.run(pattern="x", path="C:\\Windows\\System32")


class TestTruncation:
    def test_results_truncated_at_max(self, tmp_path):
        lines = [f"match {i}" for i in range(_MAX_RESULTS + 50)]
        (tmp_path / "big.txt").write_text(
            "\n".join(lines), encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="match", path=str(tmp_path))

        assert "[truncated" in result
        result_lines = result.splitlines()
        assert len(result_lines) == _MAX_RESULTS + 1


class TestSingleFileSearch:
    def test_search_single_file(self, tmp_path):
        f = tmp_path / "target.txt"
        f.write_text(
            "alpha\nbeta\ngamma", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        result = tool.run(pattern="beta", path=str(f))

        assert "beta" in result


class TestFallbackTransition:
    def test_falls_back_when_rg_not_found(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "data", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="data", path=str(tmp_path))

        assert "data" in result

    def test_falls_back_on_timeout(self, tmp_path):
        (tmp_path / "f.txt").write_text(
            "data", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=sp.TimeoutExpired(cmd="rg", timeout=30),
        ):
            result = tool.run(pattern="data", path=str(tmp_path))

        assert "data" in result
