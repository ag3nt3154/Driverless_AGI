"""Harness: workspace management, agent invocation, timeout, per-run logging."""
from __future__ import annotations

import dataclasses
import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG_DIR = Path(__file__).parent
TASKS_DIR = PKG_DIR / "tasks"
CONFIG_PATH = PKG_DIR / "config_dagi_eval.yaml"

# Every sweep gets its own timestamped folder here (see new_run_dir()):
#   .dagi/benchmarks/dagi_eval/logs/<ts>_log/
#     result.jsonl        one row per task + one "__aggregate__" row
#     code/<task_name>/   copy of that task's final workspace
#     sessions/<task_name>/session_*.jsonl   SessionTracker transcripts
# repo_root = .../benchmarks/dagi_eval -> .../benchmarks -> repo root
REPO_ROOT = PKG_DIR.parent.parent
RUNS_DIR = REPO_ROOT / ".dagi" / "benchmarks" / "dagi_eval" / "logs"


class BenchmarkTimeout(Exception):
    """Raised inside on_iteration to abort AgentLoop at an iteration boundary."""


def discover_tasks(tasks_dir: Path = TASKS_DIR,
                   only: list[str] | None = None) -> list[Path]:
    tasks = sorted(p for p in tasks_dir.iterdir() if (p / "task.yaml").exists())
    if only:
        missing = set(only) - {t.name for t in tasks}
        if missing:
            raise SystemExit(f"unknown tasks: {sorted(missing)}")
        tasks = [t for t in tasks if t.name in only]
    return tasks


def prepare_workspace(task_dir: Path) -> Path:
    """Fresh temp dir containing only the task's public files."""
    ws = Path(tempfile.mkdtemp(prefix=f"dagi_eval_{task_dir.name}_"))
    shutil.copytree(task_dir / "public", ws, dirs_exist_ok=True)
    return ws


def apply_canned_solver(workspace: Path, task_dir: Path, solver: str,
                        kind: str) -> None:
    """--solver gold|naive: run the pipeline with a canned solution (no LLM).

    coding/naive: leave the public copy untouched (expect speedup ~1.0).
    coding/gold:  overlay hidden/gold_solution.
    ds/naive:     run hidden/baseline.py in the workspace (expect ds_score ~1.0).
    ds/gold:      run hidden/gold_solution/solve.py in the workspace.
    """
    if kind == "coding":
        if solver == "gold":
            shutil.copytree(task_dir / "hidden" / "gold_solution", workspace,
                            dirs_exist_ok=True)
        return
    src = (task_dir / "hidden" / "gold_solution" / "solve.py" if solver == "gold"
           else task_dir / "hidden" / "baseline.py")
    shutil.copy(src, workspace / "solve.py")
    subprocess.run([sys.executable, "solve.py"], cwd=workspace, check=True,
                   timeout=900)


def git_commit_info() -> tuple[str, bool]:
    sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                         text=True, cwd=PKG_DIR).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"],
                                capture_output=True, text=True,
                                cwd=PKG_DIR).stdout.strip())
    return sha, dirty


def append_result(row: dict, path: Path) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def new_run_dir(runs_dir: Path = RUNS_DIR) -> Path:
    """Create and return a fresh <ts>_log/ folder (with code/ and sessions/
    subdirs already made) for one benchmark sweep. Timestamp is local time,
    filesystem-safe (no colons), collision-avoided by appending a numeric
    suffix in the unlikely event two sweeps start in the same second."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = runs_dir / f"{ts}_log"
    suffix = 1
    while run_dir.exists():
        suffix += 1
        run_dir = runs_dir / f"{ts}-{suffix}_log"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "sessions").mkdir()
    return run_dir


def save_task_code(workspace: Path, run_dir: Path, task_name: str) -> None:
    """Copy a task's final workspace (agent output or canned solution) into
    run_dir/code/<task_name>/, so the run folder is a self-contained record of
    exactly what was scored — independent of the %TEMP% workspace, which is
    discarded after the sweep."""
    dest = run_dir / "code" / task_name
    shutil.copytree(workspace, dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))


def run_agent_on_task(workspace: Path, instruction: str, model_id: str | None,
                      timeout_min: float, sessions_dir: Path, task_name: str = "",
                      verbose: bool = False) -> dict:
    """Run AgentLoop on the workspace under a wall-clock budget.

    Timeout works by raising BenchmarkTimeout from the on_iteration callback,
    which AgentLoop calls synchronously at the top of every iteration
    (agent/loop.py:381) — the loop aborts at the next iteration boundary.
    ask_user is auto-answered via the on_ask_user callback (runs are unattended).
    Tool calls and assistant messages are logged to stdout so a sweep can be
    watched live (see agent/log_callbacks.py).

    Session transcripts (SessionTracker's .jsonl) default to
    workspace/.dagi/logs — but the workspace is a %TEMP% dir that gets
    discarded, so we build the tracker ourselves pointed at
    sessions_dir/<task_name>/ (the caller's run_dir/sessions/, see
    new_run_dir()) and hand it to AgentLoop via the private _tracker=
    override, so transcripts persist alongside that sweep's result.jsonl.
    """
    from agent.config_loader import resolve_model_config
    from agent.loop import AgentLoop
    from agent.session import SessionTracker
    from agent.log_callbacks import build_cli_callbacks

    config = resolve_model_config(model_id, config_path=CONFIG_PATH)
    config.project_path = workspace

    # No worker_model/advanced_model configured yet (single tier for now), but
    # switch_model is still in config_dagi_eval.yaml's tools list, so it must
    # be registered — agent/tools.py only registers it when worker_config or
    # advanced_config is set. Point both at a standalone copy of the resolved
    # default config so switching tiers is a same-model no-op today, without
    # aliasing the live config object.
    if config.worker_config is None:
        config.worker_config = dataclasses.replace(
            config, worker_config=None, advanced_config=None)
    if config.advanced_config is None:
        config.advanced_config = dataclasses.replace(
            config, worker_config=None, advanced_config=None)

    tracker = SessionTracker(
        model=config.model, thread_id=config.thread_id,
        logs_dir=sessions_dir / (task_name or "unnamed"))

    deadline = time.monotonic() + timeout_min * 60

    def on_iteration(_i: int) -> None:
        if time.monotonic() > deadline:
            raise BenchmarkTimeout()

    callbacks = dataclasses.replace(
        build_cli_callbacks(verbose=verbose, prefix=task_name),
        on_iteration=on_iteration,
        on_ask_user=lambda question, options, timeout:
            "Proceed with your best judgment.",
    )
    loop = AgentLoop(config, callbacks=callbacks, _tracker=tracker)
    stats = {"timed_out": False, "error": None}
    t0 = time.monotonic()
    try:
        loop.run(instruction)
    except BenchmarkTimeout:
        stats["timed_out"] = True
    except Exception as exc:  # agent/API death: score whatever artifacts exist
        stats["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        loop.finish()
    stats["wall_time_s"] = round(time.monotonic() - t0, 1)

    nodes = [m for m in loop.tracker._messages if m.entity == "assistant"]
    stats["iterations"] = len(nodes)
    stats["tokens_in"] = sum(m.input_tokens or 0 for m in nodes)
    stats["tokens_out"] = sum(m.output_tokens or 0 for m in nodes)
    costs = [m.cost for m in nodes if m.cost]
    stats["cost_usd"] = round(sum(costs), 5) if costs else None
    return stats
