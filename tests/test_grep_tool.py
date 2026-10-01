import subprocess as sp
from unittest.mock import patch

import pytest

from tools._path_guard import PathNotAllowedError
from tools.grep import GrepTool
from tools.grep import _grep as grep_module
from tools.output_filter import filter_tool_output


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
    def test_dagi_dir_is_excluded(self, tmp_path):
        dagi = tmp_path / ".dagi"
        dagi.mkdir()
        (dagi / "config.yaml").write_text(
            "model: gpt-4", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="model", path=str(tmp_path))

        assert result == "[no matches]"

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


class TestBinaryFileExclusion:
    def test_pyc_files_excluded(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "mod.cpython-312.pyc").write_bytes(b"needle")
        (tmp_path / "mod.py").write_text(
            "needle", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="needle", path=str(tmp_path))

        assert "mod.py" in result
        assert "__pycache__" not in result

    def test_pyo_files_excluded(self, tmp_path):
        (tmp_path / "mod.pyo").write_bytes(b"needle")
        (tmp_path / "mod.py").write_text(
            "needle", encoding="utf-8", newline="\n",
        )
        tool = _make_tool(tmp_path)

        with patch(
            "tools.grep._grep.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = tool.run(pattern="needle", path=str(tmp_path))

        assert "mod.py" in result
        assert "mod.pyo" not in result


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


class TestLargeResults:
    """No display cap in grep itself — the shared output filter truncates."""

    def _write_matches(self, tmp_path, n):
        lines = [f"match {i}" for i in range(n)]
        (tmp_path / "big.txt").write_text(
            "\n".join(lines), encoding="utf-8", newline="\n",
        )

    def test_all_results_returned(self, tmp_path):
        self._write_matches(tmp_path, 1_000)
        with patch("tools.grep._grep.subprocess.run", side_effect=FileNotFoundError):
            result = _make_tool(tmp_path).run(pattern="match", path=str(tmp_path))
        assert len(result.splitlines()) == 1_000
        assert "stopped at" not in result

    def test_shared_filter_keeps_first_and_last_matches(self, tmp_path):
        self._write_matches(tmp_path, 5_000)
        with patch("tools.grep._grep.subprocess.run", side_effect=FileNotFoundError):
            result = _make_tool(tmp_path).run(pattern="match", path=str(tmp_path))
        ctx, _ = filter_tool_output(result, 1_000, tmp_path)
        assert "big.txt:1: match 0" in ctx
        assert "big.txt:5000: match 4999" in ctx
        assert "of 5,000 omitted" in ctx

    def test_safety_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(grep_module, "_SAFETY_LIMIT", 10)
        self._write_matches(tmp_path, 50)
        with patch("tools.grep._grep.subprocess.run", side_effect=FileNotFoundError):
            result = _make_tool(tmp_path).run(pattern="match", path=str(tmp_path))
        lines = result.splitlines()
        assert len(lines) == 11
        assert lines[-1].startswith("[stopped at 10 results")


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
