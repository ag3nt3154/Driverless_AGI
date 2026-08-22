import json
import pytest
from pathlib import Path

from agent.affect import AffectRestore, AffectVector


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

    def test_load_raw_messages_ignores_affect_records(self, tmp_path):
        from tui.history import load_raw_messages

        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task one"},
            {"role": "assistant", "content": "done"},
        ]
        path = tmp_path / "session_test.jsonl"
        lines = [
            {"type": "session_start", "model": "m", "started_at": "2026-08-01T10:00:00Z"},
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -0.2, 0.3],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
            },
            {
                "type": "session_end",
                "finished_at": "2026-08-01T10:00:00Z",
                "raw_messages": raw,
            },
            {
                "type": "affect_adjust",
                "payload": {
                    "prior": [0.1, -0.2, 0.3],
                    "delta": [0.2, 0.1, -0.1],
                    "current": [0.3, -0.1, 0.2],
                    "emote_id": "energized",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        assert load_raw_messages(path) == raw


class TestRestoreAffectIntegration:
    def test_tui_restore_stashes_affect_beside_initial_messages(self, tmp_path, monkeypatch):
        from tui.app import DagiApp

        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task one"},
            {"role": "assistant", "content": "done"},
        ]
        restore = AffectRestore(
            baseline=AffectVector(0.1, -0.2, 0.3),
            current=AffectVector(0.3, -0.1, 0.2),
            emote_id="steady",
        )
        path = _write_session(
            tmp_path, "session_test.jsonl", "2026-08-01T10:00:00Z", raw_messages=raw
        )
        monkeypatch.setattr("tui.history.load_raw_messages", lambda _path: raw)
        monkeypatch.setattr("tui.history.load_affect_restore", lambda _path: restore)

        app = object.__new__(DagiApp)
        app._active_loop = object()
        app._current_loop_ref = [object()]
        app._restore_initial_messages = None
        app._restore_initial_affect = None
        conv = _FakeConversation()
        app.query_one = lambda _cls: conv
        app._render_restored_session = lambda _path, _messages: None
        app._enable_input = lambda: None

        DagiApp._restore_session(app, path, len(raw))

        assert app._active_loop is None
        assert app._current_loop_ref == []
        assert app._restore_initial_messages == raw
        assert app._restore_initial_affect == restore

    def test_pyside_restore_stashes_affect_beside_initial_messages(self, tmp_path, monkeypatch):
        from pyside_gui.app import DagiMainWindow

        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task one"},
        ]
        restore = AffectRestore(
            baseline=AffectVector(-0.1, 0.2, 0.0),
            current=AffectVector(0.0, 0.1, 0.2),
            emote_id="focused",
        )
        path = _write_session(
            tmp_path, "session_test.jsonl", "2026-08-01T10:00:00Z", raw_messages=raw
        )
        monkeypatch.setattr("agent.history.load_raw_messages", lambda _path: raw)
        monkeypatch.setattr("agent.history.load_affect_restore", lambda _path: restore)

        app = DagiMainWindow.__new__(DagiMainWindow)
        app._active_loop = object()
        app._current_loop_ref = [object()]
        app._restore_initial_messages = None
        app._restore_initial_affect = None
        app._conversation = _FakeConversation()
        app._left_sidebar = _FakeLeftSidebar()
        app._splitter = _FakeSplitter()
        app._enable_input = lambda: None

        DagiMainWindow._on_session_selected(app, {"path": path})

        assert app._active_loop is None
        assert app._current_loop_ref == []
        assert app._restore_initial_messages == raw
        assert app._restore_initial_affect == restore


class _FakeConversation:
    def __init__(self) -> None:
        self.info: list[str] = []
        self.errors: list[str] = []

    def append_info(self, text: str) -> None:
        self.info.append(text)

    def append_error(self, text: str) -> None:
        self.errors.append(text)

    def clear(self) -> None:
        pass


class _FakeLeftSidebar:
    def set_expanded(self, value: bool) -> None:
        self.expanded = value


class _FakeSplitter:
    def setSizes(self, sizes: list[int]) -> None:
        self.sizes = sizes
