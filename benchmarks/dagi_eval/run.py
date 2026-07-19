"""DAGI eval benchmark CLI.

Usage:
    conda run -n dagi python -m benchmarks.dagi_eval.run --model <id> \
        [--label "note"] [--task <name> ...] [--timeout-min 20] \
        [--solver agent|gold|naive]

--solver gold|naive runs canned solutions instead of the agent (harness
self-test, no LLM tokens): naive must score ~1.0, gold must show real lift.

Every invocation creates its own timestamped run folder under
.dagi/benchmarks/dagi_eval/logs/<ts>_log/ (see harness.new_run_dir()):
  result.jsonl        one row per task, plus a final "__aggregate__" row
  code/<task_name>/   copy of that task's final workspace (agent output or
                       canned solution) as actually scored
  sessions/<task_name>/session_*.jsonl   SessionTracker transcripts (agent
                       solver only)

Each task row always carries baseline_score and golden_score (from the
canned naive/gold solutions, scored fresh — no LLM tokens involved) alongside
recorded_score (this row's actual --solver result), so unified_score has a
grounded reference on every run regardless of which solver was requested.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.dagi_eval import harness, scoring

load_dotenv()  # populate os.environ from .env before config_loader reads API keys


def _new_row(task_dir: Path, args: argparse.Namespace, run_dir: Path,
            sha: str, dirty: bool) -> dict:
    return {
        "run_id": run_dir.name,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "task": task_dir.name, "kind": None,
        "dagi_git_commit": sha, "dirty_tree": dirty,
        "model": args.model, "solver": args.solver, "label": args.label,
        "baseline_score": None, "golden_score": None, "recorded_score": None,
        "correct": None, "auc": None,
        "normalized_perf": None, "normalized_tokens": None, "unified_score": None,
        # tokens_think is null: SessionTracker does not track reasoning tokens
        # separately (spec schema parity)
        "wall_time_s": 0.0, "tokens_in": 0, "tokens_think": None, "tokens_out": 0,
        "cost_usd": None, "iterations": 0, "timed_out": False, "error": None,
    }


def _add_error(row: dict, msg: str) -> None:
    row["error"] = f'{row["error"]}; {msg}' if row["error"] else msg


def build_task_row(task_dir: Path, args: argparse.Namespace, run_dir: Path,
                   sha: str, dirty: bool) -> dict:
    """Run and score a single task, returning its result.jsonl row.

    Always scores the canned baseline and gold solutions fresh (cheap, no
    LLM — see scoring.score_reference) in addition to this run's chosen
    --solver, so unified_score always has a grounded (baseline, gold)
    reference pair regardless of which solver produced recorded_score. Any
    exception is caught and recorded in row["error"] so one bad task can't
    abort the whole sweep.
    """
    name = task_dir.name
    row = _new_row(task_dir, args, run_dir, sha, dirty)
    try:
        meta = scoring.load_task_meta(task_dir)
        kind = row["kind"] = meta["kind"]

        base_ref = scoring.score_reference(task_dir, kind, "naive")
        gold_ref = scoring.score_reference(task_dir, kind, "gold")
        row["baseline_score"] = None if base_ref["error"] else base_ref["score"]
        row["golden_score"] = None if gold_ref["error"] else gold_ref["score"]
        if base_ref["error"]:
            _add_error(row, f"baseline reference: {base_ref['error']}")
        if gold_ref["error"]:
            _add_error(row, f"gold reference: {gold_ref['error']}")

        ws = harness.prepare_workspace(task_dir)
        print(f"[{name}] workspace: {ws}")

        if args.solver == "agent":
            stats = harness.run_agent_on_task(
                ws, meta["instruction"], args.model, args.timeout_min,
                run_dir / "sessions", task_name=name, verbose=args.verbose)
            row["wall_time_s"] = stats["wall_time_s"]
            row["tokens_in"] = stats["tokens_in"]
            row["tokens_out"] = stats["tokens_out"]
            row["iterations"] = stats["iterations"]
            row["cost_usd"] = stats["cost_usd"]
            row["timed_out"] = stats["timed_out"]
            if stats["error"]:
                _add_error(row, f"agent: {stats['error']}")
        else:
            harness.apply_canned_solver(ws, task_dir, args.solver, kind)

        harness.save_task_code(ws, run_dir, name)

        if kind == "coding":
            res = scoring.score_coding_task(task_dir, ws)
            row["recorded_score"] = res["speedup"]
            row["correct"] = res["correct"]
            if res["error"]:
                _add_error(row, res["error"])
            print(f"[{name}] correct={res['correct']} speedup={res['speedup']}"
                 + (f" error={res['error']}" if res["error"] else ""))
        else:
            res = scoring.score_ds_task(task_dir, ws)
            row["recorded_score"] = res["ds_score"]
            row["auc"] = res["auc"]
            if res["error"]:
                _add_error(row, res["error"])
            print(f"[{name}] auc={res['auc']} ds_score={res['ds_score']}")

        row["normalized_perf"] = scoring.normalize_perf(
            row["recorded_score"], row["baseline_score"], row["golden_score"])
        row["normalized_tokens"] = scoring.normalize_tokens(
            row["tokens_in"] + row["tokens_out"])
        row["unified_score"] = scoring.unified_score(
            row["normalized_perf"], row["normalized_tokens"])
    except Exception as exc:  # noqa: BLE001 - keep the sweep alive
        _add_error(row, f"unhandled {type(exc).__name__}: {exc}")
        print(f"[{name}] ERROR: unhandled {type(exc).__name__}: {exc}")
    return row


def aggregate_row(rows: list[dict], run_dir: Path, sha: str, dirty: bool,
                  args: argparse.Namespace) -> dict:
    """Final "__aggregate__" row: sweep-wide totals and mean scores."""
    speedups = [r["recorded_score"] for r in rows
               if r["kind"] == "coding" and r["recorded_score"] is not None]
    ds_scores = [r["recorded_score"] for r in rows
                if r["kind"] == "ds" and r["recorded_score"] is not None]
    unified = [r["unified_score"] for r in rows if r["unified_score"] is not None]
    costs = [r["cost_usd"] for r in rows if r["cost_usd"]]
    return {
        "run_id": run_dir.name, "task": "__aggregate__",
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "dagi_git_commit": sha, "dirty_tree": dirty,
        "model": args.model, "solver": args.solver, "label": args.label,
        "coding_score": round(sum(speedups) / len(speedups), 2) if speedups else None,
        "ds_score": round(sum(ds_scores) / len(ds_scores), 3) if ds_scores else None,
        "unified_score": round(sum(unified) / len(unified), 4) if unified else None,
        "wall_time_s": round(sum(r["wall_time_s"] for r in rows), 1),
        "tokens_in": sum(r["tokens_in"] for r in rows),
        "tokens_think": None,
        "tokens_out": sum(r["tokens_out"] for r in rows),
        "cost_usd": round(sum(costs), 5) if costs else None,
        "iterations": sum(r["iterations"] for r in rows),
        "timed_out": [r["task"] for r in rows if r["timed_out"]],
        "errors": [f'{r["task"]}: {r["error"]}' for r in rows if r["error"]],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the DAGI eval benchmark")
    ap.add_argument("--model", default=None, help="model id from config_dagi_eval.yaml")
    ap.add_argument("--label", default="", help="free-text note stored in each row")
    ap.add_argument("--task", action="append", dest="tasks", metavar="NAME",
                    help="run only named task(s); default: all")
    ap.add_argument("--timeout-min", type=float, default=20.0,
                    help="wall-clock budget per task (agent solver)")
    ap.add_argument("--solver", choices=["agent", "gold", "naive"], default="agent")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="log full tool args/output and reasoning per task")
    ap.add_argument("--tasks-dir", type=Path, default=harness.TASKS_DIR,
                    help=argparse.SUPPRESS)
    ap.add_argument("--runs-dir", type=Path, default=harness.RUNS_DIR,
                    help=argparse.SUPPRESS)
    args = ap.parse_args()

    logging.basicConfig(format="%(asctime)s %(message)s", level=logging.INFO, datefmt="%H:%M:%S")

    sha, dirty = harness.git_commit_info()
    run_dir = harness.new_run_dir(args.runs_dir)
    results_path = run_dir / "result.jsonl"
    print(f"run dir: {run_dir}")

    rows = []
    for task_dir in harness.discover_tasks(args.tasks_dir, args.tasks):
        row = build_task_row(task_dir, args, run_dir, sha, dirty)
        harness.append_result(row, results_path)
        rows.append(row)

    agg = aggregate_row(rows, run_dir, sha, dirty, args)
    harness.append_result(agg, results_path)

    summary = {k: agg[k] for k in ("coding_score", "ds_score", "unified_score",
                                   "wall_time_s", "tokens_in", "tokens_out",
                                   "cost_usd", "timed_out", "errors")}
    print(json.dumps(summary, indent=2))
    print(f"results: {results_path}")


if __name__ == "__main__":
    main()
