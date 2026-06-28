"""
tests/test_scheduler.py — Unit tests for the DAGI task scheduler.

Covers:
  - parse_interval: float/int inputs + edge cases
  - RunTracker.is_due: never-run, recent finish, stale finish (end-to-start timing)
  - load_schedule / save_schedule round-trip
  - ScheduleTaskTool: upsert behaviour
  - RemoveScheduledTaskTool: found / not-found
"""
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scheduler.models import (
    ScheduledTask,
    load_schedule,
    parse_interval,
    save_schedule,
)
from scheduler.tracker import RunTracker


# ---------------------------------------------------------------------------
# parse_interval
# ---------------------------------------------------------------------------

class TestParseInterval:
    def test_integer_seconds(self):
        assert parse_interval(3600) == timedelta(seconds=3600)

    def test_float_seconds(self):
        assert parse_interval(3600.0) == timedelta(seconds=3600)

    def test_fractional_seconds(self):
        assert parse_interval(90.5) == timedelta(seconds=90.5)

    def test_minimum_boundary(self):
        assert parse_interval(60) == timedelta(seconds=60)
        assert parse_interval(60.0) == timedelta(minutes=1)

    def test_below_minimum_raises(self):
        with pytest.raises(ValueError):
            parse_interval(59.9)

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            parse_interval(0)

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            parse_interval(-1)

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_interval("daily")

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_interval("whenever")

    def test_none_raises(self):
        with pytest.raises(ValueError):
            parse_interval(None)

    def test_daily_equivalent(self):
        assert parse_interval(86400.0) == timedelta(hours=24)

    def test_weekly_equivalent(self):
        assert parse_interval(604800.0) == timedelta(weeks=1)

    def test_large_interval(self):
        assert parse_interval(1_000_000.0) == timedelta(seconds=1_000_000)


# ---------------------------------------------------------------------------
# RunTracker.is_due  — end-to-start timing (compares finished_at)
# ---------------------------------------------------------------------------

def _write_run(runs: Path, task_name: str, started_at: str, finished_at: str,
               status: str = "success") -> None:
    runs.parent.mkdir(parents=True, exist_ok=True)
    with runs.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "task": task_name,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "summary": "",
        }) + "\n")


