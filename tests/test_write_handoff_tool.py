"""tests/test_write_handoff_tool.py — Unit tests for WriteHandoffTool."""
from __future__ import annotations

from agent.protocol import SideEffect, ToolResult
from tools.write_handoff import WriteHandoffTool


class TestWriteHandoffTool:
    def test_subagent_mode_writes_file(self, tmp_path):
        path = tmp_path / "worker_ab12.md"
        result = WriteHandoffTool(handoff_path=path).run(content="# Report\n\nDone.")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.END_TURN
        assert path.read_text(encoding="utf-8") == "# Report\n\nDone."
        assert "# Report" in result.output

    def test_main_agent_mode_no_file_write(self, tmp_path):
        result = WriteHandoffTool(handoff_path=None).run(content="Summary for user")
        assert isinstance(result, ToolResult)
        assert result.side_effect is SideEffect.END_TURN
        assert result.output == "Summary for user"

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "deep" / "h.md"
        WriteHandoffTool(handoff_path=path).run(content="x")
        assert path.exists()

    def test_schema_has_only_content_param(self, tmp_path):
        schema = WriteHandoffTool(handoff_path=tmp_path / "h.md").schema()
        props = schema["function"]["parameters"]["properties"]
        assert set(props) == {"content"}

    def test_overwrite_replaces(self, tmp_path):
        path = tmp_path / "h.md"
        tool = WriteHandoffTool(handoff_path=path)
        tool.run(content="first")
        tool.run(content="second")
        assert path.read_text(encoding="utf-8") == "second"

    def test_name_is_write_handoff(self, tmp_path):
        tool = WriteHandoffTool(handoff_path=tmp_path / "h.md")
        assert tool.name == "write_handoff"

    def test_no_sentinel_in_output(self, tmp_path):
        path = tmp_path / "h.md"
        result = WriteHandoffTool(handoff_path=path).run(content="test")
        assert "<<HANDOFF_WRITTEN>>" not in result.output
        assert "<<END_OF_RESPONSE>>" not in result.output
