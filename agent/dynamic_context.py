from __future__ import annotations

from pathlib import Path
from typing import Protocol

from tools._plan_parser import parse_subtask_statuses

SENTINEL = "## Session Context"


class AgentConfigLike(Protocol):
    python_env: str
    active_plan_file: str | None
    plan_mode: bool


def build_dynamic_context(config: AgentConfigLike, affect_line: str | None = None) -> str:
    """Build the ephemeral session context board appended to provider requests."""
    parts = [SENTINEL]

    if config.python_env:
        parts.append(f"Python env: {config.python_env}")

    plan_file = config.active_plan_file
    if plan_file and not config.plan_mode:
        parts.append(f"Plan: {plan_file}")
        statuses = _load_plan_statuses(Path(plan_file))
        if statuses:
            active = _active_status(statuses)
            if active:
                idx = statuses.index(active) + 1
                parts.append(f"Active: {idx}. {active['name']}")
            parts.append(f"Status: {_status_line(statuses)}")

    if affect_line:
        parts.append(affect_line)

    return "\n".join(parts)


def _load_plan_statuses(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    return parse_subtask_statuses(text)


def _active_status(statuses: list[dict]) -> dict | None:
    return next(
        (s for s in statuses if s["status"] == "in_progress"),
        next((s for s in statuses if s["status"] == "pending"), None),
    )


def _status_line(statuses: list[dict]) -> str:
    marker_map = {
        "pending": " ",
        "in_progress": "~",
        "complete": "x",
        "failed": "!",
    }
    return " ".join(
        f"{i}.[{marker_map.get(s['status'], '?')}]"
        for i, s in enumerate(statuses, start=1)
    )
