"""Scoring for the dagi eval benchmark: correctness gate, timing, DS metric.

All agent code executes in fresh subprocesses via _exec_entry.py (crash/hang
isolation, scratch cwd so solutions can't read files they stashed at agent time).
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

PKG_DIR = Path(__file__).parent
EXEC_ENTRY = PKG_DIR / "_exec_entry.py"

TIMING_RUNS = 5
AGENT_CALL_TIMEOUT_S = 120    # per spec: per-call cap for agent solutions
BASELINE_CALL_TIMEOUT_S = 300  # baselines are slow by design — generous cap


def load_task_meta(task_dir: Path) -> dict:
    return yaml.safe_load((task_dir / "task.yaml").read_text(encoding="utf-8"))


def outputs_match(a, b, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    """Recursive equality with float tolerance. Int/float compare numerically;
    everything else requires identical types and shapes."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=rel_tol, abs_tol=abs_tol)
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(outputs_match(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(outputs_match(x, y) for x, y in zip(a, b))
    return a == b


def run_entry(code_dir: Path, module: str, func: str, input_dir: Path, *,
              timing_runs: int = 0,
              per_call_timeout_s: int = AGENT_CALL_TIMEOUT_S) -> dict:
    """Run <module>:<func>(input_dir) from code_dir in an isolated subprocess."""
    scratch = Path(tempfile.mkdtemp(prefix="dagi_eval_exec_"))
    out_json = scratch / "out.json"
    cmd = [sys.executable, str(EXEC_ENTRY), str(code_dir), module, func,
           str(input_dir), str(out_json)]
    if timing_runs:
        cmd += ["--timing", str(timing_runs)]
    total_timeout = (timing_runs + 1) * per_call_timeout_s + 30
    try:
        proc = subprocess.run(cmd, cwd=scratch, capture_output=True, text=True,
                              timeout=total_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timed out after {total_timeout}s"}
    if not out_json.exists():
        return {"ok": False,
                "error": f"no output written; stderr: {(proc.stderr or '')[-1000:]}"}
    return json.loads(out_json.read_text(encoding="utf-8"))


def score_coding_task(task_dir: Path, workspace: Path) -> dict:
    """Correctness gate on hidden cases, then speedup vs fresh-timed baseline."""
    meta = load_task_meta(task_dir)
    module, func = meta["entry_module"], meta["entry_func"]
    data = task_dir / "hidden" / "data"
    baseline = task_dir / "hidden" / "baseline"
    result = {"speedup": 0.0, "correct": False, "error": None,
              "agent_time_s": None, "baseline_time_s": None}

    if not data.exists():
        result["error"] = (f"hidden data missing — run: conda run -n dagi python "
                           f"{task_dir / 'hidden' / 'make_inputs.py'}")
        return result

    # ── Correctness gate ─────────────────────────────────────────────────
    for case_dir in sorted((data / "correctness").iterdir()):
        expected = json.loads(
            (data / "expected" / f"{case_dir.name}.json").read_text(encoding="utf-8"))
        actual = run_entry(workspace, module, func, case_dir)
        if not actual.get("ok"):
            result["error"] = f"correctness {case_dir.name}: {actual.get('error')}"
            return result
        if not outputs_match(expected, actual["result"]):
            result["error"] = f"correctness {case_dir.name}: output mismatch"
            return result
    result["correct"] = True

    # ── Timing (baseline timed fresh each session on this machine) ──────
    timing_dir = data / "timing"
    base = run_entry(baseline, module, func, timing_dir, timing_runs=TIMING_RUNS,
                     per_call_timeout_s=BASELINE_CALL_TIMEOUT_S)
    if not base.get("ok"):
        result["error"] = f"baseline timing failed: {base.get('error')}"
        return result
    agent = run_entry(workspace, module, func, timing_dir, timing_runs=TIMING_RUNS)
    if not agent.get("ok"):
        result["error"] = f"agent timing failed: {agent.get('error')}"
        return result
    if not outputs_match(base["result"], agent["result"]):
        result["correct"] = False
        result["error"] = "timing input: output mismatch vs baseline"
        return result

    bt = statistics.median(base["times"])
    at = statistics.median(agent["times"])
    result["baseline_time_s"] = round(bt, 3)
    result["agent_time_s"] = round(at, 3)
    result["speedup"] = round(bt / at, 2) if at > 0 else 0.0
    return result


def roc_auc(y_true, scores) -> float:
    """Tie-averaged rank AUC (Mann-Whitney)."""
    import numpy as np

    y = np.asarray(list(y_true), dtype=int)
    s = np.asarray(list(scores), dtype=float)
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("labels are degenerate (single class)")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    ranks[order] = np.arange(1, len(s) + 1)
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def score_ds_task(task_dir: Path, workspace: Path) -> dict:
    """Validate predictions.csv, compute held-out AUC, normalize vs baseline."""
    result = {"ds_score": 0.0, "auc": None, "error": None}
    meta = json.loads(
        (task_dir / "hidden" / "meta.json").read_text(encoding="utf-8"))

    labels: dict[str, int] = {}
    with open(task_dir / "hidden" / "test_labels.csv", newline="",
              encoding="utf-8") as f:
        for row in csv.DictReader(f):
            labels[row["id"]] = int(row["label"])

    preds_path = workspace / "predictions.csv"
    if not preds_path.exists():
        result["error"] = "predictions.csv not found in workspace"
        return result
    preds: dict[str, float] = {}
    try:
        with open(preds_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not {"id", "probability"} <= set(reader.fieldnames):
                result["error"] = "predictions.csv must have columns: id, probability"
                return result
            for row in reader:
                p = float(row["probability"])
                if not math.isfinite(p):
                    raise ValueError(f"non-finite probability for id {row['id']}")
                preds[row["id"]] = p
    except (ValueError, KeyError) as exc:
        result["error"] = f"malformed predictions.csv: {exc}"
        return result

    if set(preds) != set(labels):
        result["error"] = (f"prediction ids mismatch: expected {len(labels)} rows, "
                           f"got {len(preds)} with {len(set(preds) & set(labels))} matching")
        return result

    ids = sorted(labels)
    auc = roc_auc([labels[i] for i in ids], [preds[i] for i in ids])
    result["auc"] = round(auc, 4)
    result["ds_score"] = round((auc - 0.5) / (meta["baseline_auc"] - 0.5), 3)
    return result
