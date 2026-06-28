"""
scheduler/models.py — Schedule data types and YAML loading.

`interval` is a float in seconds representing the gap between the end of one
run and the start of the next (end-to-start timing).

Examples:
    interval: 86400.0   # daily  (24 h)
    interval: 21600.0   # every 6 hours
    interval: 1800.0    # every 30 minutes
    interval: 60.0      # every 1 minute (minimum)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml

_MIN_SECONDS: float = 60.0  # 1 minute


def parse_interval(seconds: float | int) -> timedelta:
    """Validate and convert a float interval (seconds) to a timedelta.

    Raises ValueError if seconds < 60 or not a real number.
    """
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        raise ValueError(f"interval must be a number (seconds), got {seconds!r}")
    if s < _MIN_SECONDS:
        raise ValueError(
            f"interval {s} s is below the minimum ({_MIN_SECONDS:.0f} s = 1 minute)"
        )
    return timedelta(seconds=s)


@dataclass
class ScheduledTask:
    """A single scheduled task definition from schedule.yaml."""

    name: str
    prompt: str
    interval: float         # seconds (end-to-start gap)
    project_path: str = "."
    model: str | None = None
    timeout_minutes: int = 30
    output_file: str | None = None
    enabled: bool = True

    def interval_td(self) -> timedelta:
        return timedelta(seconds=self.interval)


def load_schedule(path: Path) -> list[ScheduledTask]:
    """Load schedule.yaml and return a list of ScheduledTask objects.

    Returns an empty list if the file does not exist.
    Raises ValueError for malformed entries or invalid intervals.
    """
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("tasks", [])
    if not isinstance(entries, list):
        raise ValueError(
            f"schedule.yaml 'tasks' must be a list, got {type(entries).__name__}"
        )
    tasks: list[ScheduledTask] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"Task #{i} must be a mapping, got {type(entry).__name__}")
        for required in ("name", "prompt", "interval"):
            if required not in entry:
                raise ValueError(f"Task #{i} is missing required field '{required}'")
        interval_s = float(entry["interval"])
        parse_interval(interval_s)  # validate eagerly
        tasks.append(ScheduledTask(
            name=entry["name"],
            prompt=entry["prompt"],
            interval=interval_s,
            project_path=str(entry.get("project_path", ".")),
            model=entry.get("model"),
            timeout_minutes=int(entry.get("timeout_minutes", 30)),
            output_file=entry.get("output_file"),
            enabled=bool(entry.get("enabled", True)),
        ))
    return tasks


def save_schedule(path: Path, tasks: list[ScheduledTask]) -> None:
    """Write a list of ScheduledTask objects back to schedule.yaml."""
    entries = []
    for t in tasks:
        entry: dict = {"name": t.name, "prompt": t.prompt, "interval": t.interval}
        if t.project_path != ".":
            entry["project_path"] = t.project_path
        if t.model is not None:
            entry["model"] = t.model
        if t.timeout_minutes != 30:
            entry["timeout_minutes"] = t.timeout_minutes
        if t.output_file is not None:
            entry["output_file"] = t.output_file
        if not t.enabled:
            entry["enabled"] = False
        entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump({"tasks": entries}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
