"""
scheduler/runner.py — DAGI task scheduler entry point.

Usage:
    python -m scheduler.runner             # run all due tasks
    python -m scheduler.runner --dry-run   # show what would run, no execution

The scheduler loads .dagi/scheduler/schedule.yaml, checks which tasks are due,
and runs them sequentially via AgentLoop. All tasks run autonomously:
  - ask_user auto-responds after 60s with the recommended option
  - plan mode auto-approves
  - each task has a per-task timeout (default 30 min)

Results are written to:
  - .dagi/scheduler/runs.jsonl  (execution log, append-only)
  - task.output_file            (optional per-task output, if configured)
"""
from __future__ import annotations

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from agent import DAGI_ROOT
from agent.config_loader import resolve_model_config
from agent.loop import AgentCallbacks, AgentLoop
from agent.session import SessionTracker
from scheduler.models import ScheduledTask, load_schedule
from scheduler.tracker import RunTracker

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dagi.scheduler")

_SCHEDULE_PATH = DAGI_ROOT / ".dagi" / "scheduler" / "schedule.yaml"
_RUNS_PATH = DAGI_ROOT / ".dagi" / "scheduler" / "runs.jsonl"
_ASK_USER_TIMEOUT = 60  # seconds before ask_user auto-responds


def _scheduler_callbacks(task: ScheduledTask, result_holder: list[str]) -> AgentCallbacks:
    """Build minimal AgentCallbacks for autonomous (unattended) execution."""
    def _on_ask_user(question: str, options: list[dict], timeout: float | None) -> str:
        log.info("[%s] ask_user (auto-responding): %s", task.name, question[:120])
        return "Proceed with your best judgment"

    def _on_assistant_text(text: str) -> None:
        log.info("[%s] %s", task.name, text[:200])
        # Keep the last response so we can write it to output_file
        if result_holder:
            result_holder[0] = text
        else:
            result_holder.append(text)

    def _on_done(response: str) -> None:
        log.info("[%s] Task complete.", task.name)
        if result_holder:
            result_holder[0] = response
        else:
            result_holder.append(response)

    return AgentCallbacks(
        on_ask_user=_on_ask_user,
        on_assistant_text=_on_assistant_text,
        on_done=_on_done,
    )


def _run_task(task: ScheduledTask, tracker: RunTracker) -> None:
    """Execute one scheduled task and record the result."""
    log.info("--- Running task: %s ---", task.name)
    started_at = datetime.now()
    project_path = Path(task.project_path).resolve()
    result_holder: list[str] = []

    try:
        config = resolve_model_config(
            model_id=task.model or None,
            project_path=project_path,
        )
    except Exception as exc:
        log.error("[%s] Config error: %s", task.name, exc)
        tracker.record_run(task.name, started_at, datetime.now(), "error", str(exc))
        return

    config.autonomous = True
    config.ask_user_timeout = _ASK_USER_TIMEOUT

    tracker_session = SessionTracker(
        model=config.model,
        logs_dir=project_path / ".dagi" / "logs",
    )
    callbacks = _scheduler_callbacks(task, result_holder)
    loop = AgentLoop(config, callbacks=callbacks, tracker=tracker_session)

    exc_holder: list[BaseException] = []

    def _run() -> None:
        try:
            loop.run(task.prompt)
        except Exception as exc:  # noqa: BLE001
            exc_holder.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    timeout_sec = task.timeout_minutes * 60
    thread.join(timeout=timeout_sec)

    loop.finish()

    if thread.is_alive():
        log.warning("[%s] Timed out after %d min.", task.name, task.timeout_minutes)
        status = "timeout"
        summary = f"Timed out after {task.timeout_minutes} minutes."
    elif exc_holder:
        log.error("[%s] Error: %s", task.name, exc_holder[0])
        status = "error"
        summary = str(exc_holder[0])[:500]
    else:
        status = "success"
        summary = (result_holder[0] if result_holder else "")[:500]

    tracker.record_run(task.name, started_at, datetime.now(), status, summary)

    if task.output_file and status == "success" and result_holder:
        output_path = Path(task.output_file)
        if not output_path.is_absolute():
            output_path = project_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_holder[0], encoding="utf-8")
        log.info("[%s] Output written to %s", task.name, output_path)


def main(dry_run: bool = False) -> None:
    """Load the schedule, find due tasks, and run them sequentially."""
    tasks = load_schedule(_SCHEDULE_PATH)
    if not tasks:
        log.info("No tasks found in %s — nothing to do.", _SCHEDULE_PATH)
        return

    tracker = RunTracker(_RUNS_PATH)
    due = [t for t in tasks if tracker.is_due(t)]

    if not due:
        log.info("No tasks are due. Checked %d task(s).", len(tasks))
        return

    log.info("%d of %d task(s) are due.", len(due), len(tasks))

    if dry_run:
        for t in due:
            log.info("  [dry-run] would run: %s (interval=%ss)", t.name, t.interval)
        return

    for task in due:
        _run_task(task, tracker)

    log.info("Scheduler run complete.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    main(dry_run=dry)
