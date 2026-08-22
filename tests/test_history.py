import json
import pytest
from pathlib import Path

from agent.affect import AffectRestore, AffectVector
from tui.history import build_turn_list, load_raw_messages, load_sessions


def _write_session(tmp_path: Path, filename: str, started_at: str,
                   model: str = "test-model",
                   raw_messages: list | None = None) -> Path:
    """Helper: write a minimal JSONL session file."""
    path = tmp_path / filename
    lines = [
        {"type": "session_start", "thread_id": "t1", "model": model, "started_at": started_at},
    ]
    if raw_messages is not None:
        lines.append({
            "type": "session_end",
            "finished_at": started_at,
            "raw_messages": raw_messages,
        })
    path.write_text(
        "\n".join(json.dumps(l) for l in lines),
        encoding="utf-8",
    )
    return path


class TestLoadSessions:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert load_sessions(tmp_path) == []

    def test_loads_new_format(self, tmp_path):
        _write_session(tmp_path, "2026-08-01_12-00-00_fix_bug_logs.jsonl", "2026-08-01T12:00:00Z")
        result = load_sessions(tmp_path)
        assert len(result) == 1
        assert result[0]["filename"] == "2026-08-01_12-00-00_fix_bug_logs.jsonl"

    def test_loads_old_format(self, tmp_path):
        _write_session(tmp_path, "session_2026-08-01_12-00-00.jsonl", "2026-08-01T12:00:00Z")
        result = load_sessions(tmp_path)
        assert len(result) == 1

    def test_sorted_newest_first(self, tmp_path):
        _write_session(tmp_path, "session_2026-08-01_10-00-00.jsonl", "2026-08-01T10:00:00Z")
        _write_session(tmp_path, "session_2026-08-01_12-00-00.jsonl", "2026-08-01T12:00:00Z")
        result = load_sessions(tmp_path)
        assert result[0]["started_at"] > result[1]["started_at"]

    def test_max_sessions_respected(self, tmp_path):
        for i in range(5):
            _write_session(
                tmp_path, f"session_2026-08-01_1{i}-00-00.jsonl", f"2026-08-01T1{i}:00:00Z"
            )
        result = load_sessions(tmp_path, max_sessions=3)
        assert len(result) == 3

    def test_title_from_first_user_message(self, tmp_path):
        raw = [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "Please refactor the auth module"},
        ]
        _write_session(tmp_path, "2026-08-01_10-00-00_test_logs.jsonl",
                       "2026-08-01T10:00:00Z", raw_messages=raw)
        result = load_sessions(tmp_path)
        assert result[0]["title"] == "Please refactor the auth module"

    def test_title_truncated_at_60_chars(self, tmp_path):
        long_msg = "A" * 80
        raw = [{"role": "user", "content": long_msg}]
        _write_session(tmp_path, "2026-08-01_10-00-00_test_logs.jsonl",
                       "2026-08-01T10:00:00Z", raw_messages=raw)
        result = load_sessions(tmp_path)
        assert len(result[0]["title"]) <= 61  # 60 chars + ellipsis

    def test_no_duplicate_when_file_matches_both_globs(self, tmp_path):
        # A file named session_foo_logs.jsonl matches both *_logs.jsonl AND session_*.jsonl.
        # Deduplication must ensure it appears only once.
        _write_session(
            tmp_path, "session_2026-08-01_10-00-00_logs.jsonl", "2026-08-01T10:00:00Z"
        )
        result = load_sessions(tmp_path)
        assert len(result) == 1

    def test_corrupted_file_skipped(self, tmp_path):
        bad = tmp_path / "session_2026-08-01_12-00-00.jsonl"
        bad.write_text("not json\n{bad}", encoding="utf-8")
        result = load_sessions(tmp_path)
        assert result == []


class TestLoadRawMessages:
    def test_returns_none_when_no_session_end(self, tmp_path):
        path = _write_session(tmp_path, "session_test.jsonl", "2026-08-01T10:00:00Z")
        assert load_raw_messages(path) is None

    def test_returns_raw_messages(self, tmp_path):
        raw = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
        path = _write_session(tmp_path, "session_test.jsonl", "2026-08-01T10:00:00Z",
                               raw_messages=raw)
        result = load_raw_messages(path)
        assert result == raw

    def test_returns_none_on_missing_file(self, tmp_path):
        result = load_raw_messages(tmp_path / "nonexistent.jsonl")
        assert result is None

    def test_returns_none_when_raw_messages_empty_list(self, tmp_path):
        path = tmp_path / "session_test.jsonl"
        lines = [
            {"type": "session_start", "model": "m", "started_at": "2026-08-01T10:00:00Z"},
            {"type": "session_end", "finished_at": "2026-08-01T10:00:00Z", "raw_messages": []},
        ]
        path.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
        assert load_raw_messages(path) is None


