import json
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
DS_TASK = _TASKS_ROOT / "ds_01_tabular"


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


@pytest.mark.skipif(not (DS_TASK / "hidden" / "meta.json").exists(),
                    reason="ds_01_tabular dataset not generated on this machine")
def test_ds_task_naive_solver_scores_parity():
    ws = harness.prepare_workspace(DS_TASK)
    harness.apply_canned_solver(ws, DS_TASK, "naive", "ds")
    res = scoring.score_ds_task(DS_TASK, ws)
    assert res["error"] is None
    assert 0.98 <= res["ds_score"] <= 1.02


@pytest.mark.skipif(not (DS_TASK / "hidden" / "meta.json").exists(),
                    reason="ds_01_tabular dataset not generated on this machine")
def test_ds_task_gold_solver_beats_baseline():
    ws = harness.prepare_workspace(DS_TASK)
    harness.apply_canned_solver(ws, DS_TASK, "gold", "ds")
    res = scoring.score_ds_task(DS_TASK, ws)
    meta = json.loads((DS_TASK / "hidden" / "meta.json").read_text(encoding="utf-8"))
    assert res["error"] is None
    assert res["ds_score"] >= 1.3
    assert res["auc"] < meta["oracle_auc"]


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
