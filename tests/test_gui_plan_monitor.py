"""Tests for dagi_gui.plan_monitor."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dagi_gui.plan_monitor import PlanMonitor


def make_writer() -> MagicMock:
    writer = MagicMock()
    writer.write = MagicMock()
    return writer


class TestPlanMonitorPoll:
    """Tests using the polling path (no watchdog required)."""

    def test_emits_current_content_on_start(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.md"
        plan.write_text("# Plan\n- step 1")
        writer = make_writer()

        monitor = PlanMonitor(writer, plan)
        # Call _emit_if_exists directly (same as start() does before thread)
        monitor._emit_if_exists()

        writer.write.assert_called_once_with("plan_update", content="# Plan\n- step 1")

    def test_no_emit_when_file_missing(self, tmp_path: Path) -> None:
        writer = make_writer()
        monitor = PlanMonitor(writer, tmp_path / "PLAN.md")
        monitor._emit_if_exists()
        writer.write.assert_not_called()

    def test_poll_detects_file_change(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.md"
        plan.write_text("v1")
        writer = make_writer()

        monitor = PlanMonitor(writer, plan)
        # Monkey-patch interval for test speed
        monitor._POLL_INTERVAL = 0.05

        # Run polling for a brief period
        stop = threading.Event()
        events: list[str] = []

        def capture_write(event_type: str, **kwargs: object) -> None:
            if event_type == "plan_update":
                events.append(str(kwargs.get("content", "")))

        writer.write.side_effect = capture_write

        t = threading.Thread(target=monitor._watch_poll, daemon=True)
        t.start()
        time.sleep(0.1)
        plan.write_text("v2")
        time.sleep(0.2)
        monitor.stop()
        t.join(timeout=1)

        assert "v2" in events

    def test_poll_emits_on_file_creation(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.md"
        writer = make_writer()

        events: list[str] = []

        def capture_write(event_type: str, **kwargs: object) -> None:
            if event_type == "plan_update":
                events.append(str(kwargs.get("content", "")))

        writer.write.side_effect = capture_write

        monitor = PlanMonitor(writer, plan)
        monitor._POLL_INTERVAL = 0.05

        t = threading.Thread(target=monitor._watch_poll, daemon=True)
        t.start()
        time.sleep(0.1)
        plan.write_text("new content")
        time.sleep(0.2)
        monitor.stop()
        t.join(timeout=1)

        assert "new content" in events

    def test_stop_exits_poll_thread(self, tmp_path: Path) -> None:
        plan = tmp_path / "PLAN.md"
        plan.write_text("x")
        writer = make_writer()

        monitor = PlanMonitor(writer, plan)
        monitor._POLL_INTERVAL = 0.1

        t = threading.Thread(target=monitor._watch_poll, daemon=True)
        t.start()
        time.sleep(0.05)
        monitor.stop()
        t.join(timeout=2)
        assert not t.is_alive()

    def test_start_is_idempotent(self, tmp_path: Path) -> None:
        """Calling start() twice doesn't spawn a second thread."""
        plan = tmp_path / "PLAN.md"
        plan.write_text("x")
        writer = make_writer()

        monitor = PlanMonitor(writer, plan)
        # Patch _watch_watchdog to use poll path by raising immediately
        monitor._watch_watchdog = monitor._watch_poll  # type: ignore[method-assign]
        monitor._POLL_INTERVAL = 60  # won't fire during test

        monitor.start()
        thread_before = monitor._thread
        monitor.start()  # second call — should no-op
        assert monitor._thread is thread_before
        monitor.stop()
