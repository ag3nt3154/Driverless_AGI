"""
tools/schedule_tools.py — Interactive schedule management tools.

Three tools registered only in interactive (non-autonomous) sessions:
  - schedule_task          Add or update a task in schedule.yaml
  - list_scheduled_tasks   Show all tasks with last-finish and next-due info
  - remove_scheduled_task  Remove a task by name from schedule.yaml

These tools are intentionally absent from the autonomous scheduler's
registry (plan_mode_initiated_by == "dagi"), preventing scheduled tasks
from modifying the schedule themselves.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent.base_tool import BaseTool
from scheduler.models import ScheduledTask, load_schedule, parse_interval, save_schedule
from scheduler.tracker import RunTracker


class ScheduleTaskTool(BaseTool):
    """Add or update a scheduled task in .dagi/scheduler/schedule.yaml."""

    name = "schedule_task"
    description = (
        "Add or update a scheduled task that runs autonomously via run_scheduler.bat. "
        "interval is a float in seconds (end-to-start gap): e.g. 86400.0 = daily, "
        "3600.0 = every hour, 1800.0 = every 30 min, 60.0 = every minute. "
        "Minimum: 60 s (1 min). If a task with the same name exists, it is replaced."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Unique task identifier (slug, no spaces).",
            },
            "prompt": {
                "type": "string",
                "description": "The task prompt the agent will receive when the task fires.",
            },
            "interval": {
                "type": "number",
                "description": (
                    "Seconds between end of last run and start of next (float). "
                    "Examples: 86400.0 (daily), 3600.0 (1h), 1800.0 (30 min), 60.0 (1 min min)."
                ),
            },
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project directory. Defaults to current dir.",
            },
            "model": {
                "type": "string",
                "description": "Model ID from config.yaml. Omit to use the default model.",
            },
            "timeout_minutes": {
                "type": "integer",
                "description": "Hard timeout per run in minutes. Default: 30.",
            },
            "output_file": {
                "type": "string",
                "description": (
                    "Optional path where the agent's final response is saved. "
                    "Relative paths are resolved from project_path."
                ),
            },
        },
        "required": ["name", "prompt", "interval"],
    }

    def __init__(self, schedule_path: Path) -> None:
        self._path = schedule_path

    def run(
        self,
        name: str,
        prompt: str,
        interval: float,
        project_path: str = ".",
        model: str | None = None,
        timeout_minutes: int = 30,
        output_file: str | None = None,
    ) -> str:
        try:
            parse_interval(interval)
        except ValueError as exc:
            return f"Error: invalid interval — {exc}"

        tasks = load_schedule(self._path)
        tasks = [t for t in tasks if t.name != name]  # upsert: drop existing
        tasks.append(ScheduledTask(
            name=name,
            prompt=prompt,
            interval=float(interval),
            project_path=project_path,
            model=model,
            timeout_minutes=timeout_minutes,
            output_file=output_file,
        ))
        save_schedule(self._path, tasks)
        return (
            f"Task '{name}' saved to {self._path}. "
            f"It will run with a {interval}s gap between runs when run_scheduler.bat fires."
        )


class ListScheduledTasksTool(BaseTool):
    """List all scheduled tasks with last-finish time and next-due estimate."""

    name = "list_scheduled_tasks"
    description = (
        "List all tasks in .dagi/scheduler/schedule.yaml, "
        "including their interval, last finish time, and whether they are currently due."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, schedule_path: Path, runs_path: Path) -> None:
        self._schedule_path = schedule_path
        self._runs_path = runs_path

    def run(self) -> str:
        tasks = load_schedule(self._schedule_path)
        if not tasks:
            return f"No tasks found in {self._schedule_path}."

        tracker = RunTracker(self._runs_path)
        now = datetime.now()
        lines = [f"Scheduled tasks ({len(tasks)} total):\n"]

        for t in tasks:
            td = t.interval_td()
            last_finish = tracker.last_finish(t.name)
            due = tracker.is_due(t)

            if last_finish is None:
                finish_str = "never"
                next_str = "now (never run)"
            else:
                finish_str = last_finish.strftime("%Y-%m-%d %H:%M")
                if due:
                    next_str = "now (overdue)"
                else:
                    remaining = (last_finish + td) - now
                    h, rem = divmod(int(remaining.total_seconds()), 3600)
                    m = rem // 60
                    next_str = f"in {h}h {m}m" if h else f"in {m}m"

            status = "✓ due" if due else "○ waiting"
            enabled_tag = "" if t.enabled else " [disabled]"
            lines.append(
                f"  {status}  {t.name}{enabled_tag}\n"
                f"         interval={t.interval}s  timeout={t.timeout_minutes}min\n"
                f"         last_finish={finish_str}  next={next_str}\n"
                f"         prompt={t.prompt[:80]}{'…' if len(t.prompt) > 80 else ''}\n"
            )
        return "\n".join(lines)


class RemoveScheduledTaskTool(BaseTool):
    """Remove a scheduled task from .dagi/scheduler/schedule.yaml by name."""

    name = "remove_scheduled_task"
    description = "Remove a scheduled task by name from schedule.yaml."
    _parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The task name to remove.",
            },
        },
        "required": ["name"],
    }

    def __init__(self, schedule_path: Path) -> None:
        self._path = schedule_path

    def run(self, name: str) -> str:
        tasks = load_schedule(self._path)
        remaining = [t for t in tasks if t.name != name]
        if len(remaining) == len(tasks):
            return f"No task named '{name}' found in {self._path}."
        save_schedule(self._path, remaining)
        return f"Task '{name}' removed from {self._path}."
