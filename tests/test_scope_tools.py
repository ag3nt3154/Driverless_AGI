"""tests/test_scope_tools.py — Unit tests for _scope_tools() presets in agent/tools.py."""
from __future__ import annotations

from pathlib import Path

from agent.tools import _scope_tools
from tools.bash import BashTool
from tools.find import FindTool
from tools.grep import GrepTool
from tools.read import ReadTool


def _make_tools(preset: str):
    return _scope_tools(preset, [], Path("."), [Path(".")])


class TestReadBashPreset:
    def test_returns_exactly_four_tools(self):
        tools = _make_tools("read_bash")
        assert len(tools) == 4, f"Expected 4 tools, got {len(tools)}: {tools}"

    def test_contains_read_tool(self):
        tools = _make_tools("read_bash")
        assert any(isinstance(t, ReadTool) for t in tools)

    def test_contains_grep_tool(self):
        tools = _make_tools("read_bash")
        assert any(isinstance(t, GrepTool) for t in tools)

    def test_contains_find_tool(self):
        tools = _make_tools("read_bash")
        assert any(isinstance(t, FindTool) for t in tools)

    def test_contains_bash_tool(self):
        tools = _make_tools("read_bash")
        assert any(isinstance(t, BashTool) for t in tools)

    def test_tool_types_exactly(self):
        """Exact set of tool types — no write tools, no web tools."""
        tools = _make_tools("read_bash")
        expected_types = {ReadTool, GrepTool, FindTool, BashTool}
        actual_types = {type(t) for t in tools}
        assert actual_types == expected_types


class TestExistingPresetsUnaffected:
    def test_read_only_returns_three_tools(self):
        tools = _make_tools("read_only")
        assert len(tools) == 3

    def test_read_only_no_bash(self):
        tools = _make_tools("read_only")
        assert not any(isinstance(t, BashTool) for t in tools)

    def test_read_write_returns_six_tools(self):
        tools = _make_tools("read_write")
        assert len(tools) == 6

    def test_full_returns_nine_tools(self):
        tools = _make_tools("full")
        assert len(tools) == 9
