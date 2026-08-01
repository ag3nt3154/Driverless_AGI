import json
import pytest
from pathlib import Path


def _write_session(tmp_path, filename, started_at, raw_messages=None):
    path = tmp_path / filename
    lines = [{"type": "session_start", "model": "m", "started_at": started_at}]
    if raw_messages is not None:
        lines.append({"type": "session_end", "finished_at": started_at,
                       "raw_messages": raw_messages})
    path.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return path


class TestRestoreSlice:
    """Verify the slicing logic used in _restore_session."""

    def test_turn_index_full_returns_all(self):
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        turn_index = len(raw)  # "resume from latest"
        restored = raw[:turn_index + 1]
        # Safe slice past end returns all elements
        assert restored == raw

    def test_turn_index_0_returns_system_only(self):
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        # turn_index 0 = system message only (edge case — shouldn't happen from UI,
        # but slice is safe)
        turn_index = 0
        restored = raw[:turn_index + 1]
        assert len(restored) == 1
        assert restored[0]["role"] == "system"

    def test_turn_index_1_returns_system_and_first_user(self):
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "first reply"},
            {"role": "user", "content": "second message"},
        ]
        turn_index = 1  # first user message
        restored = raw[:turn_index + 1]
        assert len(restored) == 2
        assert restored[-1]["content"] == "first message"

    def test_skip_system_for_render(self):
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        # _render_restored_session receives restored[1:] (no system)
        render_messages = raw[1:]
        assert len(render_messages) == 1
        assert render_messages[0]["role"] == "user"


class TestLoadRawMessagesIntegration:
    """End-to-end: load a real JSONL file, verify restore slice round-trips."""

    def test_load_and_slice(self, tmp_path):
        from tui.history import load_raw_messages
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task one"},
            {"role": "assistant", "content": "done"},
        ]
        path = _write_session(tmp_path, "session_test.jsonl", "2026-08-01T10:00:00Z",
                               raw_messages=raw)
        loaded = load_raw_messages(path)
        assert loaded == raw
        # Restore from first user turn
        restored = loaded[:2]  # system + first user
        assert restored[1]["content"] == "task one"

    def test_no_raw_messages_returns_none(self, tmp_path):
        from tui.history import load_raw_messages
        path = _write_session(tmp_path, "session_incomplete.jsonl", "2026-08-01T10:00:00Z")
        assert load_raw_messages(path) is None
