"""tests/test_scope_tools.py — Unit tests for _tools_from_list() in agent/subagent_tools.py."""
from __future__ import annotations

from pathlib import Path

from agent.subagent_tools import _tools_from_list
from tools.bash import BashTool
from tools.edit import EditTool
from tools.find import FindTool
from tools.grep import GrepTool
from tools.read import ReadTool
from tools.write import WriteTool
from tools.write_handoff import WriteHandoffTool


def _make(names: list[str], handoff_path: Path | None = None):
    return _tools_from_list(names, Path("."), [Path(".")], handoff_path=handoff_path)


class TestToolsFromList:
    def test_read_bash_set(self):
        tools = _make(["read", "grep", "find", "bash"])
        types = {type(t) for t in tools}
        assert types == {ReadTool, GrepTool, FindTool, BashTool}

    def test_read_only_set(self):
        tools = _make(["read", "grep", "find"])
        assert len(tools) == 3
        assert not any(isinstance(t, BashTool) for t in tools)

    def test_read_write_set(self):
        tools = _make(["read", "grep", "find", "write", "edit", "copy"])
        assert len(tools) == 6

    def test_full_set(self):
        tools = _make(["read", "grep", "find", "write", "edit", "bash", "web_search", "web_fetch"])
        assert len(tools) == 8

    def test_unknown_name_skipped(self, capsys):
        tools = _make(["read", "bogus_tool"])
        assert len(tools) == 1
        assert isinstance(tools[0], ReadTool)
        captured = capsys.readouterr()
        assert "bogus_tool" in captured.err

    def test_empty_list(self):
        tools = _make([])
        assert tools == []

    def test_write_tool_included(self):
        tools = _make(["write"])
        assert len(tools) == 1
        assert isinstance(tools[0], WriteTool)

    def test_edit_tool_included(self):
        tools = _make(["edit"])
        assert any(isinstance(t, EditTool) for t in tools)

    def test_write_handoff_auto_injected_when_handoff_path_given(self, tmp_path):
        handoff_path = tmp_path / "handoff.md"
        tools = _make(["read", "grep", "find"], handoff_path=handoff_path)
        write_handoff_tools = [t for t in tools if isinstance(t, WriteHandoffTool)]
        assert len(write_handoff_tools) == 1
        assert write_handoff_tools[0]._handoff_path == handoff_path

    def test_write_handoff_absent_when_no_handoff_path(self):
        tools = _make(["read", "grep", "find"])
        assert not any(isinstance(t, WriteHandoffTool) for t in tools)