class TestRunTrackerIsDue:
    def _task(self, interval: float = 21600.0) -> ScheduledTask:
        """Default: 6-hour interval (21600 s)."""
        return ScheduledTask(name="test-task", prompt="do something", interval=interval)

    def test_never_run_is_due(self, tmp_path):
        tracker = RunTracker(tmp_path / "runs.jsonl")
        assert tracker.is_due(self._task()) is True

    def test_recent_finish_not_due(self, tmp_path):
        runs = tmp_path / "runs.jsonl"
        # Finished 1 hour ago; interval is 6h (21600s) → not due
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", one_hour_ago, one_hour_ago)
        tracker = RunTracker(runs)
        assert tracker.is_due(self._task(21600.0)) is False

    def test_stale_finish_is_due(self, tmp_path):
        runs = tmp_path / "runs.jsonl"
        # Finished 7 hours ago; interval is 6h (21600s) → due
        seven_hours_ago = (datetime.now() - timedelta(hours=7)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", seven_hours_ago, seven_hours_ago)
        tracker = RunTracker(runs)
        assert tracker.is_due(self._task(21600.0)) is True

    def test_end_to_start_uses_finished_at(self, tmp_path):
        """started_at is old enough to be due, but finished_at is not — should NOT be due."""
        runs = tmp_path / "runs.jsonl"
        started = (datetime.now() - timedelta(hours=10)).isoformat(timespec="seconds")
        finished = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", started, finished)
        tracker = RunTracker(runs)
        # interval=21600s (6h): 2h since finish < 6h → not due
        assert tracker.is_due(self._task(21600.0)) is False

    def test_disabled_task_never_due(self, tmp_path):
        tracker = RunTracker(tmp_path / "runs.jsonl")
        task = ScheduledTask(name="off", prompt="nope", interval=86400.0, enabled=False)
        assert tracker.is_due(task) is False

    def test_record_run_updates_cache_with_finished_at(self, tmp_path):
        runs = tmp_path / "runs.jsonl"
        tracker = RunTracker(runs)
        task = self._task(86400.0)  # 24h
        assert tracker.is_due(task) is True

        now = datetime.now()
        tracker.record_run("test-task", now, now, "success", "done")
        assert tracker.is_due(task) is False

    def test_latest_finish_wins_across_multiple_records(self, tmp_path):
        runs = tmp_path / "runs.jsonl"
        old = (datetime.now() - timedelta(hours=30)).isoformat(timespec="seconds")
        recent = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", old, old)
        _write_run(runs, "test-task", recent, recent)
        tracker = RunTracker(runs)
        # Most recent finish was 2h ago; interval 21600s (6h) → not due
        assert tracker.is_due(self._task(21600.0)) is False

    def test_short_interval_in_seconds(self, tmp_path):
        """Verify sub-minute precision: 90s interval, finished 2 min ago → due."""
        runs = tmp_path / "runs.jsonl"
        two_min_ago = (datetime.now() - timedelta(minutes=2)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", two_min_ago, two_min_ago)
        tracker = RunTracker(runs)
        assert tracker.is_due(self._task(90.0)) is True

    def test_short_interval_not_yet_due(self, tmp_path):
        """90s interval, finished 60s ago → not yet due."""
        runs = tmp_path / "runs.jsonl"
        one_min_ago = (datetime.now() - timedelta(seconds=60)).isoformat(timespec="seconds")
        _write_run(runs, "test-task", one_min_ago, one_min_ago)
        tracker = RunTracker(runs)
        assert tracker.is_due(self._task(90.0)) is False


# ---------------------------------------------------------------------------
# load_schedule
# ---------------------------------------------------------------------------

class TestLoadSchedule:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_schedule(tmp_path / "does_not_exist.yaml") == []

    def test_valid_yaml_float_interval(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text(textwrap.dedent("""\
            tasks:
              - name: review
                prompt: Do a code review
                interval: 86400.0
                timeout_minutes: 20
        """), encoding="utf-8")
        tasks = load_schedule(f)
        assert len(tasks) == 1
        assert tasks[0].name == "review"
        assert tasks[0].interval == 86400.0
        assert tasks[0].timeout_minutes == 20

    def test_valid_yaml_int_interval_coerced(self, tmp_path):
        """YAML integer intervals are coerced to float."""
        f = tmp_path / "schedule.yaml"
        f.write_text(textwrap.dedent("""\
            tasks:
              - name: check
                prompt: Run checks
                interval: 3600
        """), encoding="utf-8")
        tasks = load_schedule(f)
        assert tasks[0].interval == 3600.0
        assert isinstance(tasks[0].interval, float)

    def test_missing_required_field_raises(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text("tasks:\n  - name: bad\n    interval: 86400.0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field 'prompt'"):
            load_schedule(f)

    def test_missing_interval_field_raises(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text("tasks:\n  - name: x\n    prompt: y\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field 'interval'"):
            load_schedule(f)

    def test_invalid_interval_string_raises(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text(
            "tasks:\n  - name: x\n    prompt: y\n    interval: daily\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_schedule(f)

    def test_below_minimum_interval_raises(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text(
            "tasks:\n  - name: x\n    prompt: y\n    interval: 0\n",
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_schedule(f)

    def test_tasks_not_list_raises(self, tmp_path):
        f = tmp_path / "schedule.yaml"
        f.write_text("tasks: not-a-list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a list"):
            load_schedule(f)


# ---------------------------------------------------------------------------
# save_schedule / round-trip
# ---------------------------------------------------------------------------

class TestSaveSchedule:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "schedule.yaml"
        original = [
            ScheduledTask(name="a", prompt="do A", interval=21600.0),
            ScheduledTask(name="b", prompt="do B", interval=86400.0, timeout_minutes=10),
        ]
        save_schedule(path, original)
        loaded = load_schedule(path)
        assert [t.name for t in loaded] == ["a", "b"]
        assert loaded[0].interval == 21600.0
        assert loaded[1].timeout_minutes == 10

    def test_interval_stored_as_float(self, tmp_path):
        path = tmp_path / "schedule.yaml"
        save_schedule(path, [ScheduledTask(name="x", prompt="p", interval=1800.0)])
        loaded = load_schedule(path)
        assert loaded[0].interval == 1800.0

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "schedule.yaml"
        save_schedule(path, [ScheduledTask(name="x", prompt="p", interval=86400.0)])
        assert path.exists()


# ---------------------------------------------------------------------------
# ScheduleTaskTool
# ---------------------------------------------------------------------------

class TestScheduleTaskTool:
    def test_add_task(self, tmp_path):
        from tools.schedule_tools import ScheduleTaskTool
        path = tmp_path / "schedule.yaml"
        tool = ScheduleTaskTool(schedule_path=path)
        result = tool.run(name="my-task", prompt="do stuff", interval=86400.0)
        assert "my-task" in result
        tasks = load_schedule(path)
        assert len(tasks) == 1
        assert tasks[0].name == "my-task"
        assert tasks[0].interval == 86400.0

    def test_upsert_replaces_existing(self, tmp_path):
        from tools.schedule_tools import ScheduleTaskTool
        path = tmp_path / "schedule.yaml"
        tool = ScheduleTaskTool(schedule_path=path)
        tool.run(name="t", prompt="original", interval=21600.0)
        tool.run(name="t", prompt="updated", interval=86400.0)
        tasks = load_schedule(path)
        assert len(tasks) == 1
        assert tasks[0].prompt == "updated"
        assert tasks[0].interval == 86400.0

    def test_invalid_interval_returns_error(self, tmp_path):
        from tools.schedule_tools import ScheduleTaskTool
        tool = ScheduleTaskTool(schedule_path=tmp_path / "schedule.yaml")
        result = tool.run(name="bad", prompt="x", interval=0.0)
        assert "Error" in result

    def test_below_minimum_interval_returns_error(self, tmp_path):
        from tools.schedule_tools import ScheduleTaskTool
        tool = ScheduleTaskTool(schedule_path=tmp_path / "schedule.yaml")
        result = tool.run(name="fast", prompt="x", interval=30.0)
        assert "Error" in result

    def test_minimum_valid_interval(self, tmp_path):
        from tools.schedule_tools import ScheduleTaskTool
        path = tmp_path / "schedule.yaml"
        tool = ScheduleTaskTool(schedule_path=path)
        result = tool.run(name="quick", prompt="x", interval=60.0)
        assert "Error" not in result
        assert load_schedule(path)[0].interval == 60.0


# ---------------------------------------------------------------------------
# RemoveScheduledTaskTool
# ---------------------------------------------------------------------------

class TestRemoveScheduledTaskTool:
    def test_removes_existing(self, tmp_path):
        from tools.schedule_tools import RemoveScheduledTaskTool
        path = tmp_path / "schedule.yaml"
        save_schedule(path, [
            ScheduledTask(name="keep", prompt="keep this", interval=86400.0),
            ScheduledTask(name="gone", prompt="remove this", interval=21600.0),
        ])
        tool = RemoveScheduledTaskTool(schedule_path=path)
        result = tool.run(name="gone")
        assert "removed" in result
        remaining = load_schedule(path)
        assert [t.name for t in remaining] == ["keep"]

    def test_not_found_returns_message(self, tmp_path):
        from tools.schedule_tools import RemoveScheduledTaskTool
        path = tmp_path / "schedule.yaml"
        save_schedule(path, [ScheduledTask(name="x", prompt="p", interval=86400.0)])
        tool = RemoveScheduledTaskTool(schedule_path=path)
        result = tool.run(name="nonexistent")
        assert "No task named" in result
