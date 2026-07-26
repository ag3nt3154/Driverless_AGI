"""tests/test_write_handoff_tool.py — Unit tests for tools/write_handoff.py."""
from __future__ import annotations

from tools.write_handoff import WriteHandoffTool


class TestWriteHandoffTool:
    def test_writes_content_verbatim(self, tmp_path):
        path = tmp_path / "worker_ab12.md"
        out = WriteHandoffTool(handoff_path=path).run(content="# Anything\n\nfree form")
        assert path.read_text(encoding="utf-8") == "# Anything\n\nfree form"
        assert "<<HANDOFF_WRITTEN>>" in out

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

    def test_schema_requires_content(self, tmp_path):
        tool = WriteHandoffTool(handoff_path=tmp_path / "h.md")
        assert tool._parameters["required"] == ["content"]
