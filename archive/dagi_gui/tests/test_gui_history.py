"""Tests for dagi_gui/history.py — GUI history adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dagi_gui.history import list_session_summaries, restore_messages


def _write_session(path: Path, raw_messages: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "session_start",
            "started_at": "2026-08-15T10:00:00",
            "model": "claude-3",
        }) + "\n")
        f.write(json.dumps({
            "type": "session_end",
            "raw_messages": raw_messages,
        }) + "\n")


class TestListSessionSummaries:
    def test_returns_empty_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            result = list_session_summaries(Path(d))
        assert result == []

    def test_path_is_string(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "test_logs.jsonl"
            _write_session(f, [{"role": "user", "content": "hello"}])
            summaries = list_session_summaries(Path(d))
        assert len(summaries) == 1
        assert isinstance(summaries[0]["path"], str)

    def test_title_and_model_present(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "abc_logs.jsonl"
            _write_session(f, [{"role": "user", "content": "My task"}])
            summaries = list_session_summaries(Path(d))
        assert summaries[0]["model"] == "claude-3"
        assert summaries[0]["title"] == "My task"

    def test_limit_respected(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(5):
                f = Path(d) / f"sess{i}_logs.jsonl"
                _write_session(f, [{"role": "user", "content": f"task {i}"}])
            summaries = list_session_summaries(Path(d), limit=3)
        assert len(summaries) == 3


class TestRestoreMessages:
    def _make_session(self) -> tuple[Path, Path, list[dict]]:
        raw = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "first task"},
            {"role": "assistant", "content": "first response"},
            {"role": "user", "content": "second task"},
            {"role": "assistant", "content": "second response"},
        ]
        tmpdir = tempfile.mkdtemp()
        p = Path(tmpdir) / "session_logs.jsonl"
        _write_session(p, raw)
        return Path(tmpdir), p, raw

    def test_restore_full_session(self):
        _, p, raw = self._make_session()
        result = restore_messages(p, len(raw))
        assert len(result["raw_messages"]) == len(raw)

    def test_restore_partial_by_turn_index(self):
        _, p, _ = self._make_session()
        result = restore_messages(p, 2)  # system + first user
        assert len(result["raw_messages"]) == 2

    def test_renderable_skips_system_messages(self):
        _, p, raw = self._make_session()
        result = restore_messages(p, len(raw))
        roles = [m["role"] for m in result["renderable"]]
        assert "system" not in roles

    def test_path_as_string(self):
        _, p, raw = self._make_session()
        result = restore_messages(str(p), len(raw))
        assert result["raw_messages"] is not None

    def test_missing_file_returns_error(self):
        result = restore_messages("/nonexistent/path.jsonl", 0)
        assert "error" in result
        assert result["messages"] == []

    def test_turns_list_contains_user_messages(self):
        _, p, raw = self._make_session()
        result = restore_messages(p, len(raw))
        assert len(result["turns"]) == 2
        assert result["turns"][0]["content"] == "first task"
