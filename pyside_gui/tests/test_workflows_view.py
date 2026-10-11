"""pyside_gui/tests/test_workflows_view.py — Workflows rail view (Subtask 18)."""
from __future__ import annotations

import json
import time

import pytest

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from pyside_gui.sidebars.workflows_view import WorkflowsView, _STATUS_COLORS, primary_action
from rpa.store import WorkflowStore
from rpa.workflow import SecretRef, Step, Workflow


def _make_draft(project):
    store = WorkflowStore(project / ".dagi" / "rpa")
    store.save(Workflow(
        name="draft_wf",
        description="A draft workflow.",
        steps=[Step(id="s1", act="click"), Step(id="s2", act="set_value", confirm="once")],
    ))


def _make_approved_with_halt(project):
    store = WorkflowStore(project / ".dagi" / "rpa")
    wf = Workflow(
        name="approved_wf",
        description="An approved workflow that later halted.",
        secrets={"portal_pw": SecretRef(env="PORTAL_PW")},
        steps=[Step(id="step_a", act="click", confirm="once"), Step(id="step_b", act="set_value")],
    )
    store.save(wf)
    store.mark_verified("approved_wf")
    store.approve("approved_wf")
    run_dir = store.dir("approved_wf") / "runs" / "20261012-000000"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "steps": [
            {"step_id": "step_a", "rung_index": 0, "ms": 12.0, "status": "ok"},
            {"step_id": "step_b", "rung_index": None, "ms": 5.0, "status": "halted"},
        ]
    }), encoding="utf-8")
    store.record_run("approved_wf", "halted", reason="target not found", run_dir=run_dir,
                      verify=False, when=time.time())


@pytest.fixture
def project(tmp_path):
    _make_draft(tmp_path)
    _make_approved_with_halt(tmp_path)
    return tmp_path


@pytest.fixture
def view(qtbot, project):
    w = WorkflowsView()
    qtbot.addWidget(w)
    w.set_project(project)
    w.refresh()
    return w


def _row_names(view) -> list[str]:
    return [view._list.item(i).data(view._NAME_ROLE) for i in range(view._list.count())]


def test_refresh_lists_fixture_workflows_sorted(view):
    assert _row_names(view) == ["approved_wf", "draft_wf"]


def test_rows_show_right_status_chips(view):
    items = {view._list.item(i).data(view._NAME_ROLE): view._list.item(i)
             for i in range(view._list.count())}
    assert "halted" in items["approved_wf"].text()
    assert "draft" in items["draft_wf"].text()
    assert items["approved_wf"].foreground().color().name() == _STATUS_COLORS["halted"]
    assert items["draft_wf"].foreground().color().name() == _STATUS_COLORS["draft"]


def test_selecting_draft_shows_verify_run_button(view, qtbot):
    item = next(view._list.item(i) for i in range(view._list.count())
                if view._list.item(i).data(view._NAME_ROLE) == "draft_wf")
    view._list.setCurrentItem(item)
    view._on_selected(item)
    assert view._primary_button.text() == "Verify run"
    assert [s.id for s in view._detail.steps] == ["s1", "s2"]


def test_selecting_approved_halted_shows_repair_button(view):
    item = next(view._list.item(i) for i in range(view._list.count())
                if view._list.item(i).data(view._NAME_ROLE) == "approved_wf")
    view._list.setCurrentItem(item)
    view._on_selected(item)
    assert view._primary_button.text() == "Repair"
    assert view._detail.secret_names == ["portal_pw"]


def test_primary_button_click_emits_action_requested(view, qtbot):
    item = next(view._list.item(i) for i in range(view._list.count())
                if view._list.item(i).data(view._NAME_ROLE) == "approved_wf")
    view._list.setCurrentItem(item)
    view._on_selected(item)
    with qtbot.waitSignal(view.action_requested, timeout=1000) as blocker:
        view._primary_button.click()
    assert blocker.args == ["Repair workflow `approved_wf` (rpa_repair)."]


def test_refresh_button_exists_and_reloads(view, project):
    assert view._refresh_button is not None
    store = WorkflowStore(project / ".dagi" / "rpa")
    store.save(Workflow(name="new_wf", steps=[Step(id="s1", act="click")]))
    view.refresh()
    assert "new_wf" in _row_names(view)


# --- primary_action pure helper ---

def test_primary_action_draft_not_verified():
    from rpa.api import Detail
    detail = Detail(name="x", goal="", approval_status="draft", display_status="draft",
                     verified=False, params=[], secret_names=[], last_run=None, steps=[])
    assert primary_action(detail) == ("Verify run", "Verify workflow `x` (rpa_run with verify=true).")


def test_primary_action_verified_not_approved():
    from rpa.api import Detail
    detail = Detail(name="x", goal="", approval_status="draft", display_status="draft",
                     verified=True, params=[], secret_names=[], last_run=None, steps=[])
    assert primary_action(detail) == ("Approve", "Approve workflow `x` (rpa_approve).")


def test_primary_action_approved():
    from rpa.api import Detail
    detail = Detail(name="x", goal="", approval_status="approved", display_status="approved",
                     verified=True, params=[], secret_names=[], last_run=None, steps=[])
    assert primary_action(detail) == ("Run", "Run workflow `x` (rpa_run).")


def test_primary_action_halted_overrides_approved():
    from rpa.api import Detail
    detail = Detail(name="x", goal="", approval_status="approved", display_status="halted",
                     verified=True, params=[], secret_names=[], last_run=None, steps=[])
    assert primary_action(detail) == ("Repair", "Repair workflow `x` (rpa_repair).")


def test_corrupt_workflow_shows_an_error_and_no_action(qtbot, project):
    (project / ".dagi" / "rpa" / "approved_wf" / "workflow.yaml").write_text("steps: [\n bad", encoding="utf-8")
    w = WorkflowsView()
    qtbot.addWidget(w)
    w.set_project(project)
    w.refresh()

    item = next(w._list.item(i) for i in range(w._list.count())
                if w._list.item(i).data(WorkflowsView._NAME_ROLE) == "approved_wf")
    w._on_selected(item)  # must not raise out of the Qt slot

    assert not w._primary_button.isEnabled()
    assert "cannot read" in w._last_run_label.text()
