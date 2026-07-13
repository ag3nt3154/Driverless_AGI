"""Harness: workspace management, agent invocation, timeout, results append."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PKG_DIR = Path(__file__).parent
TASKS_DIR = PKG_DIR / "tasks"
RESULTS_PATH = PKG_DIR / "results.jsonl"
CONFIG_PATH = PKG_DIR / "config_dagi_eval.yaml"


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


def append_result(row: dict, path: Path = RESULTS_PATH) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def run_agent_on_task(workspace: Path, instruction: str, model_id: str | None,
                      timeout_min: float) -> dict:
    """Run AgentLoop on the workspace under a wall-clock budget.

    Timeout works by raising BenchmarkTimeout from the on_iteration callback,
    which AgentLoop calls synchronously at the top of every iteration
    (agent/loop.py:381) — the loop aborts at the next iteration boundary.
    ask_user is auto-answered via the on_ask_user callback (runs are unattended).
    """
    from agent.config_loader import resolve_model_config
    from agent.loop import AgentCallbacks, AgentLoop

    config = resolve_model_config(model_id, config_path=CONFIG_PATH)
    config.project_path = workspace

    deadline = time.monotonic() + timeout_min * 60

    def on_iteration(_i: int) -> None:
        if time.monotonic() > deadline:
            raise BenchmarkTimeout()

    callbacks = AgentCallbacks(
        on_iteration=on_iteration,
        on_ask_user=lambda question, options, timeout:
            "Proceed with your best judgment.",
    )
    loop = AgentLoop(config, callbacks=callbacks)
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
