"""tests/rpa/test_store.py — on-disk workflow store, approval lifecycle (Subtask 12)."""
from __future__ import annotations

import time

import pytest

from rpa import RpaError
from rpa.store import WorkflowStore
from rpa.workflow import Step, Workflow, step_hash


def _wf(**overrides) -> Workflow:
    steps = overrides.pop("steps", None) or [
        Step(id="s1", act="click", confirm="once"),
        Step(id="s2", act="click"),
        Step(id="s3", act="click", confirm="once", value="keep"),
    ]
    return Workflow(name=overrides.pop("name", "demo"), steps=steps)


def test_save_load_round_trips(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = _wf()
    store.save(wf)
    assert store.load("demo") == wf


def test_list(tmp_path):
    store = WorkflowStore(tmp_path)
    assert store.list() == []
    store.save(_wf())
    assert store.list() == ["demo"]


def test_dir_creates_subdirs(tmp_path):
    store = WorkflowStore(tmp_path)
    d = store.dir("demo")
    assert (d / "crops").is_dir()
    assert (d / "runs").is_dir()


def test_invalid_names_refused(tmp_path):
    store = WorkflowStore(tmp_path)
    for bad in ("Bad Name", "-leading-dash", "UPPER", "has space", ""):
        with pytest.raises(RpaError):
            store.dir(bad)


def test_save_rejects_invalid_workflow_name(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = Workflow(name="Bad Name", steps=[Step(id="s1", act="click")])
    with pytest.raises(RpaError):
        store.save(wf)


def test_state_default_before_any_save(tmp_path):
    store = WorkflowStore(tmp_path)
    state = store.state("never-saved")
    assert state["status"] == "draft"
    assert state["approved_hash_by_step"] == {}
    assert state["verified_at"] is None


def test_approve_refused_before_verify(tmp_path):
    store = WorkflowStore(tmp_path)
    store.save(_wf())
    with pytest.raises(RpaError):
        store.approve("demo")


def test_approve_refused_when_the_workflow_changed_after_verify(tmp_path):
    store = WorkflowStore(tmp_path)
    store.save(_wf())
    store.mark_verified("demo")
    store.save(_wf(steps=[Step(id="s1", act="click", confirm="once", value="changed")]))
    with pytest.raises(RpaError):
        store.approve("demo")


def test_any_edit_after_approval_reverts_status_to_draft(tmp_path):
    """Editing a step without `confirm` must also drop the approval (D8)."""
    store = WorkflowStore(tmp_path)
    wf = _wf()
    store.save(wf)
    store.mark_verified("demo")
    store.approve("demo")
    assert store.state("demo")["status"] == "approved"
    store.save(_wf(steps=[
        Step(id="s1", act="click", confirm="once"),
        Step(id="s2", act="double_click"),  # the only change: a step without confirm
        Step(id="s3", act="click", confirm="once", value="keep"),
    ]), status="approved")
    assert store.state("demo")["status"] == "draft"


def test_approve_after_fresh_verify(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = _wf()
    store.save(wf)
    time.sleep(0.05)
    store.mark_verified("demo")
    store.approve("demo")
    state = store.state("demo")
    assert state["status"] == "approved"
    assert state["approved_hash_by_step"] == {
        "s1": step_hash(wf.steps[0]),
        "s3": step_hash(wf.steps[2]),
    }


def test_confirm_ok_after_approve(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = _wf()
    store.save(wf)
    time.sleep(0.05)
    store.mark_verified("demo")
    store.approve("demo")
    assert store.confirm_ok("demo", wf.steps[0]) is True
    assert store.confirm_ok("demo", wf.steps[2]) is True


def test_edit_one_confirm_step_breaks_only_that_step(tmp_path):
    store = WorkflowStore(tmp_path)
    wf = _wf()
    store.save(wf)
    time.sleep(0.05)
    store.mark_verified("demo")
    store.approve("demo")

    edited = _wf(steps=[
        Step(id="s1", act="click", confirm="once", value="changed"),
        Step(id="s2", act="click"),
        Step(id="s3", act="click", confirm="once", value="keep"),
    ])
    store.save(edited)

    assert store.confirm_ok("demo", edited.steps[0]) is False
    assert store.confirm_ok("demo", edited.steps[2]) is True


def test_a_draft_that_halts_shows_halted(tmp_path):
    """Approval and run health are separate: a never-approved workflow's failed
    verify run must still be visible."""
    store = WorkflowStore(tmp_path)
    store.save(_wf())
    store.record_run("demo", "halted", reason="target not found", run_dir=tmp_path / "r", verify=True)
    state = store.state("demo")
    assert state["status"] == "draft"
    assert state["last_run"]["status"] == "halted" and state["last_run"]["reason"] == "target not found"
    assert store.display_status("demo") == "halted"


def test_run_health_cannot_be_written_as_approval(tmp_path):
    store = WorkflowStore(tmp_path)
    store.save(_wf())
    with pytest.raises(RpaError):
        store.set_status("demo", "halted")
