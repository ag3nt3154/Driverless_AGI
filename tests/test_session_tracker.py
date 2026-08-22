"""tests/test_session_tracker.py — Unit tests for SessionTracker."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace

from agent.session import SessionTracker


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class TestInit:
    def test_creates_logs_dir_and_session_file(self, tmp_path):
        logs_dir = tmp_path / "logs"
        tracker = SessionTracker(model="test-model", logs_dir=logs_dir)

        assert logs_dir.is_dir()
        assert tracker._path.exists()

        records = _read_jsonl(tracker._path)
        assert records[0]["type"] == "session_start"
        assert records[0]["model"] == "test-model"

    def test_thread_id_defaults_to_random_hex(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        assert isinstance(tracker.thread_id, str)
        assert len(tracker.thread_id) > 0

    def test_thread_id_uses_supplied_value(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path, thread_id="fixed-id")
        assert tracker.thread_id == "fixed-id"


class TestRecordMessages:
    def test_record_user_and_system_append_jsonl(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.record_system("sys prompt")
        tracker.record_user("hello")

        records = _read_jsonl(tracker._path)
        messages = [r for r in records if r["type"] == "message"]
        assert [m["entity"] for m in messages] == ["system", "user"]
        assert messages[1]["content"] == "hello"

    def test_record_assistant_extracts_usage_fields(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.001)

        tracker.record_assistant("hi there", usage, tool_calls=[])

        records = _read_jsonl(tracker._path)
        msg = [r for r in records if r["type"] == "message"][0]
        assert msg["input_tokens"] == 10
        assert msg["output_tokens"] == 5
        assert msg["cost"] == 0.001

    def test_record_assistant_handles_none_usage(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.record_assistant("hi", None, tool_calls=[])

        records = _read_jsonl(tracker._path)
        msg = [r for r in records if r["type"] == "message"][0]
        assert msg["input_tokens"] is None
        assert msg["output_tokens"] is None
        assert msg["cost"] is None


class TestRecordToolEvents:
    def test_record_tool_start_and_end_write_separate_records(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.record_tool_start("bash", "runs shell", '{"cmd": "ls"}')
        tracker.record_tool_end("bash", "file1\nfile2")

        records = _read_jsonl(tracker._path)
        types = [r["type"] for r in records]
        assert "tool_start" in types
        assert "tool_end" in types

    def test_record_subagent_end_truncates_result_to_500_chars(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        long_result = "x" * 1000
        tracker.record_subagent_start("sub1", "explore", "find stuff", depth=1)
        tracker.record_subagent_end("sub1", long_result, depth=1)

        records = _read_jsonl(tracker._path)
        end_record = [r for r in records if r["type"] == "subagent_end"][0]
        assert len(end_record["result"]) == 500


class TestChildTracker:
    def test_child_tracker_writes_flow_through_to_parent_file(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")

        child.record_user("child says hi")

        records = _read_jsonl(parent._path)
        messages = [r for r in records if r["type"] == "message"]
        child_msg = [m for m in messages if m["content"] == "child says hi"][0]
        assert child_msg["subagent_id"] == "sub1"
        assert child_msg["depth"] == 1

    def test_child_has_no_own_session_file(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        assert child._path is None

    def test_nested_child_depth_increments(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        grandchild = child.child_tracker("sub2")

        grandchild.record_user("deep message")

        records = _read_jsonl(parent._path)
        messages = [r for r in records if r["type"] == "message"]
        deep_msg = [m for m in messages if m["content"] == "deep message"][0]
        assert deep_msg["depth"] == 2
        assert deep_msg["subagent_id"] == "sub2"

    def test_child_cannot_replace_root_affect_controller_binding(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        root_controller = object()
        child_controller = object()

        parent.bind_affect_controller(root_controller)
        child.bind_affect_controller(child_controller)

        assert parent.affect_controller is root_controller
        assert child.affect_controller is root_controller


class TestAffectPersistence:
    def test_record_affect_writes_structured_jsonl_record(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)

        tracker.record_affect(
            "affect_adjust",
            {
                "prior": [0.1, -0.2, 0.3],
                "delta": [0.2, 0.1, -0.1],
                "current": [0.3, -0.1, 0.2],
                "emote_id": "steady",
            },
        )

        records = _read_jsonl(tracker._path)
        affect = [r for r in records if r["type"] == "affect_adjust"][0]
        assert affect["payload"] == {
            "prior": [0.1, -0.2, 0.3],
            "delta": [0.2, 0.1, -0.1],
            "current": [0.3, -0.1, 0.2],
            "emote_id": "steady",
        }
        assert isinstance(affect["timestamp"], str)

    def test_child_record_affect_reuses_parent_session_file(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")

        child.record_affect(
            "affect_drift",
            {
                "prior": [0.5, 0.0, 0.0],
                "delta": [-0.05, 0.0, 0.0],
                "current": [0.45, 0.0, 0.0],
                "emote_id": "steady",
            },
        )

        records = _read_jsonl(parent._path)
        affect = [r for r in records if r["type"] == "affect_drift"][0]
        assert affect["subagent_id"] == "sub1"
        assert affect["depth"] == 1

    def test_bind_affect_controller_sets_root_once_for_children_to_reuse(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        controller = object()

        parent.bind_affect_controller(controller)

        assert parent.affect_controller is controller
        assert child.affect_controller is controller


class TestFinish:
    def test_finish_writes_session_end_with_totals(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        usage1 = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=0.01)
        usage2 = SimpleNamespace(prompt_tokens=20, completion_tokens=8, cost=0.02)
        tracker.record_assistant("a1", usage1, tool_calls=[])
        tracker.record_assistant("a2", usage2, tool_calls=[])

        tracker.finish()

        records = _read_jsonl(tracker._path)
        end = [r for r in records if r["type"] == "session_end"][0]
        assert end["total_input_tokens"] == 30
        assert end["total_output_tokens"] == 13
        assert round(end["total_cost"], 2) == 0.03

    def test_finish_on_child_rolls_stats_into_parent_and_writes_nothing_itself(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3, cost=0.005)
        child.record_assistant("child result", usage, tool_calls=[])

        records_before = _read_jsonl(parent._path)
        child.finish()
        records_after = _read_jsonl(parent._path)

        # finish() on a child must not append a new record to the parent file.
        assert len(records_after) == len(records_before)
        assert len(parent._subagent_stats) == 1
        assert parent._subagent_stats[0]["subagent_id"] == "sub1"
        assert parent._subagent_stats[0]["input_tokens"] == 7

    def test_finish_merges_subagent_stats_into_root_totals(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3, cost=None)
        child.record_assistant("child result", usage, tool_calls=[])
        child.finish()

        parent.finish()

        records = _read_jsonl(parent._path)
        end = [r for r in records if r["type"] == "session_end"][0]
        assert end["total_input_tokens"] == 7
        assert end["total_output_tokens"] == 3


class TestRenameWithSlug:
    def test_renames_file_and_updates_path(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        old_path = tracker._path
        assert old_path.exists()

        tracker.rename_with_slug("fix_login_bug")

        assert not old_path.exists()
        assert tracker._path.exists()
        assert tracker._path.name.endswith("_fix_login_bug_logs.jsonl")
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", tracker._path.name)

    def test_subsequent_writes_go_to_renamed_file(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("my_session")
        tracker.record_user("hello after rename")

        records = _read_jsonl(tracker._path)
        user_msgs = [r for r in records if r.get("entity") == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "hello after rename"

    def test_second_rename_is_noop(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("first_name")
        path_after_first = tracker._path
        tracker.rename_with_slug("second_name")
        assert tracker._path == path_after_first

    def test_sanitises_slug(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("Hello World! @#$ Fix 123")
        assert "hello_world_fix_123" in tracker._path.name

    def test_truncates_long_slug(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        long_slug = "a" * 100
        tracker.rename_with_slug(long_slug)
        parts = tracker._path.stem.split("_logs")[0]
        slug_part = "_".join(parts.split("_")[2:])  # skip YYYY-MM-DD, HH-MM-SS
        assert len(slug_part) <= 50

    def test_child_tracker_rename_is_noop(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        old_parent_path = parent._path
        child.rename_with_slug("child_slug")
        assert parent._path == old_parent_path
