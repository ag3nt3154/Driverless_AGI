"""tests/test_find_tool.py — FindTool results and the shared truncation filter."""
from __future__ import annotations

from tools.find import FindTool
from tools.find import _find as find_module
from tools.output_filter import filter_tool_output


def _make_tool(tmp_path):
    return FindTool(cwd=tmp_path, allowed_roots=[tmp_path])


def _make_files(tmp_path, n):
    d = tmp_path / "src"
    d.mkdir()
    for i in range(n):
        (d / f"f{i:05d}.py").write_text("", encoding="utf-8")


class TestFind:
    def test_relative_sorted_paths(self, tmp_path):
        _make_files(tmp_path, 3)
        result = _make_tool(tmp_path).run(pattern="**/*.py", path=str(tmp_path))
        assert result.splitlines() == [
            str(tmp_path.joinpath("src", f"f{i:05d}.py").relative_to(tmp_path))
            for i in range(3)
        ]

    def test_no_matches(self, tmp_path):
        assert _make_tool(tmp_path).run(pattern="*.rs", path=str(tmp_path)) == "[no matches]"

    def test_missing_dir(self, tmp_path):
        result = _make_tool(tmp_path).run(pattern="*", path=str(tmp_path / "nope"))
        assert result == "[no matches]"


class TestLargeResults:
    """No display cap in find itself — the shared output filter truncates."""

    def test_all_results_returned(self, tmp_path):
        _make_files(tmp_path, 1_200)
        result = _make_tool(tmp_path).run(pattern="**/*.py", path=str(tmp_path))
        assert len(result.splitlines()) == 1_200

    def test_shared_filter_keeps_first_and_last_paths(self, tmp_path):
        _make_files(tmp_path, 3_000)
        result = _make_tool(tmp_path).run(pattern="**/*.py", path=str(tmp_path))
        ctx, _ = filter_tool_output(result, 1_000, tmp_path)
        assert "f00000.py" in ctx
        assert "f02999.py" in ctx
        assert "of 3,000 omitted" in ctx

    def test_safety_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(find_module, "_SAFETY_LIMIT", 10)
        _make_files(tmp_path, 25)
        lines = _make_tool(tmp_path).run(pattern="**/*.py", path=str(tmp_path)).splitlines()
        assert len(lines) == 11
        assert lines[-1].startswith("[stopped at 10 of 25 results")