class TestLoadAffectRestore:
    def test_returns_latest_valid_affect_restore(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -0.2, 0.3],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
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
            {
                "type": "affect_drift",
                "payload": {
                    "prior": [0.3, -0.1, 0.2],
                    "delta": [-0.05, 0.0, 0.0],
                    "current": [0.25, -0.1, 0.2],
                    "emote_id": "steady",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        result = load_affect_restore(path)

        assert result == AffectRestore(
            baseline=AffectVector(0.1, -0.2, 0.3),
            current=AffectVector(0.25, -0.1, 0.2),
            emote_id="steady",
        )

    def test_preserves_original_baseline_when_latest_state_changes(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [-0.4, 0.2, 0.0],
                    "current": [-0.4, 0.2, 0.0],
                    "emote_id": "tense",
                },
            },
            {
                "type": "affect_adjust",
                "payload": {
                    "prior": [-0.4, 0.2, 0.0],
                    "delta": [0.5, -0.1, 0.3],
                    "current": [0.1, 0.1, 0.3],
                    "emote_id": "steady",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        result = load_affect_restore(path)

        assert result is not None
        assert result.baseline == AffectVector(-0.4, 0.2, 0.0)
        assert result.current == AffectVector(0.1, 0.1, 0.3)

    def test_returns_none_for_legacy_logs_without_affect_records(self, tmp_path):
        from agent.history import load_affect_restore

        path = _write_session(
            tmp_path,
            "session_test.jsonl",
            "2026-08-01T10:00:00Z",
            raw_messages=[{"role": "user", "content": "hello"}],
        )

        assert load_affect_restore(path) is None

    def test_skips_malformed_latest_record_and_warns_once(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -0.2, 0.3],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
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
            {
                "type": "affect_drift",
                "payload": {
                    "prior": [0.3, -0.1, 0.2],
                    "delta": [-0.05, 0.0, 0.0],
                    "current": ["bad", -0.1, 0.2],
                    "emote_id": "steady",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        with pytest.warns(UserWarning, match="Malformed affect record"):
            result = load_affect_restore(path)

        assert result is not None
        assert result.current == AffectVector(0.3, -0.1, 0.2)
        assert result.emote_id == "energized"

    def test_returns_none_for_malformed_affect_init_and_warns_once(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -0.2],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
            }
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        with pytest.warns(UserWarning, match="Malformed affect record"):
            assert load_affect_restore(path) is None

    def test_skips_out_of_range_latest_current_and_restores_previous_valid(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -0.2, 0.3],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
            },
            {
                "type": "affect_adjust",
                "payload": {
                    "prior": [0.1, -0.2, 0.3],
                    "delta": [0.2, 0.0, 0.0],
                    "current": [0.3, -0.2, 0.3],
                    "emote_id": "bright",
                },
            },
            {
                "type": "affect_drift",
                "payload": {
                    "prior": [0.3, -0.2, 0.3],
                    "delta": [0.8, 0.0, 0.0],
                    "current": [1.1, -0.2, 0.3],
                    "emote_id": "bright",
                },
            },
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        with pytest.warns(UserWarning, match="Malformed affect record"):
            result = load_affect_restore(path)

        assert result == AffectRestore(
            baseline=AffectVector(0.1, -0.2, 0.3),
            current=AffectVector(0.3, -0.2, 0.3),
            emote_id="bright",
        )

    def test_returns_none_for_out_of_range_baseline(self, tmp_path):
        from agent.history import load_affect_restore

        path = tmp_path / "session_test.jsonl"
        lines = [
            {
                "type": "affect_init",
                "payload": {
                    "baseline": [0.1, -1.2, 0.3],
                    "current": [0.1, -0.2, 0.3],
                    "emote_id": "steady",
                },
            }
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

        with pytest.warns(UserWarning, match="Malformed affect record"):
            assert load_affect_restore(path) is None


class TestBuildTurnList:
    def test_empty_messages_returns_empty(self):
        assert build_turn_list([]) == []

    def test_only_user_messages_included(self):
        raw = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "follow-up"},
        ]
        turns = build_turn_list(raw)
        assert len(turns) == 2
        assert turns[0]["index"] == 1
        assert turns[1]["index"] == 3

    def test_label_truncated_at_70_chars(self):
        raw = [{"role": "user", "content": "X" * 100}]
        turns = build_turn_list(raw)
        assert len(turns[0]["label"]) <= 71  # 70 chars + ellipsis

    def test_label_not_truncated_when_short(self):
        raw = [{"role": "user", "content": "short message"}]
        turns = build_turn_list(raw)
        assert turns[0]["label"] == "short message"
        assert turns[0]["content"] == "short message"

    def test_preserves_index_correctly(self):
        raw = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]
        turns = build_turn_list(raw)
        assert turns[0]["index"] == 1
        assert turns[1]["index"] == 3
