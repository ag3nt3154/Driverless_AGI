"""tests/rpa/test_repair.py — repair_context / preview_patch / write_patch (Subtask 17)."""
from __future__ import annotations

import json

import pytest

from rpa import RpaError
from rpa.repair import preview_patch, repair_context, write_patch
from rpa.store import WorkflowStore
from rpa.workflow import parse_workflow

_WF = {
    "name": "demo",
    "steps": [
        {
            "id": "click_ok",
            "act": "click",
            "root": {"window": {"title_re": "MyApp"}},
            "target": {"locators": [{"uia": {"automation_id": "btnOK"}}]},
        },
        {
            "id": "send_it",
            "act": "click",
            "confirm": "once",
            "root": {"window": {"title_re": "MyApp"}},
            "target": {"locators": [{"uia": {"automation_id": "btnSend"}}]},
        },
    ],
}


def _store(tmp_path) -> WorkflowStore:
    return WorkflowStore(tmp_path / "rpa")


def _save(store, data=None, *, status: str = "draft"):
    store.save(parse_workflow(data or _WF), status=status)


def _write_halt(store, name: str, step_id: str, *, reason: str = "no locator matched") -> None:
    run_dir = store.dir(name) / "runs" / "20261012T000000Z"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"name": name, "status": "halted", "halted_step": step_id, "reason": reason}),
        encoding="utf-8",
    )
    (run_dir / "outline.txt").write_text("[0] Button \"OK\"", encoding="utf-8")
    (run_dir / "halt.png").write_bytes(b"\x89PNG\r\n")
    store.record_run(name, "halted", reason=reason, run_dir=run_dir, verify=False)


# -- repair_context -----------------------------------------------------------


def test_repair_context_requires_a_halted_run(tmp_path):
    store = _store(tmp_path)
    _save(store)
    with pytest.raises(RpaError, match="no halted run"):
        repair_context(store, "demo")


def test_repair_context_on_halted_workflow_includes_evidence(tmp_path):
    store = _store(tmp_path)
    _save(store)
    _write_halt(store, "demo", "click_ok", reason="no locator matched")

    ctx = repair_context(store, "demo")

    assert ctx["name"] == "demo"
    assert ctx["halted_step"] == "click_ok"
    assert ctx["reason"] == "no locator matched"
    assert "btnOK" in ctx["step_yaml"]
    assert ctx["outline_path"] is not None
    assert ctx["screenshot_path"] is not None


def test_repair_context_omits_missing_evidence_files(tmp_path):
    store = _store(tmp_path)
    _save(store)
    run_dir = store.dir("demo") / "runs" / "20261012T000000Z"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(
        json.dumps({"name": "demo", "status": "halted", "halted_step": "click_ok", "reason": "x"}),
        encoding="utf-8",
    )
    store.record_run("demo", "halted", reason="x", run_dir=run_dir, verify=False)

    ctx = repair_context(store, "demo")

    assert ctx["outline_path"] is None
    assert ctx["screenshot_path"] is None


def test_repair_context_before_summary_from_trace(tmp_path):
    # Freshly compiled ids (step_NN) map 1:1 to trace entry order.
    store = _store(tmp_path)
    _save(store, {**_WF, "steps": [{**_WF["steps"][0], "id": "step_01"}, {**_WF["steps"][1], "id": "step_02"}]})
    trace_path = store.dir("demo") / "trace.jsonl"
    entries = [
        {"kind": "header", "name": "demo"},
        {"kind": "act", "n": 1, "action": "click", "before": {"role": "Button", "name": "OK", "path": []}},
        {"kind": "act", "n": 2, "action": "click", "before": {"role": "Button", "name": "Send", "path": []}},
    ]
    trace_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    _write_halt(store, "demo", "step_02")

    ctx = repair_context(store, "demo")

    assert ctx["before"] == {"role": "Button", "name": "Send", "path": []}


def test_repair_context_before_summary_none_for_a_renamed_step(tmp_path):
    # A step renamed during cleanup no longer fits the step_NN numbering.
    store = _store(tmp_path)
    _save(store)
    trace_path = store.dir("demo") / "trace.jsonl"
    entries = [
        {"kind": "act", "n": 1, "action": "click", "before": {"role": "Button", "name": "OK", "path": []}},
        {"kind": "act", "n": 2, "action": "click", "before": {"role": "Button", "name": "Send", "path": []}},
    ]
    trace_path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    _write_halt(store, "demo", "send_it")

    ctx = repair_context(store, "demo")

    assert ctx["before"] is None


def test_repair_context_before_summary_none_when_unmappable(tmp_path):
    store = _store(tmp_path)
    _save(store)
    _write_halt(store, "demo", "click_ok")  # no trace.jsonl at all

    ctx = repair_context(store, "demo")

    assert ctx["before"] is None


