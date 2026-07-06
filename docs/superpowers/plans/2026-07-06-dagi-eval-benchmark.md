# DAGI Eval Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-contained benchmark harness (`benchmarks/dagi_eval/`) that runs any (dagi version × model) combo against 5 coding-optimization tasks + 1 data-science task and appends a scorecard row (scores vs wall time vs token cost) to `results.jsonl`.

**Architecture:** Standalone in-process harness driving `AgentLoop` directly (same pattern as `benchmarks/harbor/agent.py`, no Docker). Each task ships `public/` (copied into a fresh temp workspace the agent works in) and `hidden/` (pristine baseline, gold solution, seeded input generator — never exposed to the agent). Scoring runs in fresh subprocesses. Spec: `docs/superpowers/specs/2026-07-06-dagi-eval-benchmark-design.md`.

**Tech Stack:** Python 3.11+ (conda env `dagi`), pytest, numpy/pandas/scipy/scikit-learn for task content, existing `agent.loop.AgentLoop` / `agent.config_loader.resolve_model_config`.

**Key API facts (verified against the codebase):**
- `resolve_model_config(model_id, config_path=Path) -> AgentConfig` — reads a dedicated YAML; `tools:` list in the YAML restricts registered tools.
- `AgentConfig` has **no** `max_iterations` field (the loop is unbounded) — the harness wall-clock timeout is the only budget. `max_continuations` exists.
- `AgentLoop(config, callbacks=AgentCallbacks(...))`; `callbacks.on_iteration(i)` is called synchronously at the top of each iteration — **raising an exception there aborts the loop** (our timeout mechanism). `callbacks.on_ask_user` is a callback (no tool stub needed).
- Token stats: `loop.tracker._messages` nodes with `entity == "assistant"` carry `input_tokens`, `output_tokens`, `cost` (pattern from `benchmarks/harbor/agent.py:_populate_context`).
- All commands run via `conda run -n dagi python ...`.

**Run every pytest command as:** `conda run -n dagi python -m pytest <path> -q`

---

## File Structure

```
benchmarks/dagi_eval/
├── __init__.py
├── run.py                    # CLI entry (argparse)
├── harness.py                # workspace mgmt, agent invocation, timeout, results append
├── scoring.py                # subprocess eval: correctness gate, timing, DS metric
├── _exec_entry.py            # subprocess script: run <module>:<func>(input_dir) isolated
├── _genutil.py               # shared: write expected outputs from baseline
├── config_dagi_eval.yaml     # benchmark model catalog + tool list (committed)
├── results.jsonl             # append-only scorecard history (committed, created on first run)
└── tasks/
    ├── coding_01_logpipe/    # task.yaml, public/{spec.md,pipeline.py},
    │                         # hidden/{baseline/pipeline.py, gold_solution/pipeline.py,
    │                         #         make_inputs.py, data/ (generated, gitignored)}
    ├── coding_02_querymini/  # same shape, entry module engine.py
    ├── coding_03_simgrid/    # same shape, entry module sim.py
    ├── coding_04_dedup/      # same shape, entry module dedup.py
    ├── coding_05_sheetcalc/  # same shape, entry module sheet.py
    └── ds_01_tabular/
        ├── task.yaml
        ├── generator.py                  # seeded; run once, outputs committed
        ├── public/{spec.md, train.csv, test_features.csv}
        └── hidden/{test_labels.csv, meta.json, baseline.py, gold_solution/solve.py}
tests/dagi_eval/
├── __init__.py
├── test_exec_entry.py
├── test_scoring.py
├── test_harness.py
└── fixture_task/             # tiny toy task for harness/CLI tests (no LLM)
```

**Uniform coding-task contract:** each task's `task.yaml` names an `entry_module` / `entry_func`; the function signature is always `run(input_dir: str) -> dict` (JSON-serializable). Correctness = agent output matches stored expected outputs (from the pristine baseline) on hidden cases, floats at rel_tol 1e-6. Timing = median of 5 runs after 1 warmup, in a subprocess; baseline (pristine `hidden/baseline/`) timed fresh in the same session. Score = `baseline_median / agent_median`.

---

### Task 1: Package skeleton + subprocess entry executor

**Files:**
- Create: `benchmarks/dagi_eval/__init__.py` (empty)
- Create: `benchmarks/dagi_eval/_exec_entry.py`
- Create: `tests/dagi_eval/__init__.py` (empty)
- Create: `tests/dagi_eval/test_exec_entry.py`
- Modify: `.gitignore` (append one line)

- [ ] **Step 1: Create empty package init files and gitignore entry**

Create `benchmarks/dagi_eval/__init__.py` and `tests/dagi_eval/__init__.py` (both empty). Append to `.gitignore`:

```
benchmarks/dagi_eval/tasks/*/hidden/data/
```

- [ ] **Step 2: Write the failing tests**

Create `tests/dagi_eval/test_exec_entry.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

EXEC_ENTRY = Path(__file__).resolve().parents[2] / "benchmarks" / "dagi_eval" / "_exec_entry.py"


def _run(code_dir, module, func, input_dir, out_json, extra=()):
    cmd = [sys.executable, str(EXEC_ENTRY), str(code_dir), module, func,
           str(input_dir), str(out_json), *extra]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return json.loads(Path(out_json).read_text(encoding="utf-8"))


def test_runs_entry_and_writes_result(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    return {'n': 2, 'dir': True}\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json")
    assert payload == {"ok": True, "result": {"n": 2, "dir": True}}


def test_timing_mode_reports_times(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    return {'n': 1}\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json", ("--timing", "3"))
    assert payload["ok"] is True
    assert len(payload["times"]) == 3
    assert all(t >= 0 for t in payload["times"])


def test_crashing_module_reports_error(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "m.py").write_text(
        "def run(input_dir):\n    raise ValueError('boom')\n", encoding="utf-8")
    payload = _run(ws, "m", "run", tmp_path, tmp_path / "out.json")
    assert payload["ok"] is False
    assert "boom" in payload["error"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_exec_entry.py -q`
Expected: 3 failures (file `_exec_entry.py` produces no output / FileNotFoundError).

- [ ] **Step 4: Implement `_exec_entry.py`**

```python
"""Subprocess entry executor for the dagi eval benchmark.

Usage:
    python _exec_entry.py <code_dir> <module> <func> <input_dir> <out_json> [--timing N]

Imports <module> from <code_dir>, calls <func>(input_dir), writes JSON to <out_json>:
    {"ok": true, "result": ...}                      (normal mode)
    {"ok": true, "result": ..., "times": [...]}      (timing: 1 warmup + N timed calls)
    {"ok": false, "error": "<traceback tail>"}       (any exception)

Runs as a plain script (not -m) so the parent can set cwd to a scratch dir.
"""
import importlib
import json
import sys
import time
import traceback


def main() -> None:
    code_dir, module_name, func_name, input_dir, out_json = sys.argv[1:6]
    timing_runs = 0
    if "--timing" in sys.argv:
        timing_runs = int(sys.argv[sys.argv.index("--timing") + 1])

    sys.path.insert(0, code_dir)
    try:
        mod = importlib.import_module(module_name)
        func = getattr(mod, func_name)
        if timing_runs:
            func(input_dir)  # warmup
            times, result = [], None
            for _ in range(timing_runs):
                t0 = time.perf_counter()
                result = func(input_dir)
                times.append(time.perf_counter() - t0)
            payload = {"ok": True, "result": result, "times": times}
        else:
            payload = {"ok": True, "result": func(input_dir)}
    except BaseException:
        payload = {"ok": False, "error": traceback.format_exc()[-2000:]}

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_exec_entry.py -q`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add benchmarks/dagi_eval tests/dagi_eval .gitignore
git commit -m "feat(dagi_eval): package skeleton + subprocess entry executor"
```

---

### Task 2: scoring.py — output compare, timing protocol, DS metric

**Files:**
- Create: `benchmarks/dagi_eval/scoring.py`
- Create: `tests/dagi_eval/test_scoring.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/dagi_eval/test_scoring.py`:

```python
import json

import pytest

from benchmarks.dagi_eval import scoring


# ── outputs_match ────────────────────────────────────────────────────────
def test_outputs_match_exact_and_nested():
    a = {"x": [1, "s", {"y": 2}], "z": None}
    assert scoring.outputs_match(a, json.loads(json.dumps(a)))


def test_outputs_match_float_tolerance():
    assert scoring.outputs_match({"v": 1.0000000001}, {"v": 1.0})
    assert not scoring.outputs_match({"v": 1.01}, {"v": 1.0})


def test_outputs_match_type_and_shape_mismatches():
    assert not scoring.outputs_match([1, 2], [1, 2, 3])
    assert not scoring.outputs_match({"a": 1}, {"b": 1})
    assert not scoring.outputs_match("1", 1)
    assert not scoring.outputs_match(1.0, "1.0")


def test_outputs_match_int_float_close():
    assert scoring.outputs_match(2, 2.0)


