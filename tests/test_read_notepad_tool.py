from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent import notepad_store
from agent._loop_config import AgentCallbacks
from agent.tools import create_tool_registry
from tools.read_notepad import ReadNotepadTool
from tools.read_notepad._read_notepad import MAX_CHARS


def test_schema_has_no_parameters(tmp_path):
    tool = ReadNotepadTool(root=tmp_path)
    assert tool.schema()["function"]["parameters"] == {"type": "object", "properties": {}}


def test_missing_or_blank_note_is_empty(tmp_path):
    tool = ReadNotepadTool(root=tmp_path)
    assert tool.run() == "Notepad is empty."
    notepad_store.write_text("  \n", tmp_path)
    assert tool.run() == "Notepad is empty."


def test_returns_raw_markdown_with_header(tmp_path):
    text = "# Ideas\n\n$$\n\\int_0^1 x\\,dx\n$$\n"
    notepad_store.write_text(text, tmp_path)
    out = ReadNotepadTool(root=tmp_path).run()
    header, body = out.split("\n\n", 1)
    assert header.startswith("Notepad (last edited ")
    assert f"{len(text)} chars)" in header
    assert body == text


def test_truncates_long_notes(tmp_path):
    notepad_store.write_text("x" * (MAX_CHARS + 50), tmp_path)
    out = ReadNotepadTool(root=tmp_path).run()
    assert f"showing {MAX_CHARS} of {MAX_CHARS + 50} chars" in out
    assert out.count("x") == MAX_CHARS


def test_flush_runs_before_read(tmp_path):
    def flush():
        notepad_store.write_text("fresh", tmp_path)
        return True

    out = ReadNotepadTool(on_flush=flush, root=tmp_path).run()
    assert out.endswith("fresh")
    assert "may be missing" not in out


def test_failed_or_raising_flush_marks_note_stale(tmp_path):
    notepad_store.write_text("old", tmp_path)
    assert "unsaved edits may be missing" in ReadNotepadTool(on_flush=lambda: False, root=tmp_path).run()

    def boom():
        raise RuntimeError("gui gone")

    out = ReadNotepadTool(on_flush=boom, root=tmp_path).run()
    assert "unsaved edits may be missing" in out and out.endswith("old")


def _config(tmp_path: Path):
    cfg = MagicMock()
    cfg.tools = None
    cfg.disabled_tools = None
    cfg.bash_backend = "subprocess"
    cfg.sandbox_mode = False
    cfg.advanced_config = None
    cfg.worker_config = None
    cfg.autonomous = False
    cfg.project_path = tmp_path
    return cfg


def test_registered_without_callbacks_or_config(tmp_path):
    names = {n for n, _ in create_tool_registry(cwd=tmp_path).list_tools()}
    assert "read_notepad" in names
    names = {n for n, _ in create_tool_registry(cwd=tmp_path, config=_config(tmp_path)).list_tools()}
    assert "read_notepad" in names


def test_registry_wires_flush_callback(tmp_path):
    flush = MagicMock(return_value=True)
    reg = create_tool_registry(
        cwd=tmp_path, config=_config(tmp_path), callbacks=AgentCallbacks(on_flush_notepad=flush),
    )
    assert reg.get("read_notepad")._on_flush is flush
