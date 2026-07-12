"""DAGI eval benchmark CLI.

Usage:
    conda run -n dagi python -m benchmarks.dagi_eval.run --model <id> \
        [--label "note"] [--task <name> ...] [--timeout-min 20] \
        [--solver agent|gold|naive]

--solver gold|naive runs canned solutions instead of the agent (harness
self-test, no LLM tokens): naive must score ~1.0, gold must show real lift.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path

from benchmarks.dagi_eval import harness, scoring


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the DAGI eval benchmark")
    ap.add_argument("--model", default=None, help="model id from config_dagi_eval.yaml")
    ap.add_argument("--label", default="", help="free-text note stored in the row")
    ap.add_argument("--task", action="append", dest="tasks", metavar="NAME",
                    help="run only named task(s); default: all")
    ap.add_argument("--timeout-min", type=float, default=20.0,
                    help="wall-clock budget per task (agent solver)")
    ap.add_argument("--solver", choices=["agent", "gold", "naive"], default="agent")
    ap.add_argument("--tasks-dir", type=Path, default=harness.TASKS_DIR,
                    help=argparse.SUPPRESS)
    ap.add_argument("--results", type=Path, default=harness.RESULTS_PATH,
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    sha, dirty = harness.git_commit_info()
    row = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "dagi_git_commit": sha, "dirty_tree": dirty,
        "model": args.model, "solver": args.solver, "label": args.label,
        "coding_score": None, "coding_tasks": {},
        "ds_score": None, "ds_auc": None,
        # tokens_think is null: SessionTracker does not track reasoning tokens
        # separately (spec schema parity)
        "wall_time_s": 0.0, "tokens_in": 0, "tokens_think": None, "tokens_out": 0,
        "cost_usd": None, "iterations": 0, "timed_out": [], "errors": [],
    }

    speedups = []
    for task_dir in harness.discover_tasks(args.tasks_dir, args.tasks):
        name = task_dir.name
        meta = scoring.load_task_meta(task_dir)
        kind = meta["kind"]
        ws = harness.prepare_workspace(task_dir)
        print(f"[{name}] workspace: {ws}")

        if args.solver == "agent":
            stats = harness.run_agent_on_task(
                ws, meta["instruction"], args.model, args.timeout_min)
            row["wall_time_s"] = round(row["wall_time_s"] + stats["wall_time_s"], 1)
            row["tokens_in"] += stats["tokens_in"]
            row["tokens_out"] += stats["tokens_out"]
            row["iterations"] += stats["iterations"]
            if stats["cost_usd"]:
                row["cost_usd"] = round((row["cost_usd"] or 0) + stats["cost_usd"], 5)
            if stats["timed_out"]:
                row["timed_out"].append(name)
            if stats["error"]:
                row["errors"].append(f"{name} (agent): {stats['error']}")
        else:
            harness.apply_canned_solver(ws, task_dir, args.solver, kind)

        if kind == "coding":
            res = scoring.score_coding_task(task_dir, ws)
            row["coding_tasks"][name] = res
            speedups.append(res["speedup"])
            if res["error"]:
                row["errors"].append(f"{name}: {res['error']}")
            print(f"[{name}] correct={res['correct']} speedup={res['speedup']}")
        else:
            res = scoring.score_ds_task(task_dir, ws)
            row["ds_score"], row["ds_auc"] = res["ds_score"], res["auc"]
            if res["error"]:
                row["errors"].append(f"{name}: {res['error']}")
            print(f"[{name}] auc={res['auc']} ds_score={res['ds_score']}")

    if speedups:
        row["coding_score"] = round(sum(speedups) / len(speedups), 2)

    harness.append_result(row, args.results)
    summary = {k: row[k] for k in ("coding_score", "ds_score", "wall_time_s",
                                   "tokens_in", "tokens_out", "cost_usd",
                                   "timed_out", "errors")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