# -- preview_patch / write_patch ----------------------------------------------


def test_preview_patch_replace_step_changes_locators(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [
        {"op": "replace_step", "step_id": "click_ok",
         "step": {"target": {"locators": [{"uia": {"automation_id": "btnOK2"}}]}}},
    ])

    assert preview.workflow.steps[0].target == {"locators": [{"uia": {"automation_id": "btnOK2"}}]}
    assert "btnOK2" in preview.yaml_text
    assert "-" in preview.diff_text and "+" in preview.diff_text


def test_preview_patch_changed_confirm_step_is_flagged(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [
        {"op": "replace_step", "step_id": "send_it",
         "step": {"target": {"locators": [{"uia": {"automation_id": "btnSend2"}}]}}},
    ])

    assert preview.changed_confirm_steps == ["send_it"]


def test_preview_patch_unchanged_confirm_step_not_flagged(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [
        {"op": "replace_step", "step_id": "click_ok",
         "step": {"target": {"locators": [{"uia": {"automation_id": "btnOK2"}}]}}},
    ])

    assert preview.changed_confirm_steps == []


def test_preview_patch_insert_step_after_defaults_root_from_after_step(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [
        {"op": "insert_step_after", "after": "click_ok",
         "step": {"id": "wait_a_bit", "act": "focus",
                  "target": {"locators": [{"uia": {"automation_id": "btnOK"}}]}}},
    ])

    ids = [s.id for s in preview.workflow.steps]
    assert ids == ["click_ok", "wait_a_bit", "send_it"]
    inserted = preview.workflow.steps[1]
    assert inserted.root == {"window": {"title_re": "MyApp"}}


def test_preview_patch_insert_step_after_new_confirm_step_is_flagged(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [
        {"op": "insert_step_after", "after": "click_ok",
         "step": {"id": "confirm_new", "act": "click", "confirm": "once",
                  "target": {"locators": [{"uia": {"automation_id": "btnOK"}}]}}},
    ])

    assert preview.changed_confirm_steps == ["confirm_new"]


def test_preview_patch_delete_step_removing_confirm_step_is_flagged(tmp_path):
    store = _store(tmp_path)
    _save(store)

    preview = preview_patch(store, "demo", [{"op": "delete_step", "step_id": "send_it"}])

    assert [s.id for s in preview.workflow.steps] == ["click_ok"]
    assert preview.changed_confirm_steps == ["send_it"]


def test_preview_patch_unknown_step_id_raises(tmp_path):
    store = _store(tmp_path)
    _save(store)

    with pytest.raises(RpaError):
        preview_patch(store, "demo", [{"op": "replace_step", "step_id": "nope", "step": {}}])


def test_preview_patch_unknown_op_raises(tmp_path):
    store = _store(tmp_path)
    _save(store)

    with pytest.raises(RpaError):
        preview_patch(store, "demo", [{"op": "wat"}])


def test_preview_patch_writes_nothing(tmp_path):
    store = _store(tmp_path)
    _save(store)
    before = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")

    preview_patch(store, "demo", [{"op": "delete_step", "step_id": "send_it"}])

    after = (store.dir("demo") / "workflow.yaml").read_text(encoding="utf-8")
    assert before == after


def test_write_patch_writes_yaml_and_clears_approved_hash(tmp_path):
    store = _store(tmp_path)
    _save(store)
    store.mark_verified("demo")
    store.approve("demo")
    assert "send_it" in store.state("demo")["approved_hash_by_step"]

    preview = preview_patch(store, "demo", [
        {"op": "replace_step", "step_id": "send_it",
         "step": {"target": {"locators": [{"uia": {"automation_id": "btnSend2"}}]}}},
    ])
    write_patch(store, "demo", preview)

    workflow = store.load("demo")
    assert workflow.steps[1].target == {"locators": [{"uia": {"automation_id": "btnSend2"}}]}
    assert "send_it" not in store.state("demo")["approved_hash_by_step"]


def test_write_patch_refuses_when_workflow_changed_since_preview(tmp_path):
    store = _store(tmp_path)
    _save(store)
    preview = preview_patch(store, "demo", [{"op": "delete_step", "step_id": "send_it"}])

    # Someone else edits the workflow after the preview was taken.
    other = parse_workflow(_WF)
    store.save(other, status="draft")
    _save(store, {**_WF, "description": "edited"})

    with pytest.raises(RpaError, match="changed"):
        write_patch(store, "demo", preview)

    # Nothing written.
    workflow = store.load("demo")
    assert [s.id for s in workflow.steps] == ["click_ok", "send_it"]
