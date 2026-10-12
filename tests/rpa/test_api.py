"""tests/rpa/test_api.py — read-only summary/detail views over the workflow store (Subtask 18).

No Qt, no agent imports: the GUI's workflows rail and any future caller both
read workflows through `rpa.api`, never the store directly.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from rpa import RpaError
from rpa.api import list_workflows, workflow_detail
from rpa.store import WorkflowStore
from rpa.workflow import SecretRef, Step, Workflow


def _make_draft(project: Path) -> None:
    store = WorkflowStore(project / ".dagi" / "rpa")
    wf = Workflow(
        name="draft_wf",
        description="A draft workflow.",
        steps=[
            Step(id="s1", act="click"),
            Step(id="s2", act="set_value", confirm="once"),
        ],
    )
    store.save(wf)


def _make_approved_with_halt(project: Path) -> None:
    store = WorkflowStore(project / ".dagi" / "rpa")
    wf = Workflow(
        name="approved_wf",
        description="An approved workflow that later halted.",
        params={},
        secrets={"portal_pw": SecretRef(env="PORTAL_PW")},
        steps=[
            Step(id="step_a", act="click", confirm="once"),
            Step(id="step_b", act="set_value"),
        ],
    )
    store.save(wf)
    store.mark_verified("approved_wf")
    store.approve("approved_wf")
    run_dir = store.dir("approved_wf") / "runs" / "20261012-000000"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({
            "steps": [
                {"step_id": "step_a", "rung_index": 0, "ms": 12.0, "status": "ok"},
                {"step_id": "step_b", "rung_index": None, "ms": 5.0, "status": "halted"},
            ]
        }),
        encoding="utf-8",
    )
    store.record_run(
        "approved_wf", "halted", reason="target not found", run_dir=run_dir, verify=False,
        when=time.time(),
    )


@pytest.fixture
def project(tmp_path):
    _make_draft(tmp_path)
    _make_approved_with_halt(tmp_path)
    return tmp_path


# --- list_workflows ---

def test_empty_project_has_no_workflows(tmp_path):
    assert list_workflows(tmp_path) == []


def test_list_workflows_sorted_with_right_summaries(project):
    summaries = list_workflows(project)
    assert [s.name for s in summaries] == ["approved_wf", "draft_wf"]

    approved = summaries[0]
    assert approved.display_status == "halted"
    assert approved.last_run_status == "halted"
    assert approved.last_run_at is not None

    draft = summaries[1]
    assert draft.display_status == "draft"
    assert draft.last_run_status is None
    assert draft.last_run_at is None


# --- workflow_detail ---

def test_workflow_detail_unknown_name_raises(project):
    with pytest.raises(RpaError):
        workflow_detail(project, "does-not-exist")


def test_workflow_detail_draft(project):
    detail = workflow_detail(project, "draft_wf")
    assert detail.name == "draft_wf"
    assert detail.goal == "A draft workflow."
    assert detail.approval_status == "draft"
    assert detail.display_status == "draft"
    assert detail.verified is False
    assert detail.params == []
    assert detail.secret_names == []
    assert detail.last_run is None
    assert [s.id for s in detail.steps] == ["s1", "s2"]
    assert detail.steps[0].confirm is None
    assert detail.steps[1].confirm == "once"
    assert detail.steps[0].last_rung is None


def test_workflow_detail_approved_with_halted_run_and_secrets(project):
    detail = workflow_detail(project, "approved_wf")
    assert detail.approval_status == "approved"
    assert detail.display_status == "halted"
    assert detail.verified is True
    assert detail.secret_names == ["portal_pw"]
    for secret_name in detail.secret_names:
        assert "PORTAL_PW" not in secret_name  # names only, never env var or value
    assert detail.last_run["status"] == "halted"
    assert detail.last_run["reason"] == "target not found"

    step_a, step_b = detail.steps
    assert step_a.act == "click"
    assert step_a.confirm == "once"
    assert step_a.last_rung == 0
    assert step_b.last_rung is None


def test_workflow_detail_params_names_and_defaults(tmp_path):
    store = WorkflowStore(tmp_path / ".dagi" / "rpa")
    from rpa.workflow import Param
    wf = Workflow(
        name="with_params",
        params={"report_date": Param(default="{{ yesterday }}")},
        steps=[Step(id="s1", act="click")],
    )
    store.save(wf)
    detail = workflow_detail(tmp_path, "with_params")
    assert detail.params == [("report_date", "{{ yesterday }}")]


def _corrupt(project: Path, name: str) -> None:
    (project / ".dagi" / "rpa" / name / "workflow.yaml").write_text("steps: [\n  - id: x\n bad", encoding="utf-8")


@pytest.mark.parametrize("name", ["draft_wf", "approved_wf"])
def test_corrupt_workflow_does_not_break_the_list(tmp_path, name):
    _make_draft(tmp_path)
    _make_approved_with_halt(tmp_path)
    _corrupt(tmp_path, name)

    summaries = {s.name: s for s in list_workflows(tmp_path)}

    assert set(summaries) == {"draft_wf", "approved_wf"}
    assert summaries[name].display_status == "error"


def test_corrupt_workflow_detail_raises_rpa_error(tmp_path):
    _make_draft(tmp_path)
    _corrupt(tmp_path, "draft_wf")
    with pytest.raises(RpaError, match="cannot read"):
        workflow_detail(tmp_path, "draft_wf")
