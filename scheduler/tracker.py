"""
scheduler/tracker.py — Execution tracking for scheduled tasks.

RunTracker reads and writes .dagi/scheduler/runs.jsonl, an append-only log
of every scheduler execution. It answers two questions:
  - Is a given task due? (is_due)
  - Record that a task ran and what happened. (record_run)

Run record format (one JSON object per line):
{
    "task":        "my-task-name",
    "started_at":  "2026-06-28T08:00:00",   # ISO 8601, no timezone (local time)
    "finished_at": "2026-06-28T08:12:34",
    "status":      "success" | "timeout" | "error",
    "summary":     "First 500 chars of the agent's final response."
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scheduler.models import ScheduledTask


class RunTracker:
    """Tracks task execution history via an append-only JSONL file."""

    def __init__(self, runs_path: Path) -> None:
        self._path = runs_path
        self._last_finish: dict[str, datetime] = self._load_last_finishes()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_due(self, task: ScheduledTask) -> bool:
        """Return True if the task has never run or interval has elapsed since last finish.

        Timing is end-to-start: the interval is measured from when the previous
        run *finished* to when the next run *starts*. This guarantees a full
        interval-hour gap between runs regardless of task duration.
        """
        if not task.enabled:
            return False
        last_finish = self._last_finish.get(task.name)
        if last_finish is None:
            return True
        return datetime.now() - last_finish >= task.interval_td()

    def record_run(
        self,
        task_name: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        summary: str = "",
    ) -> None:
        """Append a run record to runs.jsonl and update the in-memory cache."""
        record = {
            "task": task_name,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "status": status,
            "summary": summary[:500],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        self._last_finish[task_name] = finished_at

    def last_finish(self, task_name: str) -> datetime | None:
        """Return the finish datetime of the most recent run, or None if never run."""
        return self._last_finish.get(task_name)

    def all_records(self) -> list[dict]:
        """Return every record in chronological order (for list_scheduled_tasks)."""
        if not self._path.exists():
            return []
        records = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_last_finishes(self) -> dict[str, datetime]:
        """Read runs.jsonl and build a dict of task_name -> latest finished_at."""
        result: dict[str, datetime] = {}
        for record in self.all_records():
            name = record.get("task", "")
            raw_ts = record.get("finished_at", "")
            if not name or not raw_ts:
                continue
            try:
                ts = datetime.fromisoformat(raw_ts)
            except ValueError:
                continue
            if name not in result or ts > result[name]:
                result[name] = ts
        return result