# ── roc_auc ──────────────────────────────────────────────────────────────
def test_roc_auc_perfect_and_reversed():
    y = [0, 0, 1, 1]
    assert scoring.roc_auc(y, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert scoring.roc_auc(y, [0.9, 0.8, 0.2, 0.1]) == pytest.approx(0.0)


def test_roc_auc_ties_average():
    assert scoring.roc_auc([0, 1], [0.5, 0.5]) == pytest.approx(0.5)


def test_roc_auc_known_value():
    # pairs: (0.4>0.3)=1, (0.4>0.5)=0, (0.6>0.3)=1, (0.6>0.5)=1 -> 3/4
    assert scoring.roc_auc([0, 0, 1, 1], [0.3, 0.5, 0.4, 0.6]) == pytest.approx(0.75)


def test_roc_auc_degenerate_raises():
    with pytest.raises(ValueError):
        scoring.roc_auc([1, 1], [0.1, 0.2])


# ── score_ds_task validation ────────────────────────────────────────────
def _make_ds_task(tmp_path, labels_rows, meta=None):
    task = tmp_path / "ds_task"
    (task / "hidden").mkdir(parents=True)
    (task / "hidden" / "test_labels.csv").write_text(
        "id,label\n" + "\n".join(labels_rows) + "\n", encoding="utf-8")
    (task / "hidden" / "meta.json").write_text(
        json.dumps(meta or {"baseline_auc": 0.7, "oracle_auc": 0.9}), encoding="utf-8")
    return task


def test_score_ds_missing_predictions(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert "not found" in res["error"]


def test_score_ds_wrong_ids(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,0.2\n99,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert res["error"] is not None


def test_score_ds_non_numeric(tmp_path):
    task = _make_ds_task(tmp_path, ["1,0", "2,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,abc\n2,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["ds_score"] == 0.0
    assert res["error"] is not None


def test_score_ds_happy_path(tmp_path):
    # perfect ranking -> auc 1.0 -> ds_score (1.0-0.5)/(0.7-0.5) = 2.5
    task = _make_ds_task(tmp_path, ["1,0", "2,1", "3,0", "4,1"])
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "predictions.csv").write_text(
        "id,probability\n1,0.1\n2,0.9\n3,0.2\n4,0.8\n", encoding="utf-8")
    res = scoring.score_ds_task(task, ws)
    assert res["error"] is None
    assert res["auc"] == pytest.approx(1.0)
    assert res["ds_score"] == pytest.approx(2.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_scoring.py -q`
Expected: ImportError / all fail (module doesn't exist).

- [ ] **Step 3: Implement `scoring.py`**

```python
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


def run_entry(code_dir: Path, module: str, func: str, input_dir: Path,
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
    """Tie-averaged rank AUC (Mann–Whitney)."""
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_scoring.py -q`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add benchmarks/dagi_eval/scoring.py tests/dagi_eval/test_scoring.py
git commit -m "feat(dagi_eval): scoring — output compare, timing protocol, DS metric"
```

---

### Task 3: harness.py + test fixture task

**Files:**
- Create: `benchmarks/dagi_eval/harness.py`
- Create: `benchmarks/dagi_eval/_genutil.py`
- Create: `tests/dagi_eval/fixture_task/` (task.yaml, public/, hidden/)
- Create: `tests/dagi_eval/test_harness.py`

- [ ] **Step 1: Create the fixture task**

`tests/dagi_eval/fixture_task/task.yaml`:

```yaml
kind: coding
entry_module: pipeline
entry_func: run
gold_min_speedup: 2.0
instruction: |
  Read spec.md in your working directory and optimize pipeline.py for speed
  while preserving exact outputs.
```

`tests/dagi_eval/fixture_task/public/spec.md`:

```markdown
# Fixture task
`pipeline.run(input_dir)` sums `numbers.json`. Keep outputs identical; make it fast.
```

`tests/dagi_eval/fixture_task/public/pipeline.py`:

```python
import json
from pathlib import Path


def run(input_dir):
    numbers = json.loads(Path(input_dir, "numbers.json").read_text(encoding="utf-8"))
    total = 0
    for n in numbers:
        for _ in range(2000):  # deliberate busywork
            pass
        total += n
    return {"total": total, "count": len(numbers)}
```

`tests/dagi_eval/fixture_task/hidden/baseline/pipeline.py`: **exact copy** of the public file above.

`tests/dagi_eval/fixture_task/hidden/gold_solution/pipeline.py`:

```python
import json
from pathlib import Path


def run(input_dir):
    numbers = json.loads(Path(input_dir, "numbers.json").read_text(encoding="utf-8"))
    return {"total": sum(numbers), "count": len(numbers)}
```

`tests/dagi_eval/fixture_task/hidden/make_inputs.py`:

```python
"""Generate fixture data: 2 correctness cases + 1 timing input + expected outputs."""
import json
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[2]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402


def main() -> None:
    data = TASK_DIR / "hidden" / "data"
    for name, numbers in [("case_01_empty", []), ("case_02_small", [1, 2, 3])]:
        d = data / "correctness" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "numbers.json").write_text(json.dumps(numbers), encoding="utf-8")
    t = data / "timing"
    t.mkdir(parents=True, exist_ok=True)
    (t / "numbers.json").write_text(json.dumps(list(range(3000))), encoding="utf-8")
    write_expected(TASK_DIR)
    print("fixture data written")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Implement `_genutil.py`**

```python
"""Shared generator helper: store baseline outputs for correctness cases."""
from __future__ import annotations

import json
from pathlib import Path

from benchmarks.dagi_eval import scoring


def write_expected(task_dir: Path) -> None:
    """Run the pristine baseline on every hidden correctness case and store
    the outputs as hidden/data/expected/<case>.json."""
    meta = scoring.load_task_meta(task_dir)
    data = task_dir / "hidden" / "data"
    exp_dir = data / "expected"
    exp_dir.mkdir(parents=True, exist_ok=True)
    for case in sorted((data / "correctness").iterdir()):
        payload = scoring.run_entry(
            task_dir / "hidden" / "baseline", meta["entry_module"],
            meta["entry_func"], case,
            per_call_timeout_s=scoring.BASELINE_CALL_TIMEOUT_S)
        if not payload.get("ok"):
            raise SystemExit(f"{case.name}: baseline failed: {payload.get('error')}")
        (exp_dir / f"{case.name}.json").write_text(
            json.dumps(payload["result"]), encoding="utf-8")
```

- [ ] **Step 3: Write the failing tests**

Create `tests/dagi_eval/test_harness.py`:

```python
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.dagi_eval import harness, scoring

FIXTURE = Path(__file__).parent / "fixture_task"
_TASKS_ROOT = Path(__file__).resolve().parents[2] / "benchmarks" / "dagi_eval" / "tasks"
REAL_TASKS = sorted(
    p for p in _TASKS_ROOT.glob("coding_*") if (p / "task.yaml").exists()
) if _TASKS_ROOT.exists() else []


@pytest.fixture(scope="module", autouse=True)
def fixture_data():
    subprocess.run([sys.executable, str(FIXTURE / "hidden" / "make_inputs.py")],
                   check=True, capture_output=True, timeout=300)


def test_prepare_workspace_copies_only_public(tmp_path):
    ws = harness.prepare_workspace(FIXTURE)
    assert (ws / "spec.md").exists()
    assert (ws / "pipeline.py").exists()
    assert not (ws / "hidden").exists()
    assert not (ws / "task.yaml").exists()


def test_naive_solver_scores_near_parity():
    ws = harness.prepare_workspace(FIXTURE)
    harness.apply_canned_solver(ws, FIXTURE, "naive", "coding")
    res = scoring.score_coding_task(FIXTURE, ws)
    assert res["error"] is None
    assert res["correct"] is True
    assert 0.3 <= res["speedup"] <= 3.0  # same code, timing noise only


def test_gold_solver_correct_and_faster():
    ws = harness.prepare_workspace(FIXTURE)
    harness.apply_canned_solver(ws, FIXTURE, "gold", "coding")
    res = scoring.score_coding_task(FIXTURE, ws)
    assert res["error"] is None
    assert res["correct"] is True
    assert res["speedup"] > 2.0


def test_broken_solution_scores_zero(tmp_path):
    ws = harness.prepare_workspace(FIXTURE)
    (ws / "pipeline.py").write_text("def run(input_dir):\n    return {'total': -1}\n",
                                    encoding="utf-8")
    res = scoring.score_coding_task(FIXTURE, ws)
    assert res["correct"] is False
    assert res["speedup"] == 0.0
    assert "mismatch" in res["error"]


def test_discover_tasks_rejects_unknown(tmp_path):
    (tmp_path / "t1").mkdir()
    (tmp_path / "t1" / "task.yaml").write_text("kind: coding\n", encoding="utf-8")
    assert [p.name for p in harness.discover_tasks(tmp_path)] == ["t1"]
    with pytest.raises(SystemExit):
        harness.discover_tasks(tmp_path, only=["nope"])


def test_append_result_and_git_info(tmp_path):
    out = tmp_path / "results.jsonl"
    harness.append_result({"a": 1}, out)
    harness.append_result({"b": 2}, out)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    sha, dirty = harness.git_commit_info()
    assert len(sha) == 40
    assert isinstance(dirty, bool)


@pytest.mark.parametrize("task_dir", REAL_TASKS, ids=lambda p: p.name)
def test_baseline_is_pristine_copy_of_public(task_dir):
    """Guards drift between the shipped slow code and the timing baseline."""
    meta = scoring.load_task_meta(task_dir)
    fname = meta["entry_module"] + ".py"
    pub = (task_dir / "public" / fname).read_text(encoding="utf-8")
    base = (task_dir / "hidden" / "baseline" / fname).read_text(encoding="utf-8")
    assert pub == base
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`
Expected: ImportError (harness module doesn't exist).

- [ ] **Step 5: Implement `harness.py`**

```python
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`
Expected: all passed (the `REAL_TASKS` parametrized test collects 0 items for now). Note: the fixture-data setup and timing tests take ~1–2 min.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/dagi_eval/harness.py benchmarks/dagi_eval/_genutil.py tests/dagi_eval
git commit -m "feat(dagi_eval): harness — workspace mgmt, canned solvers, agent runner"
```

---

### Task 4: run.py CLI + benchmark config

**Files:**
- Create: `benchmarks/dagi_eval/run.py`
- Create: `benchmarks/dagi_eval/config_dagi_eval.yaml`
- Modify: `tests/dagi_eval/test_harness.py` (add one e2e CLI test)

- [ ] **Step 1: Write the failing e2e test**

Append to `tests/dagi_eval/test_harness.py`:

```python
def test_cli_end_to_end_naive_on_fixture(tmp_path):
    results = tmp_path / "results.jsonl"
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, "-m", "benchmarks.dagi_eval.run",
         "--solver", "naive", "--task", "fixture_task",
         "--tasks-dir", str(FIXTURE.parent), "--results", str(results),
         "--label", "e2e-test"],
        capture_output=True, text=True, cwd=repo_root, timeout=600)
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(l) for l in results.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["solver"] == "naive"
    assert row["label"] == "e2e-test"
    assert row["coding_tasks"]["fixture_task"]["correct"] is True
    assert 0.3 <= row["coding_score"] <= 3.0
```

Also add `import json` at the top of the file if not present.

Note `--tasks-dir` points at `tests/dagi_eval/` — discovery picks up `fixture_task` because it contains a `task.yaml`.

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py::test_cli_end_to_end_naive_on_fixture -q`
Expected: FAIL (`No module named benchmarks.dagi_eval.run`).

- [ ] **Step 3: Write `config_dagi_eval.yaml`**

```yaml
# Benchmark config for the dagi eval harness (benchmarks/dagi_eval/run.py).
# Same schema as config.yaml; passed to resolve_model_config(config_path=...).
default_model: claude-sonnet-openrouter
max_continuations: 30
cache_prompt: true

# Only these tools are registered for benchmark runs. No ask_user (runs are
# unattended — the on_ask_user callback auto-answers anyway), no web tools
# (the tasks are self-contained), no plan mode.
tools:
  - read
  - write
  - edit
  - bash
  - grep
  - find
  - compact

system_prompt_preamble: |
  ## Benchmark Environment
  You are being evaluated in an unattended benchmark run. The task specification
  is in spec.md in your working directory — read it first. Work fully
  autonomously: never ask the user questions and never wait for confirmation.
  Your working directory contains everything you need; produce the required
  artifacts there. Python packages available: numpy, pandas, scipy, scikit-learn.
  Run python via: conda run -n dagi python <script>

models:
  claude-sonnet-openrouter:
    name: "Claude Sonnet (OpenRouter)"
    model: "anthropic/claude-sonnet-4-5"
    api_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
  deepseek-openrouter:
    name: "DeepSeek (OpenRouter)"
    model: "deepseek/deepseek-chat"
    api_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
```

- [ ] **Step 4: Implement `run.py`**

```python
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
```

- [ ] **Step 5: Run the full test file**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/ -q`
Expected: all passed (including the new e2e test).

- [ ] **Step 6: Verify required packages are in the dagi env**

Run: `conda run -n dagi python -c "import numpy, pandas, scipy, sklearn; print('ok')"`
If it fails: `conda run -n dagi pip install numpy pandas scipy scikit-learn` and re-run.

- [ ] **Step 7: Commit**

```bash
git add benchmarks/dagi_eval/run.py benchmarks/dagi_eval/config_dagi_eval.yaml tests/dagi_eval/test_harness.py
git commit -m "feat(dagi_eval): CLI runner + benchmark config"
```

---

## Coding task pattern (Tasks 5–9)

Every coding task follows the same steps. The self-test commands write to a **scratch results file** so calibration noise never lands in the committed `results.jsonl`:

```bash
# naive self-test (expected: correct=True, speedup in 0.3–3.0)
conda run -n dagi python -m benchmarks.dagi_eval.run --solver naive --task <name> --results "$TMP/selftest.jsonl"
# gold self-test (expected: correct=True, speedup >= gold_min_speedup from task.yaml)
conda run -n dagi python -m benchmarks.dagi_eval.run --solver gold --task <name> --results "$TMP/selftest.jsonl"
```

**Calibration rule (applies to every coding task):** after the naive self-test, check the printed `baseline_time_s` (also in the scratch results row). Target: **10–40 s**. If outside, adjust the size constants at the top of that task's `make_inputs.py` (roughly linearly, or quadratically where noted), delete `tasks/<name>/hidden/data/`, re-run `make_inputs.py`, and re-test. Record the final constants in the commit.

**Determinism rule:** all quantities that reach the output dict are either integers, exact-integer-valued floats (e.g. epoch seconds of whole-second timestamps, integer money amounts), or compared with rel_tol 1e-6 by `outputs_match` — gold solutions must never introduce a different rounding step than the naive code.

---

### Task 5: coding_01_logpipe

**Files:**
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/public/pipeline.py`
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/baseline/pipeline.py` (exact copy of public)
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/make_inputs.py`
- Create: `benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/gold_solution/pipeline.py`

- [ ] **Step 1: Write task.yaml, spec.md, and the naive pipeline**

`task.yaml`:

```yaml
kind: coding
entry_module: pipeline
entry_func: run
gold_min_speedup: 10.0
instruction: |
  Read spec.md in your working directory first. Optimize the log-analytics
  pipeline in pipeline.py for speed. The outputs of pipeline.run(input_dir)
  must remain exactly identical for any valid input — you will be scored on
  runtime speedup on hidden inputs, with correctness as a hard gate. Work
  autonomously; do not ask questions.
```

`public/spec.md`:

```markdown
# Task: optimize the log-analytics pipeline

`pipeline.py` implements a working but slow log-analytics pipeline. Your job is
to make `pipeline.run(input_dir)` as fast as possible **without changing its
output in any way**.

## Contract
- Entry point: `pipeline.run(input_dir: str) -> dict` must keep its exact
  signature and module name. Internal restructuring is freely allowed (helper
  modules, rewritten functions, different data structures).
- For any valid input directory the returned dict must be exactly identical to
  what the current implementation returns (floats within 1e-6 relative).
- Allowed: Python stdlib, numpy, pandas, scipy.

## Input format
`<input_dir>/logs/*.log` — pipe-delimited lines: `TIMESTAMP|USER|EVENT|PATH`
- TIMESTAMP: `YYYY-MM-DDTHH:MM:SS` (whole seconds)
- EVENT: one of view, cart, checkout, purchase, ping
- Lines may appear in any order across and within files. Blank and malformed
  lines are skipped.

## What it computes
1. Sessions: per user, events sorted by time split where the gap between
   consecutive events exceeds 1800 s (a gap of exactly 1800 s stays in the
   same session).
2. Funnel: for each stage (view, cart, checkout, purchase), the number of
   sessions containing at least one event of that stage.
3. `avg_session_len_s`: mean of (last event time − first event time) per
   session, rounded to 3 decimals.
4. `daily_active`: per calendar day (from the timestamp string), the number of
   distinct users with at least one event that day.

## Scoring
Hidden inputs of this same format (much larger). Score =
baseline_runtime / your_runtime. Correctness failure on any hidden case = 0.
```

`public/pipeline.py`:

```python
"""Log analytics pipeline: parse -> sessionize -> aggregate.

Contract (spec.md): run(input_dir) -> dict. Outputs must remain identical.
"""
import datetime
import re
from pathlib import Path

SESSION_GAP_S = 1800
FUNNEL = ["view", "cart", "checkout", "purchase"]


def _epoch(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").timestamp()


def parse_logs(input_dir):
    events = []
    for log_file in sorted(Path(input_dir, "logs").glob("*.log")):
        for line in log_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            pattern = re.compile(
                r"^(?P<ts>[^|]+)\|(?P<user>[^|]+)\|(?P<event>[^|]+)\|(?P<path>.*)$")
            m = pattern.match(line)
            if m is None:
                continue
            events.append({"ts": m.group("ts"), "user": m.group("user"),
                           "event": m.group("event"), "path": m.group("path")})
    return events


def sessionize(events):
    sessions = []
    for user in sorted({e["user"] for e in events}):
        mine = [e for e in events if e["user"] == user]
        mine = sorted(mine, key=lambda e: _epoch(e["ts"]))
        for e in mine:
            placed = False
            for s in sessions:
                if (s["user"] == user
                        and _epoch(e["ts"]) - _epoch(s["events"][-1]["ts"])
                        <= SESSION_GAP_S):
                    s["events"].append(e)
                    placed = True
                    break
            if not placed:
                sessions.append({"user": user, "events": [e]})
    return sessions


def aggregate(events, sessions):
    funnel = {}
    for stage in FUNNEL:
        count = 0
        for s in sessions:
            for e in s["events"]:
                if e["event"] == stage:
                    count += 1
                    break
        funnel[stage] = count
    daily = {}
    for day in sorted({e["ts"][:10] for e in events}):
        daily[day] = len({e["user"] for e in events if e["ts"][:10] == day})
    total = 0.0
    for s in sessions:
        total += _epoch(s["events"][-1]["ts"]) - _epoch(s["events"][0]["ts"])
    avg = total / len(sessions) if sessions else 0.0
    return {"sessions": len(sessions), "funnel": funnel,
            "avg_session_len_s": round(avg, 3), "daily_active": daily}


def run(input_dir):
    events = parse_logs(input_dir)
    sessions = sessionize(events)
    return aggregate(events, sessions)
```

Layered bottlenecks (for the plan reader, not the spec): per-line regex compile;
`strptime` re-parse everywhere; per-user full event scans; per-event scan of the
global session list; per-stage session rescans; per-day full event scans.

- [ ] **Step 2: Copy pristine baseline**

```bash
mkdir -p benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/baseline
cp benchmarks/dagi_eval/tasks/coding_01_logpipe/public/pipeline.py \
   benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/baseline/pipeline.py
```

- [ ] **Step 3: Write and run make_inputs.py**

`hidden/make_inputs.py`:

```python
"""Generate hidden inputs for coding_01_logpipe. Seeded — deterministic."""
import datetime
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 101
# Calibration knobs — naive timing target 10-40 s. Cost is roughly quadratic
# in total event count (global session-list scan).
N_USERS = 300
EVENTS_PER_USER = 150

EVENTS = ["view", "cart", "checkout", "purchase", "ping"]
BASE_EPOCH = int(datetime.datetime(2026, 1, 1, 0, 0, 0).timestamp())


def _fmt(epoch):
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%S")


def _write_log(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _gen_lines(rng, n_users, events_per_user):
    lines = []
    for u in range(n_users):
        user = f"user{u:05d}"
        t = BASE_EPOCH + rng.randint(0, 86400 * 30)
        made = 0
        while made < events_per_user:
            burst = min(rng.randint(3, 8), events_per_user - made)
            for _ in range(burst):
                t += rng.randint(1, 600)
                lines.append(
                    f"{_fmt(t)}|{user}|{rng.choice(EVENTS)}|/p/{rng.randint(1, 50)}")
                made += 1
            t += rng.randint(3600, 86400)  # gap > 1800 s -> new session
    rng.shuffle(lines)
    return lines


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    _write_log(cor / "case_01_empty" / "logs" / "a.log", [])
    _write_log(cor / "case_02_single" / "logs" / "a.log", [
        "2026-01-01T10:00:00|alice|view|/p/1",
        "2026-01-01T10:10:00|alice|purchase|/p/1",
    ])
    # exactly 1800 s -> same session; the third event starts a new session
    _write_log(cor / "case_03_gap_boundary" / "logs" / "a.log", [
        "2026-01-01T10:00:00|bob|view|/p/1",
        "2026-01-01T10:30:00|bob|cart|/p/1",
        "2026-01-01T11:00:01|bob|view|/p/2",
    ])
    _write_log(cor / "case_04_unsorted" / "logs" / "a.log",
               _gen_lines(random.Random(SEED + 1), 5, 20))
    multi = _gen_lines(random.Random(SEED + 2), 8, 25)
    _write_log(cor / "case_05_multifile" / "logs" / "a.log",
               multi[: len(multi) // 2])
    _write_log(cor / "case_05_multifile" / "logs" / "b.log",
               multi[len(multi) // 2:])
    _write_log(cor / "case_06_medium" / "logs" / "a.log",
               _gen_lines(random.Random(SEED + 3), 40, 60))

    timing_lines = _gen_lines(random.Random(SEED), N_USERS, EVENTS_PER_USER)
    n = len(timing_lines) // 3
    _write_log(data / "timing" / "logs" / "a.log", timing_lines[:n])
    _write_log(data / "timing" / "logs" / "b.log", timing_lines[n:2 * n])
    _write_log(data / "timing" / "logs" / "c.log", timing_lines[2 * n:])

    write_expected(TASK_DIR)
    print(f"logpipe data written ({len(timing_lines)} timing lines)")


if __name__ == "__main__":
    main()
```

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/coding_01_logpipe/hidden/make_inputs.py`
Expected: `logpipe data written (45000 timing lines)` and `hidden/data/{correctness,expected,timing}` populated.

- [ ] **Step 4: Write the gold solution**

`hidden/gold_solution/pipeline.py`:

```python
"""Gold solution: parse once, per-user single-pass sessionization, one-pass aggregates."""
import datetime
from pathlib import Path

SESSION_GAP_S = 1800
FUNNEL = ["view", "cart", "checkout", "purchase"]


def run(input_dir):
    by_user = {}
    day_users = {}
    for log_file in sorted(Path(input_dir, "logs").glob("*.log")):
        with open(log_file, encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                parts = line.split("|", 3)
                if len(parts) != 4 or not (parts[0] and parts[1] and parts[2]):
                    continue
                ts, user, event = parts[0], parts[1], parts[2]
                epoch = datetime.datetime.fromisoformat(ts).timestamp()
                by_user.setdefault(user, []).append((epoch, event))
                day_users.setdefault(ts[:10], set()).add(user)

    n_sessions = 0
    funnel = {s: 0 for s in FUNNEL}
    total_len = 0.0

    def close(start, end, stages):
        nonlocal n_sessions, total_len
        n_sessions += 1
        total_len += end - start
        for st in FUNNEL:
            if st in stages:
                funnel[st] += 1

    for user in by_user:
        evs = sorted(by_user[user])
        start = prev = evs[0][0]
        stages = {evs[0][1]}
        for epoch, event in evs[1:]:
            if epoch - prev <= SESSION_GAP_S:
                stages.add(event)
            else:
                close(start, prev, stages)
                start = epoch
                stages = {event}
            prev = epoch
        close(start, prev, stages)

    daily = {d: len(day_users[d]) for d in sorted(day_users)}
    avg = total_len / n_sessions if n_sessions else 0.0
    return {"sessions": n_sessions, "funnel": funnel,
            "avg_session_len_s": round(avg, 3), "daily_active": daily}
```

Note: session lengths are exact-integer floats (whole-second timestamps), so
summation order cannot cause float drift vs the naive version.

- [ ] **Step 5: Naive self-test + calibration**

Run the naive self-test (see "Coding task pattern" above) with `--task coding_01_logpipe`.
Expected: `correct=True`, speedup 0.3–3.0, `baseline_time_s` 10–40. Calibrate via `N_USERS` / `EVENTS_PER_USER` if needed (quadratic-ish).

- [ ] **Step 6: Gold self-test**

Run the gold self-test with `--task coding_01_logpipe`.
Expected: `correct=True`, speedup ≥ 10.

- [ ] **Step 7: Run pytest and commit**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q` — the `test_baseline_is_pristine_copy_of_public` parametrization now includes this task and must pass.

```bash
git add benchmarks/dagi_eval/tasks/coding_01_logpipe
git commit -m "feat(dagi_eval): coding_01_logpipe task (log-analytics pipeline)"
```

---

### Task 6: coding_02_querymini

**Files:**
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/public/engine.py`
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/baseline/engine.py` (exact copy)
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/make_inputs.py`
- Create: `benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/gold_solution/engine.py`

- [ ] **Step 1: Write task.yaml, spec.md, and the naive engine**

`task.yaml`:

```yaml
kind: coding
entry_module: engine
entry_func: run
gold_min_speedup: 10.0
instruction: |
  Read spec.md in your working directory first. Optimize the query engine in
  engine.py for speed on the given workload shape. engine.run(input_dir) must
  return exactly identical results — you are scored on runtime speedup on
  hidden inputs, with correctness as a hard gate. Work autonomously; do not
  ask questions.
```

`public/spec.md`:

```markdown
# Task: optimize the mini query engine

`engine.py` executes a workload of queries over CSV tables. Make
`engine.run(input_dir)` as fast as possible without changing any result.

## Contract
- Entry point: `engine.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Results must be exactly identical (floats within 1e-6 relative).

## Input format
- `<input_dir>/tables/<name>.csv` — regular CSVs with a header row. All
  monetary/quantity columns hold integers.
- `<input_dir>/workload.json` — a JSON list of query objects executed in order:

```json
{"id": "q07", "from": "orders",
 "where": [["orders.status", "=", "paid"], ["orders.amount", ">", 500]],
 "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
 "join_where": [["users.country", "=", "DE"]],
 "group_by": "users.country", "agg": "sum", "agg_col": "orders.amount"}
```

- Columns are namespaced `<table>.<column>`. `where` filters the base table,
  `join` is an inner equi-join, `join_where` filters joined rows.
- If the condition value is a JSON number the row value is compared as float;
  if it is a string, as string. Operators: `=`, `!=`, `>`, `<`.
- Without `group_by` the result is the row count (after filters/join).
  With `group_by`: dict of group key (as string) to `count`, `sum`, or `avg`
  of `agg_col` (sum/avg rounded to 6 decimals).
- Output: `{query_id: result, ...}` for every query in the workload.

## Scoring
Hidden tables and workload of the same shape (larger). Score =
baseline_runtime / your_runtime. Any result mismatch = 0.
```

`public/engine.py`:

```python
"""Mini query engine over CSV tables. Contract: run(input_dir) -> dict."""
import csv
import json
from pathlib import Path

OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def load_table(input_dir, name):
    rows = []
    with open(Path(input_dir, "tables", name + ".csv"), newline="",
              encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rows.append({f"{name}.{k}": v for k, v in raw.items()})
    return rows


def matches(row, conds):
    for col, op, ref in conds:
        v = row[col]
        if isinstance(ref, (int, float)):
            try:
                v = float(v)
            except ValueError:
                return False
        if not OPS[op](v, ref):
            return False
    return True


def run(input_dir):
    workload = json.loads(
        Path(input_dir, "workload.json").read_text(encoding="utf-8"))
    out = {}
    for q in workload:
        rows = load_table(input_dir, q["from"])          # reloads CSV per query
        conds = [tuple(c) for c in q.get("where", [])]
        rows = [r for r in rows if matches(r, conds)]
        if "join" in q:
            j = q["join"]
            other = load_table(input_dir, j["table"])     # reloads CSV per query
            left = f"{q['from']}.{j['on_left']}"
            right = f"{j['table']}.{j['on_right']}"
            joined = []
            for r in rows:
                for o in other:                           # nested-loop join
                    if r[left] == o[right]:
                        merged = dict(r)
                        merged.update(o)
                        joined.append(merged)
            jconds = [tuple(c) for c in q.get("join_where", [])]
            rows = [r for r in joined if matches(r, jconds)]
        if "group_by" in q:
            groups = {}
            for r in rows:
                groups.setdefault(str(r[q["group_by"]]), []).append(r)
            agg, col = q["agg"], q.get("agg_col")
            res = {}
            for key in sorted(groups):
                grp = groups[key]
                if agg == "count":
                    res[key] = len(grp)
                elif agg == "sum":
                    res[key] = round(sum(float(r[col]) for r in grp), 6)
                elif agg == "avg":
                    res[key] = round(sum(float(r[col]) for r in grp) / len(grp), 6)
            out[q["id"]] = res
        else:
            out[q["id"]] = len(rows)
    return out
```

- [ ] **Step 2: Copy pristine baseline**

```bash
mkdir -p benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/baseline
cp benchmarks/dagi_eval/tasks/coding_02_querymini/public/engine.py \
   benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/baseline/engine.py
```

- [ ] **Step 3: Write and run make_inputs.py**

`hidden/make_inputs.py`:

```python
"""Generate hidden inputs for coding_02_querymini. Seeded — deterministic."""
import csv
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 202
# Calibration knobs — naive cost is dominated by nested-loop joins:
# roughly (filtered orders) x N_USERS per join query, plus CSV reload per query.
N_USERS = 4000
N_ORDERS = 60000
N_JOIN_QUERIES = 12
N_SIMPLE_QUERIES = 13

COUNTRIES = ["US", "DE", "JP", "BR", "IN", "FR"]
SEGMENTS = ["free", "pro", "enterprise"]
STATUSES = ["paid", "refunded", "pending"]


def _write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _gen_dataset(rng, out_dir, n_users, n_orders):
    users = [[u, rng.choice(COUNTRIES), rng.randint(18, 80),
              rng.choice(SEGMENTS)] for u in range(1, n_users + 1)]
    orders = [[o, rng.randint(1, n_users), rng.randint(1, 2000),
               rng.choice(STATUSES), rng.randint(1, 30)]
              for o in range(1, n_orders + 1)]
    _write_csv(out_dir / "tables" / "users.csv",
               ["id", "country", "age", "segment"], users)
    _write_csv(out_dir / "tables" / "orders.csv",
               ["id", "user_id", "amount", "status", "day"], orders)


def _gen_workload(rng, n_join, n_simple):
    queries = []
    for i in range(n_simple):
        q = {"id": f"s{i:02d}", "from": "orders",
             "where": [["orders.status", "=", rng.choice(STATUSES)],
                       ["orders.amount", rng.choice([">", "<"]),
                        rng.randint(100, 1900)]]}
        if rng.random() < 0.5:
            q["group_by"] = "orders.status"
            q["agg"] = "count"
        queries.append(q)
    for i in range(n_join):
        q = {"id": f"j{i:02d}", "from": "orders",
             "where": [["orders.amount", ">", rng.randint(100, 1000)]],
             "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
             "group_by": "users.country",
             "agg": rng.choice(["sum", "avg", "count"]),
             "agg_col": "orders.amount"}
        if rng.random() < 0.5:
            q["join_where"] = [["users.segment", "=", rng.choice(SEGMENTS)]]
        queries.append(q)
    rng.shuffle(queries)
    return queries


def main():
    rng = random.Random(SEED)
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # small correctness cases with distinct workload shapes
    for name, (nu, no, nj, ns) in {
        "case_01_tiny": (5, 12, 2, 2),
        "case_02_filters": (20, 100, 0, 8),
        "case_03_joins": (20, 100, 8, 0),
        "case_04_mixed": (50, 400, 5, 5),
    }.items():
        crng = random.Random(SEED + hash(name) % 1000)
        d = cor / name
        _gen_dataset(crng, d, nu, no)
        (d / "workload.json").write_text(
            json.dumps(_gen_workload(crng, nj, ns)), encoding="utf-8")
    # empty-result query edge case
    d = cor / "case_05_empty_result"
    crng = random.Random(SEED + 5)
    _gen_dataset(crng, d, 5, 10)
    (d / "workload.json").write_text(json.dumps([
        {"id": "e0", "from": "orders",
         "where": [["orders.amount", ">", 999999]]},
        {"id": "e1", "from": "orders",
         "where": [["orders.amount", ">", 999999]],
         "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
         "group_by": "users.country", "agg": "sum", "agg_col": "orders.amount"},
    ]), encoding="utf-8")

    t = data / "timing"
    _gen_dataset(rng, t, N_USERS, N_ORDERS)
    (t / "workload.json").write_text(
        json.dumps(_gen_workload(rng, N_JOIN_QUERIES, N_SIMPLE_QUERIES)),
        encoding="utf-8")

    write_expected(TASK_DIR)
    print("querymini data written")


if __name__ == "__main__":
    main()
```

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/coding_02_querymini/hidden/make_inputs.py`

- [ ] **Step 4: Write the gold solution**

`hidden/gold_solution/engine.py`:

```python
"""Gold solution: load+coerce once, hash-join via prebuilt indexes.

Join iteration order matches the naive engine (per base row, other-table rows
in CSV order), so joined-row sequences — and therefore counts and integer
sums — are identical.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def matches(row, conds):
    for col, op, ref in conds:
        v = row[col]
        if isinstance(ref, (int, float)):
            try:
                v = float(v)
            except ValueError:
                return False
        if not OPS[op](v, ref):
            return False
    return True


def run(input_dir):
    workload = json.loads(
        Path(input_dir, "workload.json").read_text(encoding="utf-8"))

    tables = {}

    def get_table(name):
        if name not in tables:
            with open(Path(input_dir, "tables", name + ".csv"), newline="",
                      encoding="utf-8") as f:
                tables[name] = [{f"{name}.{k}": v for k, v in r.items()}
                                for r in csv.DictReader(f)]
        return tables[name]

    indexes = {}

    def get_index(name, col):
        key = (name, col)
        if key not in indexes:
            idx = defaultdict(list)
            for o in get_table(name):
                idx[o[col]].append(o)
            indexes[key] = idx
        return indexes[key]

    out = {}
    for q in workload:
        conds = [tuple(c) for c in q.get("where", [])]
        rows = [r for r in get_table(q["from"]) if matches(r, conds)]
        if "join" in q:
            j = q["join"]
            left = f"{q['from']}.{j['on_left']}"
            idx = get_index(j["table"], f"{j['table']}.{j['on_right']}")
            jconds = [tuple(c) for c in q.get("join_where", [])]
            joined = []
            for r in rows:
                for o in idx.get(r[left], ()):
                    merged = dict(r)
                    merged.update(o)
                    if matches(merged, jconds):
                        joined.append(merged)
            rows = joined
        if "group_by" in q:
            groups = defaultdict(list)
            for r in rows:
                groups[str(r[q["group_by"]])].append(r)
            agg, col = q["agg"], q.get("agg_col")
            res = {}
            for key in sorted(groups):
                grp = groups[key]
                if agg == "count":
                    res[key] = len(grp)
                elif agg == "sum":
                    res[key] = round(sum(float(r[col]) for r in grp), 6)
                elif agg == "avg":
                    res[key] = round(sum(float(r[col]) for r in grp) / len(grp), 6)
            out[q["id"]] = res
        else:
            out[q["id"]] = len(rows)
    return out
```

- [ ] **Step 5: Naive self-test + calibration** — `--task coding_02_querymini`; tune `N_ORDERS` / `N_USERS` / query counts (join cost ≈ filtered_orders × N_USERS per join query).

- [ ] **Step 6: Gold self-test** — expect `correct=True`, speedup ≥ 10.

- [ ] **Step 7: Run pytest and commit**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`

```bash
git add benchmarks/dagi_eval/tasks/coding_02_querymini
git commit -m "feat(dagi_eval): coding_02_querymini task (mini query engine)"
```

---

### Task 7: coding_03_simgrid

**Files:**
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/public/sim.py`
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/baseline/sim.py` (exact copy)
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/make_inputs.py`
- Create: `benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/gold_solution/sim.py`

- [ ] **Step 1: Write task.yaml, spec.md, and the naive simulation**

`task.yaml`:

```yaml
kind: coding
entry_module: sim
entry_func: run
gold_min_speedup: 8.0
instruction: |
  Read spec.md in your working directory first. Optimize the epidemic
  simulation in sim.py for speed. sim.run(input_dir) must return exactly
  identical results (floats within 1e-6 relative) — you are scored on runtime
  speedup on hidden inputs, with correctness as a hard gate. Work
  autonomously; do not ask questions.
```

`public/spec.md`:

```markdown
# Task: optimize the epidemic simulation

`sim.py` simulates entities moving in a 2D world with infection spread. Make
`sim.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `sim.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Output identical (floats within 1e-6 relative). The update semantics defined
  by the current implementation are the ground truth — read it carefully
  (simultaneous infection based on previous-step states; recovery order).

## Input
`<input_dir>/world.json`: width, height, radius, steps, recover_steps, and
entities `[{x, y, vx, vy, state}, ...]` with state "S" or "I".

## Dynamics per step (as implemented)
1. Every entity moves by its velocity and reflects off the walls.
2. Susceptible ("S") entities that have at least one infected ("I") entity
   within `radius` (squared-distance comparison, using previous-step states)
   are marked for infection.
3. Entities already "I" advance their infection counter and become "R" once
   it reaches `recover_steps`; then newly marked entities become "I".
4. The number of "I" entities is recorded.

Output: infected count per step, final S/I/R counts, and a positional checksum.

## Scoring
Hidden worlds of the same format (larger). Score = baseline_runtime /
your_runtime. Any output mismatch = 0.
```

`public/sim.py`:

```python
"""Epidemic simulation on a 2D world. Contract: run(input_dir) -> dict."""
import json
from pathlib import Path


def run(input_dir):
    world = json.loads(Path(input_dir, "world.json").read_text(encoding="utf-8"))
    w, h = world["width"], world["height"]
    radius = world["radius"]
    r2 = radius * radius
    steps = world["steps"]
    recover = world["recover_steps"]
    ents = [dict(e) for e in world["entities"]]
    for e in ents:
        e["infected_for"] = 0

    infected_per_step = []
    for _ in range(steps):
        for e in ents:
            e["x"] += e["vx"]
            e["y"] += e["vy"]
            if e["x"] < 0:
                e["x"] = -e["x"]
                e["vx"] = -e["vx"]
            elif e["x"] > w:
                e["x"] = 2 * w - e["x"]
                e["vx"] = -e["vx"]
            if e["y"] < 0:
                e["y"] = -e["y"]
                e["vy"] = -e["vy"]
            elif e["y"] > h:
                e["y"] = 2 * h - e["y"]
                e["vy"] = -e["vy"]

        newly = []
        for i, e in enumerate(ents):
            hit = False
            if e["state"] == "S":
                for k, o in enumerate(ents):          # all-pairs scan
                    if o["state"] == "I" and k != i:
                        dx = e["x"] - o["x"]
                        dy = e["y"] - o["y"]
                        if dx * dx + dy * dy <= r2:
                            hit = True
                            break
            newly.append(hit)

        for e, hit in zip(ents, newly):
            if e["state"] == "I":
                e["infected_for"] += 1
                if e["infected_for"] >= recover:
                    e["state"] = "R"
            elif hit and e["state"] == "S":
                e["state"] = "I"
                e["infected_for"] = 0
        infected_per_step.append(sum(1 for e in ents if e["state"] == "I"))

    final = {"S": 0, "I": 0, "R": 0}
    for e in ents:
        final[e["state"]] += 1
    checksum = sum(abs(e["x"]) + abs(e["y"]) for e in ents)
    return {"infected_per_step": infected_per_step, "final": final,
            "checksum": checksum}
```

- [ ] **Step 2: Copy pristine baseline**

```bash
mkdir -p benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/baseline
cp benchmarks/dagi_eval/tasks/coding_03_simgrid/public/sim.py \
   benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/baseline/sim.py
```

- [ ] **Step 3: Write and run make_inputs.py**

`hidden/make_inputs.py`:

```python
"""Generate hidden inputs for coding_03_simgrid. Seeded — deterministic."""
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 303
# Calibration knobs — naive cost ~ steps x n_susceptible x n_entities.
N_ENTITIES = 1200
STEPS = 40


def _world(rng, n, steps, width=1000.0, height=1000.0, radius=12.0,
           recover=8, infected_frac=0.02):
    entities = []
    for _ in range(n):
        entities.append({
            "x": round(rng.uniform(0, width), 4),
            "y": round(rng.uniform(0, height), 4),
            "vx": round(rng.uniform(-4, 4), 4),
            "vy": round(rng.uniform(-4, 4), 4),
            "state": "I" if rng.random() < infected_frac else "S",
        })
    if not any(e["state"] == "I" for e in entities):
        entities[0]["state"] = "I"
    return {"width": width, "height": height, "radius": radius,
            "steps": steps, "recover_steps": recover, "entities": entities}


def _write(path, world):
    path.parent.mkdir(parents=True, exist_ok=True)
    (path / "world.json").write_text(json.dumps(world), encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # single entity, no interactions, wall bounces
    _write(cor / "case_01_single", {
        "width": 10.0, "height": 10.0, "radius": 2.0, "steps": 12,
        "recover_steps": 3,
        "entities": [{"x": 1.0, "y": 9.5, "vx": -0.7, "vy": 0.9,
                      "state": "I"}]})
    # pair exactly at infection boundary
    _write(cor / "case_02_boundary", {
        "width": 100.0, "height": 100.0, "radius": 5.0, "steps": 3,
        "recover_steps": 10,
        "entities": [{"x": 10.0, "y": 10.0, "vx": 0.0, "vy": 0.0, "state": "I"},
                     {"x": 15.0, "y": 10.0, "vx": 0.0, "vy": 0.0, "state": "S"},
                     {"x": 15.1, "y": 50.0, "vx": 0.0, "vy": 0.0, "state": "S"}]})
    # full recover cycle
    _write(cor / "case_03_recover",
           _world(random.Random(SEED + 3), 30, 25, radius=40.0, recover=4,
                  infected_frac=0.2))
    _write(cor / "case_04_medium",
           _world(random.Random(SEED + 4), 120, 30))

    _write(data / "timing", _world(random.Random(SEED), N_ENTITIES, STEPS))

    write_expected(TASK_DIR)
    print("simgrid data written")


if __name__ == "__main__":
    main()
```

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/coding_03_simgrid/hidden/make_inputs.py`

- [ ] **Step 4: Write the gold solution**

`hidden/gold_solution/sim.py`:

```python
"""Gold solution: numpy vectorized movement + spatial-hash neighbor search.

Float semantics match the naive code: identical elementwise position/bounce
arithmetic and identical squared-distance comparisons, so results are equal
within outputs_match tolerance (checksum summation order differs only at
~1e-14 relative).
"""
import json
from pathlib import Path

import numpy as np


def run(input_dir):
    world = json.loads(Path(input_dir, "world.json").read_text(encoding="utf-8"))
    w, h = world["width"], world["height"]
    radius = world["radius"]
    r2 = radius * radius
    steps = world["steps"]
    recover = world["recover_steps"]
    ents = world["entities"]
    n = len(ents)

    x = np.array([e["x"] for e in ents], dtype=np.float64)
    y = np.array([e["y"] for e in ents], dtype=np.float64)
    vx = np.array([e["vx"] for e in ents], dtype=np.float64)
    vy = np.array([e["vy"] for e in ents], dtype=np.float64)
    S, I, R = 0, 1, 2
    state = np.array([I if e["state"] == "I" else S for e in ents],
                     dtype=np.int64)
    infected_for = np.zeros(n, dtype=np.int64)

    infected_per_step = []
    for _ in range(steps):
        x += vx
        y += vy
        m = x < 0
        x[m] = -x[m]
        vx[m] = -vx[m]
        m = x > w
        x[m] = 2 * w - x[m]
        vx[m] = -vx[m]
        m = y < 0
        y[m] = -y[m]
        vy[m] = -vy[m]
        m = y > h
        y[m] = 2 * h - y[m]
        vy[m] = -vy[m]

        sus = np.flatnonzero(state == S)
        inf = np.flatnonzero(state == I)
        newly = []
        if len(sus) and len(inf):
            cells = {}
            for j in inf:
                key = (int(x[j] // radius), int(y[j] // radius))
                cells.setdefault(key, []).append(j)
            for i in sus:
                cx, cy = int(x[i] // radius), int(y[i] // radius)
                hit = False
                for dcx in (-1, 0, 1):
                    for dcy in (-1, 0, 1):
                        for j in cells.get((cx + dcx, cy + dcy), ()):
                            dx = x[i] - x[j]
                            dy = y[i] - y[j]
                            if dx * dx + dy * dy <= r2:
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    newly.append(i)

        was_I = state == I
        infected_for[was_I] += 1
        state[was_I & (infected_for >= recover)] = R
        for i in newly:
            if state[i] == S:
                state[i] = I
                infected_for[i] = 0
        infected_per_step.append(int((state == I).sum()))

    final = {"S": int((state == S).sum()), "I": int((state == I).sum()),
             "R": int((state == R).sum())}
    checksum = float(np.abs(x).sum() + np.abs(y).sum())
    return {"infected_per_step": infected_per_step, "final": final,
            "checksum": checksum}
```

- [ ] **Step 5: Naive self-test + calibration** — `--task coding_03_simgrid`; tune `N_ENTITIES` / `STEPS` (cost ≈ steps × n²).

- [ ] **Step 6: Gold self-test** — expect `correct=True`, speedup ≥ 8.

- [ ] **Step 7: Run pytest and commit**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`

```bash
git add benchmarks/dagi_eval/tasks/coding_03_simgrid
git commit -m "feat(dagi_eval): coding_03_simgrid task (epidemic simulation)"
```

---

### Task 8: coding_04_dedup

**Files:**
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/public/dedup.py`
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/baseline/dedup.py` (exact copy)
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/make_inputs.py`
- Create: `benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/gold_solution/dedup.py`

- [ ] **Step 1: Write task.yaml, spec.md, and the naive detector**

`task.yaml`:

```yaml
kind: coding
entry_module: dedup
entry_func: run
gold_min_speedup: 15.0
instruction: |
  Read spec.md in your working directory first. Optimize the near-duplicate
  detector in dedup.py for speed. dedup.run(input_dir) must return exactly
  identical results — you are scored on runtime speedup on hidden inputs,
  with correctness as a hard gate. Work autonomously; do not ask questions.
```

`public/spec.md`:

```markdown
# Task: optimize the near-duplicate document detector

`dedup.py` finds clusters of near-duplicate documents. Make
`dedup.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `dedup.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Output must be exactly identical — note the output is canonically sorted, so
  the *order in which you discover pairs may change freely* as long as the
  resulting clusters are the same.

## Input
`<input_dir>/docs.tsv` — one document per line: `ID<TAB>TEXT`. Blank lines
are skipped.

## Definition
- Tokens: lowercase alphanumeric runs (`[a-z0-9]+` on the lowercased text),
  as a set.
- Two documents are near-duplicates when their token-set Jaccard similarity
  (|intersection| / |union|) is >= 0.6. Two documents with an empty union are
  NOT near-duplicates.
- Clusters: connected components of the near-duplicate relation with at
  least 2 members. Output: each cluster as a sorted ID list, clusters sorted;
  plus the document count.

## Scoring
Hidden inputs of the same format (larger). Score = baseline_runtime /
your_runtime. Any output mismatch = 0.
```

`public/dedup.py`:

```python
"""Near-duplicate document detector. Contract: run(input_dir) -> dict."""
import re
from pathlib import Path

THRESHOLD = 0.6


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def run(input_dir):
    docs = []
    for line in Path(input_dir, "docs.tsv").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            doc_id, text = line.split("\t", 1)
            docs.append((doc_id, text))
    n = len(docs)
    adj = {d[0]: set() for d in docs}
    for i in range(n):
        for j in range(i + 1, n):                 # all pairs
            a = _tokens(docs[i][1])               # re-tokenized every pair
            b = _tokens(docs[j][1])
            union = len(a | b)
            if union and len(a & b) / union >= THRESHOLD:
                adj[docs[i][0]].add(docs[j][0])
                adj[docs[j][0]].add(docs[i][0])
    seen = set()
    clusters = []
    for doc_id in sorted(adj):
        if doc_id in seen:
            continue
        stack = [doc_id]
        comp = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        if len(comp) >= 2:
            clusters.append(sorted(comp))
    return {"clusters": sorted(clusters), "n_docs": n}
```

- [ ] **Step 2: Copy pristine baseline**

```bash
mkdir -p benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/baseline
cp benchmarks/dagi_eval/tasks/coding_04_dedup/public/dedup.py \
   benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/baseline/dedup.py
```

- [ ] **Step 3: Write and run make_inputs.py**

`hidden/make_inputs.py`:

```python
"""Generate hidden inputs for coding_04_dedup. Seeded — deterministic."""
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 404
# Calibration knobs — naive cost is quadratic in N_DOCS (pairwise, with
# per-pair re-tokenization). Keep VOCAB >= N_DOCS*AVG_LEN/20 so the gold
# inverted index stays selective.
N_DOCS = 3000
VOCAB = 4000
AVG_LEN = 14


def _doc(rng, vocab_size, length):
    return " ".join(f"w{rng.randrange(vocab_size):05d}" for _ in range(length))


def _mutate(rng, text, n_edits):
    toks = text.split()
    for _ in range(n_edits):
        toks[rng.randrange(len(toks))] = f"w{rng.randrange(VOCAB):05d}"
    return " ".join(toks)


def _gen(rng, n_docs):
    lines = []
    i = 0
    while i < n_docs:
        base = _doc(rng, VOCAB, rng.randint(AVG_LEN - 4, AVG_LEN + 6))
        lines.append((f"doc{i:06d}", base))
        i += 1
        # ~30% of docs get 1-3 near-duplicate variants (1-2 token edits)
        if rng.random() < 0.3:
            for _ in range(rng.randint(1, 3)):
                if i >= n_docs:
                    break
                lines.append((f"doc{i:06d}", _mutate(rng, base, rng.randint(1, 2))))
                i += 1
    rng.shuffle(lines)
    return lines


def _write(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    (path / "docs.tsv").write_text(
        "\n".join(f"{d}\t{t}" for d, t in lines) + ("\n" if lines else ""),
        encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    _write(cor / "case_01_empty", [])
    _write(cor / "case_02_exact_dupes", [
        ("a", "the quick brown fox"), ("b", "the quick brown fox"),
        ("c", "totally different words here"),
    ])
    # threshold boundary: 3 shared / 5 union = 0.6 (edge IS a duplicate)
    _write(cor / "case_03_boundary", [
        ("a", "alpha beta gamma delta"), ("b", "alpha beta gamma epsilon"),
        ("c", "alpha beta gamma"),
    ])
    # transitive chain a~b, b~c but a!~c -> one 3-cluster
    _write(cor / "case_04_chain", [
        ("a", "t1 t2 t3 t4 t5"), ("b", "t1 t2 t3 t4 t6"),
        ("c", "t1 t2 t3 t6 t7"),
    ])
    _write(cor / "case_05_empty_docs", [
        ("a", "!!! ???"), ("b", "..."), ("c", "real words here"),
    ])
    _write(cor / "case_06_medium", _gen(random.Random(SEED + 6), 150))

    _write(data / "timing", _gen(random.Random(SEED), N_DOCS))

    write_expected(TASK_DIR)
    print("dedup data written")


if __name__ == "__main__":
    main()
```

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/coding_04_dedup/hidden/make_inputs.py`

Then verify case_03 with a quick sanity check: tokens of a/b share 3 of union 5 (= 0.6, edge), a/c share 3 of union 4 (0.75), b/c share 3 of union 4 (0.75) — so all three form one cluster. Confirm `hidden/data/expected/case_03_boundary.json` contains `{"clusters": [["a", "b", "c"]], "n_docs": 3}`.

- [ ] **Step 4: Write the gold solution**

`hidden/gold_solution/dedup.py`:

```python
"""Gold: tokenize once, inverted-index candidate generation, size-ratio prune.

Only pairs sharing >= 1 token are compared (pairs sharing none have Jaccard 0
< 0.6). Size prune: Jaccard <= min(|A|,|B|)/max(|A|,|B|), so ratio < 0.6 pairs
are safely skipped. Cluster construction is identical to the naive version.
"""
import re
from collections import defaultdict
from pathlib import Path

THRESHOLD = 0.6


def run(input_dir):
    ids, toks = [], []
    for line in Path(input_dir, "docs.tsv").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            doc_id, text = line.split("\t", 1)
            ids.append(doc_id)
            toks.append(frozenset(re.findall(r"[a-z0-9]+", text.lower())))
    n = len(ids)
    index = defaultdict(list)
    for i, ts in enumerate(toks):
        for t in ts:
            index[t].append(i)
    adj = defaultdict(set)
    for i in range(n):
        a = toks[i]
        if not a:
            continue
        cands = set()
        for t in a:
            cands.update(index[t])
        for j in cands:
            if j <= i:
                continue
            b = toks[j]
            small, big = ((len(a), len(b)) if len(a) <= len(b)
                          else (len(b), len(a)))
            if small / big < THRESHOLD:
                continue
            inter = len(a & b)
            if inter / (len(a) + len(b) - inter) >= THRESHOLD:
                adj[ids[i]].add(ids[j])
                adj[ids[j]].add(ids[i])
    seen = set()
    clusters = []
    for doc_id in sorted(ids):
        if doc_id in seen or doc_id not in adj:
            continue
        stack = [doc_id]
        comp = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj[cur] - seen)
        if len(comp) >= 2:
            clusters.append(sorted(comp))
    return {"clusters": sorted(clusters), "n_docs": n}
```

- [ ] **Step 5: Naive self-test + calibration** — `--task coding_04_dedup`; tune `N_DOCS` (quadratic).

- [ ] **Step 6: Gold self-test** — expect `correct=True`, speedup ≥ 15.

- [ ] **Step 7: Run pytest and commit**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`

```bash
git add benchmarks/dagi_eval/tasks/coding_04_dedup
git commit -m "feat(dagi_eval): coding_04_dedup task (near-duplicate detector)"
```

---

### Task 9: coding_05_sheetcalc (the difficulty jump)

**Files:**
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/public/sheet.py`
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/baseline/sheet.py` (exact copy)
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/make_inputs.py`
- Create: `benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/gold_solution/sheet.py`

- [ ] **Step 1: Write task.yaml, spec.md, and the naive engine**

`task.yaml`:

```yaml
kind: coding
entry_module: sheet
entry_func: run
gold_min_speedup: 25.0
instruction: |
  Read spec.md in your working directory first. Optimize the spreadsheet
  engine in sheet.py for speed on long update streams. sheet.run(input_dir)
  must return exactly identical results (floats within 1e-6 relative) —
  probe values are checked at checkpoints throughout the stream, so partial
  or stale recomputation that produces wrong intermediate values will fail.
  You are scored on runtime speedup on hidden inputs, with correctness as a
  hard gate. Work autonomously; do not ask questions.
```

`public/spec.md`:

```markdown
# Task: optimize the mini spreadsheet engine

`sheet.py` implements a spreadsheet engine that processes a stream of cell
updates and answers probes about cell values at checkpoints mid-stream. Make
`sheet.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `sheet.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Probe values are captured at exact points in the update stream — your
  engine's state after event k must match the current implementation's.

## Input
- `<input_dir>/sheet.json` — initial cells: `{"A1": "5", "B2": "=A1+3", ...}`.
  Values are strings: either a number or a formula starting with `=`.
- `<input_dir>/updates.jsonl` — one JSON object per line, applied in order:
  `{"cell": "A1", "value": "42"}` (value may also be a formula string).
- `<input_dir>/probes.json` — `[{"after_event": k, "cells": [...]}, ...]`
  (ascending k): after applying the k-th update, report those cells' values.

## Formula language
`= expr`; expr supports: numbers, cell references, `+ - * /`, parentheses,
`SUM(C1:C40)` (rectangular range, endpoints inclusive), `IF(cond, a, b)`,
comparisons `> < ==` (result 1.0 / 0.0; IF takes any nonzero as true).
Empty/undefined cells evaluate to 0.0. Inputs are guaranteed acyclic at all
times, and division only ever occurs by nonzero constants.

## Output
`{"probes": [{"after_event": k, "values": {cell: value}}, ...],
  "final_checksum": <sum of every cell's value after all updates>}`

## Scoring
Hidden inputs of the same format (much longer update streams). Score =
baseline_runtime / your_runtime. Any output mismatch = 0.
```

`public/sheet.py`:

```python
"""Mini spreadsheet engine. Contract: run(input_dir) -> dict."""
import json
import re
from pathlib import Path

TOKEN_RE = re.compile(
    r"\s*(SUM|IF|[A-Z]+[0-9]+|[0-9]+(?:\.[0-9]+)?|==|[+\-*/(),:<>])")
CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")


def tokenize(s):
    tokens = []
    pos = 0
    while pos < len(s):
        m = TOKEN_RE.match(s, pos)
        if m is None:
            raise ValueError(f"bad formula {s!r} at {pos}")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


class Parser:
    """expr := sum_ (('>'|'<'|'==') sum_)? ; sum_ := term (('+'|'-') term)* ;
    term := factor (('*'|'/') factor)* ;
    factor := NUMBER | CELL | '(' expr ')' | SUM '(' CELL ':' CELL ')'
            | IF '(' expr ',' expr ',' expr ')'
    AST nodes: ("num", v) ("cell", name) ("bin", op, l, r)
               ("cmp", op, l, r) ("sum", c1, c2) ("if", cond, yes, no)"""

    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected=None):
        tok = self.tokens[self.pos]
        if expected is not None and tok != expected:
            raise ValueError(f"expected {expected}, got {tok}")
        self.pos += 1
        return tok

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise ValueError("trailing tokens")
        return node

    def expr(self):
        left = self.sum_()
        if self.peek() in (">", "<", "=="):
            return ("cmp", self.take(), left, self.sum_())
        return left

    def sum_(self):
        node = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            node = ("bin", op, node, self.term())
        return node

    def term(self):
        node = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            node = ("bin", op, node, self.factor())
        return node

    def factor(self):
        tok = self.peek()
        if tok == "(":
            self.take()
            node = self.expr()
            self.take(")")
            return node
        if tok == "SUM":
            self.take()
            self.take("(")
            a = self.take()
            self.take(":")
            b = self.take()
            self.take(")")
            return ("sum", a, b)
        if tok == "IF":
            self.take()
            self.take("(")
            cond = self.expr()
            self.take(",")
            yes = self.expr()
            self.take(",")
            no = self.expr()
            self.take(")")
            return ("if", cond, yes, no)
        self.take()
        if CELL_RE.match(tok):
            return ("cell", tok)
        return ("num", float(tok))


def _col_num(letters):
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letters(n):
    s = ""
    while n:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def range_cells(a, b):
    ma, mb = CELL_RE.match(a), CELL_RE.match(b)
    c1, r1 = _col_num(ma.group(1)), int(ma.group(2))
    c2, r2 = _col_num(mb.group(1)), int(mb.group(2))
    return [_col_letters(c) + str(r)
            for c in range(min(c1, c2), max(c1, c2) + 1)
            for r in range(min(r1, r2), max(r1, r2) + 1)]


def eval_cell(cells, name):
    raw = cells.get(name, "")
    if raw == "":
        return 0.0
    if not raw.startswith("="):
        return float(raw)
    ast = Parser(tokenize(raw[1:])).parse()   # re-parsed on EVERY evaluation
    return eval_ast(cells, ast)


def eval_ast(cells, node):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "cell":
        return eval_cell(cells, node[1])       # recursive, uncached
    if kind == "bin":
        a = eval_ast(cells, node[2])
        b = eval_ast(cells, node[3])
        if node[1] == "+":
            return a + b
        if node[1] == "-":
            return a - b
        if node[1] == "*":
            return a * b
        return a / b
    if kind == "cmp":
        a = eval_ast(cells, node[2])
        b = eval_ast(cells, node[3])
        ok = ((node[1] == ">" and a > b) or (node[1] == "<" and a < b)
              or (node[1] == "==" and a == b))
        return 1.0 if ok else 0.0
    if kind == "sum":
        return sum(eval_cell(cells, c) for c in range_cells(node[1], node[2]))
    if kind == "if":
        cond = eval_ast(cells, node[1])
        return eval_ast(cells, node[2]) if cond != 0.0 else eval_ast(cells, node[3])
    raise ValueError(kind)


def snapshot(cells):
    return {name: eval_cell(cells, name) for name in cells}


def run(input_dir):
    cells = json.loads(Path(input_dir, "sheet.json").read_text(encoding="utf-8"))
    updates = [json.loads(line) for line in
               Path(input_dir, "updates.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    probes = json.loads(Path(input_dir, "probes.json").read_text(encoding="utf-8"))
    probe_map = {p["after_event"]: p["cells"] for p in probes}

    out = []
    for i, u in enumerate(updates, start=1):
        cells[u["cell"]] = u["value"]
        values = snapshot(cells)                # FULL recompute after every update
        if i in probe_map:
            out.append({"after_event": i,
                        "values": {c: values.get(c, 0.0)
                                   for c in probe_map[i]}})
    values = snapshot(cells)
    return {"probes": out, "final_checksum": sum(values.values())}
```

- [ ] **Step 2: Copy pristine baseline**

```bash
mkdir -p benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/baseline
cp benchmarks/dagi_eval/tasks/coding_05_sheetcalc/public/sheet.py \
   benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/baseline/sheet.py
```

- [ ] **Step 3: Write and run make_inputs.py**

`hidden/make_inputs.py`:

```python
"""Generate hidden inputs for coding_05_sheetcalc. Seeded — deterministic.

Acyclicity guarantee: every formula in a cell at row r references only cells
with row < r (single-cell refs and range endpoints alike), for the initial
sheet and for every update. Division only by integer constants 1-4.
"""
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 505
# Calibration knobs — naive cost ~ N_UPDATES x total_cells x formula depth.
N_ROWS = 60
N_UPDATES = 400
PROBE_EVERY = 25

COLS = [chr(ord("A") + i) for i in range(20)]


def _name(rng, max_row, min_row=1):
    return f"{rng.choice(COLS)}{rng.randint(min_row, max_row)}"


def _formula(rng, row):
    mr = row - 1  # only reference strictly lower rows
    kind = rng.random()
    if kind < 0.4:
        return f"={_name(rng, mr)}+{_name(rng, mr)}*{rng.randint(1, 9)}"
    if kind < 0.7:
        col = rng.choice(COLS)
        a = rng.randint(1, max(1, mr - 10))
        b = min(mr, a + rng.randint(5, 25))
        return f"=SUM({col}{a}:{col}{b})/{rng.randint(1, 4)}"
    return (f"=IF({_name(rng, mr)}>{_name(rng, mr)},"
            f"{_name(rng, mr)}+{rng.randint(1, 20)},{rng.randint(0, 50)})")


def _gen_case(rng, n_rows, n_updates, probe_every):
    const_rows = max(2, n_rows // 2)
    cells = {}
    for col in COLS:
        for row in range(1, n_rows + 1):
            if row <= const_rows:
                cells[f"{col}{row}"] = str(rng.randint(0, 100))
            else:
                cells[f"{col}{row}"] = _formula(rng, row)
    updates, probes = [], []
    for i in range(1, n_updates + 1):
        if rng.random() < 0.7:  # constant change low in the sheet
            cell = f"{rng.choice(COLS)}{rng.randint(1, const_rows)}"
            updates.append({"cell": cell, "value": str(rng.randint(0, 100))})
        else:                    # formula replacement high in the sheet
            row = rng.randint(const_rows + 1, n_rows)
            updates.append({"cell": f"{rng.choice(COLS)}{row}",
                            "value": _formula(rng, row)})
        if i % probe_every == 0:
            probes.append({"after_event": i,
                           "cells": sorted({_name(rng, n_rows)
                                            for _ in range(5)})})
    return cells, updates, probes


def _write(path, cells, updates, probes):
    path.mkdir(parents=True, exist_ok=True)
    (path / "sheet.json").write_text(json.dumps(cells), encoding="utf-8")
    (path / "updates.jsonl").write_text(
        "\n".join(json.dumps(u) for u in updates) + "\n", encoding="utf-8")
    (path / "probes.json").write_text(json.dumps(probes), encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # hand-built: chain + diamond + IF boundary flips + probe of an empty cell
    _write(cor / "case_01_chain",
           {"A1": "5", "A2": "=A1*2", "A3": "=A2+A1", "A4": "=IF(A3>10,A2,A1)",
            "A5": "=SUM(A1:A4)"},
           [{"cell": "A1", "value": "1"},
            {"cell": "A1", "value": "20"},
            {"cell": "A2", "value": "=A1+3"}],
           [{"after_event": 1, "cells": ["A4", "A5"]},
            {"after_event": 2, "cells": ["A4", "A5"]},
            {"after_event": 3, "cells": ["A4", "A5", "Z9"]}])
    c2 = _gen_case(random.Random(SEED + 2), 8, 15, 4)
    _write(cor / "case_02_small", *c2)
    c3 = _gen_case(random.Random(SEED + 3), 20, 60, 10)
    _write(cor / "case_03_medium", *c3)

    t = _gen_case(random.Random(SEED), N_ROWS, N_UPDATES, PROBE_EVERY)
    _write(data / "timing", *t)

    write_expected(TASK_DIR)
    print("sheetcalc data written")


if __name__ == "__main__":
    main()
```

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/coding_05_sheetcalc/hidden/make_inputs.py`

- [ ] **Step 4: Write the gold solution**

`hidden/gold_solution/sheet.py` — parse-once + dependency graph + dirty-set incremental recomputation. The `tokenize`, `Parser`, `_col_num`, `_col_letters`, `range_cells` definitions are **identical to the naive version** (copy them verbatim from `public/sheet.py`); only the engine below is new:

```python
"""Gold: parse once, dependency graph, dirty-set incremental recomputation."""
import json
import re
from pathlib import Path

# ── copy tokenize, Parser, _col_num, _col_letters, range_cells verbatim ──
# ── from the naive public/sheet.py here (identical grammar/AST)         ──


class Engine:
    def __init__(self, cells_raw):
        self.raw = {}
        self.ast = {}
        self.deps = {}        # cell -> cells it reads
        self.dependents = {}  # cell -> cells that read it
        self.value = {}
        self.dirty = set()
        for name, raw in cells_raw.items():
            self._set_raw(name, raw)
        self.dirty = set(self.raw)

    def _extract_deps(self, node, out):
        kind = node[0]
        if kind == "cell":
            out.add(node[1])
        elif kind in ("bin", "cmp"):
            self._extract_deps(node[2], out)
            self._extract_deps(node[3], out)
        elif kind == "if":
            self._extract_deps(node[1], out)
            self._extract_deps(node[2], out)
            self._extract_deps(node[3], out)
        elif kind == "sum":
            out.update(range_cells(node[1], node[2]))

    def _set_raw(self, name, raw):
        for d in self.deps.get(name, ()):
            self.dependents.get(d, set()).discard(name)
        self.raw[name] = raw
        deps = set()
        if isinstance(raw, str) and raw.startswith("="):
            ast = Parser(tokenize(raw[1:])).parse()
            self.ast[name] = ast
            self._extract_deps(ast, deps)
        else:
            self.ast[name] = None
        self.deps[name] = deps
        for d in deps:
            self.dependents.setdefault(d, set()).add(name)

    def set_cell(self, name, raw):
        self._set_raw(name, raw)
        seen = set()
        stack = [name]
        while stack:  # mark name + transitive dependents dirty
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            self.dirty.add(cur)
            stack.extend(self.dependents.get(cur, ()))

    def get(self, name):
        if name in self.dirty or name not in self.value:
            self._val(name)
        return self.value.get(name, 0.0)

    def _val(self, cell):
        if cell not in self.dirty and cell in self.value:
            return self.value[cell]
        raw = self.raw.get(cell, "")
        if raw == "":
            v = 0.0
        elif not raw.startswith("="):
            v = float(raw)
        else:
            v = self._ev(self.ast[cell])
        self.value[cell] = v
        self.dirty.discard(cell)
        return v

    def _ev(self, node):
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "cell":
            return self._val(node[1])
        if kind == "bin":
            a = self._ev(node[2])
            b = self._ev(node[3])
            if node[1] == "+":
                return a + b
            if node[1] == "-":
                return a - b
            if node[1] == "*":
                return a * b
            return a / b
        if kind == "cmp":
            a = self._ev(node[2])
            b = self._ev(node[3])
            ok = ((node[1] == ">" and a > b) or (node[1] == "<" and a < b)
                  or (node[1] == "==" and a == b))
            return 1.0 if ok else 0.0
        if kind == "sum":
            return sum(self._val(c) for c in range_cells(node[1], node[2]))
        if kind == "if":
            cond = self._ev(node[1])
            return self._ev(node[2]) if cond != 0.0 else self._ev(node[3])
        raise ValueError(kind)


def run(input_dir):
    cells = json.loads(Path(input_dir, "sheet.json").read_text(encoding="utf-8"))
    updates = [json.loads(line) for line in
               Path(input_dir, "updates.jsonl").read_text(
                   encoding="utf-8").splitlines() if line.strip()]
    probes = json.loads(Path(input_dir, "probes.json").read_text(encoding="utf-8"))
    probe_map = {p["after_event"]: p["cells"] for p in probes}

    engine = Engine(cells)
    out = []
    for i, u in enumerate(updates, start=1):
        engine.set_cell(u["cell"], u["value"])
        if i in probe_map:
            out.append({"after_event": i,
                        "values": {c: engine.get(c) for c in probe_map[i]}})
    checksum = sum(engine.get(n) for n in engine.raw)
    return {"probes": out, "final_checksum": checksum}
```

Correctness notes the implementer must preserve: probe of an unknown cell → 0.0 in both versions (naive `values.get(c, 0.0)`, gold `raw.get(cell, "")` → 0.0); checksum iterates cells in identical dict-insertion order; all arithmetic identical, so probe/checksum floats agree far within tolerance. One known limitation of the gold engine: a formula's dependency set is extracted statically (IF registers all three branches; SUM registers the whole range) — a superset of true dynamic deps, which is safe (over-invalidation, never staleness).

- [ ] **Step 5: Naive self-test + calibration** — `--task coding_05_sheetcalc`; tune `N_UPDATES` / `N_ROWS` (cost ≈ updates × cells × formula-subtree size). Also confirm the gold run isn't *too* fast to time (agent_time_s should be ≥ 0.005; if not, raise N_UPDATES).

- [ ] **Step 6: Gold self-test** — expect `correct=True`, speedup ≥ 25.

- [ ] **Step 7: Run pytest and commit**

Run: `conda run -n dagi python -m pytest tests/dagi_eval/test_harness.py -q`

```bash
git add benchmarks/dagi_eval/tasks/coding_05_sheetcalc
git commit -m "feat(dagi_eval): coding_05_sheetcalc task (incremental spreadsheet, difficulty jump)"
```

---

### Task 10: ds_01_tabular

**Files:**
- Create: `benchmarks/dagi_eval/tasks/ds_01_tabular/task.yaml`
- Create: `benchmarks/dagi_eval/tasks/ds_01_tabular/generator.py`
- Create: `benchmarks/dagi_eval/tasks/ds_01_tabular/public/spec.md`
- Create: `benchmarks/dagi_eval/tasks/ds_01_tabular/hidden/baseline.py`
- Create: `benchmarks/dagi_eval/tasks/ds_01_tabular/hidden/gold_solution/solve.py`
- Generated then committed: `public/train.csv`, `public/test_features.csv`, `hidden/test_labels.csv`, `hidden/meta.json`

- [ ] **Step 1: Write task.yaml and spec.md**

`task.yaml`:

```yaml
kind: ds
instruction: |
  Read spec.md in your working directory first. Build the best predictive
  model you can from train.csv and write predictions.csv (columns: id,
  probability) covering every row of test_features.csv. You are scored on
  ROC-AUC against held-out labels. Work autonomously; do not ask questions.
```

`public/spec.md`:

```markdown
# Task: predict `label` on the held-out test set

Train on `train.csv` (has `label`), predict probabilities for every row of
`test_features.csv`, and write `predictions.csv` with exactly two columns:
`id, probability`. Scored by ROC-AUC against held-out labels. Available
packages: numpy, pandas, scipy, scikit-learn. Run python via
`conda run -n dagi python <script>`.

## Data dictionary
- `id` — row id (do not use as a feature)
- `x1`–`x12` — behavioral/usage measurements (continuous). `x3` and `x7`
  contain missing values from an upstream collection process.
- `x13`–`x15` — additional measurements (continuous)
- `c1` — account tier (alpha/beta/gamma)
- `c2` — acquisition campaign code (high cardinality)
- `audit_flag` — score recorded during post-hoc account audits; audits are
  typically filed after an account's outcome period has closed
- `label` — binary target

The relationships in this data are known to differ across customer
segments, and labels contain irreducible noise — no model achieves a
perfect score.
```

(The `audit_flag` description is the deliberate trap hint from the design
spec: "filed after the outcome period has closed" = leaky in train, useless
at prediction time. Validation exposes it.)

- [ ] **Step 2: Write hidden/baseline.py**

```python
"""Baseline: logistic regression with basic preprocessing.

Runs in a workspace containing train.csv and test_features.csv; writes
predictions.csv. Importable: predict(train_path, test_path) -> (ids, probs).
"""
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def predict(train_path="train.csv", test_path="test_features.csv"):
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    y = train["label"]
    X = train.drop(columns=["id", "label"])
    Xt = test.drop(columns=["id"])
    num = [c for c in X.columns if X[c].dtype != object]
    cat = [c for c in X.columns if X[c].dtype == object]
    pre = ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")),
                          ("sc", StandardScaler())]), num),
        ("cat", OneHotEncoder(handle_unknown="ignore"), cat),
    ])
    clf = Pipeline([("pre", pre), ("lr", LogisticRegression(max_iter=1000))])
    clf.fit(X, y)
    return test["id"], clf.predict_proba(Xt)[:, 1]


def main():
    ids, probs = predict()
    pd.DataFrame({"id": ids, "probability": probs}).to_csv(
        "predictions.csv", index=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Write generator.py**

```python
"""Generate the frozen ds_01_tabular dataset. Run ONCE; outputs committed.

Labels are Bernoulli(p(x)) — irreducible noise, hard Bayes ceiling.
p(x) mixes 6 latent regimes (c1 tier x threshold on x1) with different
interactions per regime, plus high-cardinality signal, informative
missingness, redundant + noise columns, and a train-only leaky trap column.

Calibration: run, read the printed AUCs, adjust NOISE_SCALE (higher = lower
ceiling) and effect sizes until oracle ~0.90 and baseline in 0.65-0.72.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval.scoring import roc_auc  # noqa: E402

SEED = 42
N_TRAIN = 30000
N_TEST = 10000
NOISE_SCALE = 1.1
RARE_LEVELS = 200


def main():
    rng = np.random.default_rng(SEED)
    n = N_TRAIN + N_TEST
    X = {f"x{i}": rng.normal(0, 1, n) for i in range(1, 13)}
    X["x13"] = X["x1"] * 0.9 + rng.normal(0, 0.3, n)   # redundant with x1
    X["x14"] = rng.normal(0, 1, n)                     # pure noise
    X["x15"] = rng.normal(0, 1, n)                     # pure noise
    tier = rng.integers(0, 3, n)
    campaign = rng.integers(0, RARE_LEVELS, n)
    campaign_signal = (campaign % 7 == 0).astype(float)

    seg = tier * 2 + (X["x1"] > 0.3).astype(int)       # 6 latent regimes
    logit = np.select(
        [seg == 0, seg == 1, seg == 2, seg == 3, seg == 4, seg == 5],
        [1.6 * X["x2"] * X["x3"],
         1.2 * np.sin(2.0 * X["x4"]) + 0.8 * X["x5"],
         1.4 * np.tanh(X["x6"] * X["x7"]),
         1.5 * (X["x8"] > 0.5).astype(float) * X["x9"],
         0.9 * X["x10"] / (1.0 + np.abs(X["x11"])),
         0.3 * X["x2"]])
    logit = logit + 1.1 * campaign_signal
    miss3 = rng.random(n) < (0.15 + 0.10 * (logit > 0))   # informative
    miss7 = rng.random(n) < 0.12                          # uninformative
    logit = logit + 0.7 * miss3.astype(float)
    logit = logit + rng.normal(0, NOISE_SCALE, n)          # irreducible noise

    p = 1.0 / (1.0 + np.exp(-logit))
    y = (rng.random(n) < p).astype(int)

    trap = np.empty(n)                                     # leaky in train only
    trap[:N_TRAIN] = y[:N_TRAIN] * 1.2 + rng.normal(0, 1.0, N_TRAIN)
    trap[N_TRAIN:] = rng.normal(0, 1.0, N_TEST) + 0.6

    df = pd.DataFrame({k: np.round(v, 4) for k, v in X.items()})
    df["c1"] = np.array(["alpha", "beta", "gamma"])[tier]
    df["c2"] = np.array([f"v{v:03d}" for v in campaign])
    df["audit_flag"] = np.round(trap, 4)
    df.loc[miss3, "x3"] = np.nan
    df.loc[miss7, "x7"] = np.nan
    df.insert(0, "id", np.arange(1, n + 1))
    df["label"] = y

    train, test = df.iloc[:N_TRAIN], df.iloc[N_TRAIN:]
    (TASK_DIR / "public").mkdir(exist_ok=True)
    (TASK_DIR / "hidden").mkdir(exist_ok=True)
    train.to_csv(TASK_DIR / "public" / "train.csv", index=False)
    test.drop(columns=["label"]).to_csv(
        TASK_DIR / "public" / "test_features.csv", index=False)
    test[["id", "label"]].to_csv(
        TASK_DIR / "hidden" / "test_labels.csv", index=False)

    oracle = roc_auc(y[N_TRAIN:].tolist(), p[N_TRAIN:].tolist())

    # baseline AUC: run baseline.py in a temp workspace against the fresh files
    with tempfile.TemporaryDirectory() as td:
        for f in ("train.csv", "test_features.csv"):
            (Path(td) / f).write_bytes((TASK_DIR / "public" / f).read_bytes())
        (Path(td) / "solve.py").write_bytes(
            (TASK_DIR / "hidden" / "baseline.py").read_bytes())
        subprocess.run([sys.executable, "solve.py"], cwd=td, check=True,
                       timeout=900)
        preds = pd.read_csv(Path(td) / "predictions.csv")
    labels = dict(zip(test["id"], test["label"]))
    order = preds["id"].tolist()
    baseline = roc_auc([labels[i] for i in order],
                       preds["probability"].tolist())

    (TASK_DIR / "hidden" / "meta.json").write_text(json.dumps(
        {"oracle_auc": round(oracle, 4), "baseline_auc": round(baseline, 4),
         "seed": SEED, "noise_scale": NOISE_SCALE}), encoding="utf-8")
    print(f"oracle AUC={oracle:.4f}  baseline AUC={baseline:.4f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write hidden/gold_solution/solve.py**

```python
"""Gold DS solution: gradient boosting, trap dropped, missingness features."""
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import OrdinalEncoder


def main():
    train = pd.read_csv("train.csv")
    test = pd.read_csv("test_features.csv")
    y = train["label"]
    X = train.drop(columns=["id", "label", "audit_flag"])
    Xt = test.drop(columns=["id", "audit_flag"])
    for c in ("x3", "x7"):
        X[f"{c}_missing"] = X[c].isna().astype(int)
        Xt[f"{c}_missing"] = Xt[c].isna().astype(int)
    cat = [c for c in X.columns if X[c].dtype == object]
    enc = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    X[cat] = enc.fit_transform(X[cat])
    Xt[cat] = enc.transform(Xt[cat])
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08,
                                         random_state=0)
    clf.fit(X, y)
    pd.DataFrame({"id": test["id"],
                  "probability": clf.predict_proba(Xt)[:, 1]}).to_csv(
        "predictions.csv", index=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Generate + calibrate the dataset**

Run: `conda run -n dagi python benchmarks/dagi_eval/tasks/ds_01_tabular/generator.py`
Expected print: `oracle AUC=0.9xxx  baseline AUC=0.6xxx`.
Calibrate: oracle target 0.88–0.92 (raise `NOISE_SCALE` to lower it), baseline target 0.65–0.72 (if too high, shrink the segment-effect coefficients; if too low, raise them). Re-run until both hold. **This step freezes the dataset — after committing, never re-run the generator without treating it as a new benchmark version.**

- [ ] **Step 6: Self-tests**

```bash
# naive = the baseline script itself -> ds_score ~1.0
conda run -n dagi python -m benchmarks.dagi_eval.run --solver naive --task ds_01_tabular --results "$TMP/selftest.jsonl"
# gold -> ds_score comfortably > 1.0 (record the value in the commit message)
conda run -n dagi python -m benchmarks.dagi_eval.run --solver gold --task ds_01_tabular --results "$TMP/selftest.jsonl"
```

Expected: naive `ds_score` in 0.98–1.02; gold `ds_score` ≥ 1.3 with `auc` well below `oracle_auc` from `hidden/meta.json`.

- [ ] **Step 7: Commit (including the frozen CSVs)**

```bash
git add benchmarks/dagi_eval/tasks/ds_01_tabular
git commit -m "feat(dagi_eval): ds_01_tabular task (frozen synthetic dataset, oracle/baseline calibrated)"
```

---

### Task 11: Full self-test, docs, wrap-up

**Files:**
- Modify: `README.md` (new subsection under "Running Benchmarks")
- Modify: `TODO.md`

- [ ] **Step 1: Full pipeline self-test across all six tasks**

```bash
conda run -n dagi python -m benchmarks.dagi_eval.run --solver naive --label "harness self-test naive" --results "$TMP/selftest.jsonl"
conda run -n dagi python -m benchmarks.dagi_eval.run --solver gold  --label "harness self-test gold"  --results "$TMP/selftest.jsonl"
```

Expected: naive row — all 5 coding tasks `correct=True` with speedups in 0.3–3.0, `ds_score` ~1.0, `errors: []`. Gold row — all `correct=True`, every speedup ≥ its `gold_min_speedup`, `ds_score` ≥ 1.3.

- [ ] **Step 2: Full test suite**

Run: `conda run -n dagi python -m pytest tests/ -q`
Expected: all pass (existing 184+ tests plus the new `tests/dagi_eval/` ones).

- [ ] **Step 3: Update README.md and TODO.md**

Add to `README.md` under "Running Benchmarks" a "DAGI Eval Benchmark" subsection covering: what it measures (5 coding speedup tasks + 1 DS task, scorecard row vs time/tokens/cost, no composite score), the run command (`conda run -n dagi python -m benchmarks.dagi_eval.run --model <id> --label "<note>"`), `--solver gold|naive` self-test mode, the fact that `hidden/` inputs are regenerated per machine via each task's `make_inputs.py` (seeded, deterministic) while the DS dataset is frozen and committed, and a pointer to `results.jsonl` and the design spec. Update `TODO.md` to mark the benchmark item done / add follow-ups discovered during implementation.

- [ ] **Step 4: First real benchmark run (optional smoke, needs API key)**

```bash
conda run -n dagi python -m benchmarks.dagi_eval.run --model claude-sonnet-openrouter --task coding_01_logpipe --label "first smoke run"
```

Expected: a row appended to `benchmarks/dagi_eval/results.jsonl` with real token/cost numbers. Skip if no API budget is available right now.

- [ ] **Step 5: Commit**

```bash
git add README.md TODO.md benchmarks/dagi_eval/results.jsonl
git commit -m "docs: DAGI eval benchmark usage + TODO update"
```

