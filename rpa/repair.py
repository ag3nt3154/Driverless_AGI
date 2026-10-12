"""rpa/repair.py — repair context and a small, reviewed patch for a halted
workflow (Subtask 17, D7).

`repair_context` reads the evidence of the latest halted run. `preview_patch`
builds and validates a candidate workflow in memory and writes nothing;
`write_patch` writes it only after the caller (the `rpa_patch` tool, which
gets the model's approval) decides to. Ops are already resolved, plain dicts —
this module never calls a driver and never generates a locator. The caller
must already have turned every locator-bearing field (`target`, `if_present`,
`expect.present`/`expect.gone`) into generated locators.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from difflib import unified_diff
from pathlib import Path
from typing import Any

import yaml

from rpa import RpaError
from rpa.compiler import _collapse_duplicate_focus
from rpa.store import WorkflowStore
from rpa.workflow import (
    Step,
    Workflow,
    _STEP_ORDER,
    _step_to_dict,
    dump_workflow,
    parse_workflow,
    step_hash,
    workflow_hash,
)

__all__ = ["PatchPreview", "repair_context", "preview_patch", "write_patch"]

_ALLOWED_STEP_FIELDS = {"id", *_STEP_ORDER}


@dataclass(frozen=True)
class PatchPreview:
    """A pure, in-memory candidate patch. Nothing has been written yet."""

    workflow: Workflow
    yaml_text: str
    diff_text: str
    changed_confirm_steps: list[str]
    base_hash: str


# -- repair_context ------------------------------------------------------------


def _before_for_step(workflow_dir: Path, step_id: str) -> "dict | None":
    """The recorded `before` summary for `step_id`, mapped the same way
    `compile_trace` numbers steps (`step_NN` = NN-th non-header, de-duplicated
    trace entry). None when there is no trace, the id doesn't fit that
    numbering (a renamed step), or the matched entry isn't an `act`."""
    trace_path = workflow_dir / "trace.jsonl"
    if not trace_path.exists():
        return None
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
    except (OSError, json.JSONDecodeError):
        return None
    entries = [e for e in entries if e.get("kind") != "header"]
    entries = _collapse_duplicate_focus(entries)
    for i, entry in enumerate(entries, start=1):
        if f"step_{i:02d}" == step_id:
            return entry.get("before") if entry.get("kind") == "act" else None
    return None


def repair_context(store: WorkflowStore, name: str) -> dict:
    """Evidence for `name`'s latest halted run. Raises `RpaError` if the
    latest run did not halt, or its evidence cannot be read."""
    state = store.state(name)
    last_run = state.get("last_run") or {}
    if last_run.get("status") != "halted":
        raise RpaError(f"workflow {name!r} has no halted run")

    run_dir = Path(last_run["run_dir"])
    run_json_path = run_dir / "run.json"
    try:
        run_json = json.loads(run_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RpaError(f"workflow {name!r}: cannot read run evidence at {run_json_path}: {exc}") from exc

    halted_step = run_json.get("halted_step")
    reason = run_json.get("reason")

    workflow = store.load(name)
    step = next((s for s in workflow.steps if s.id == halted_step), None)
    if step is None:
        raise RpaError(f"workflow {name!r}: halted step {halted_step!r} is no longer in the workflow")
    step_yaml = yaml.safe_dump(_step_to_dict(step), sort_keys=False, default_flow_style=False, allow_unicode=True)

    outline_path = run_dir / "outline.txt"
    screenshot_path = run_dir / "halt.png"

    return {
        "name": name,
        "halted_step": halted_step,
        "step_yaml": step_yaml,
        "reason": reason,
        "run_dir": str(run_dir),
        "outline_path": str(outline_path) if outline_path.exists() else None,
        "screenshot_path": str(screenshot_path) if screenshot_path.exists() else None,
        "before": _before_for_step(store.dir(name), halted_step),
    }


# -- ops ------------------------------------------------------------------------


def _merge_step(old: Step, fields: dict) -> Step:
    if not isinstance(fields, dict):
        raise RpaError("repair: replace_step.step must be a mapping")
    unknown = set(fields) - _ALLOWED_STEP_FIELDS
    if unknown:
        raise RpaError(f"repair: unknown step field(s) {sorted(unknown)}")
    return replace(old, **{k: v for k, v in fields.items() if k != "id"})


def _new_step(data: Any) -> Step:
    if not isinstance(data, dict):
        raise RpaError("repair: insert_step_after.step must be a mapping")
    step_id = data.get("id")
    if not isinstance(step_id, str) or not step_id:
        raise RpaError("repair: insert_step_after.step.id is required")
    unknown = set(data) - _ALLOWED_STEP_FIELDS
    if unknown:
        raise RpaError(f"repair: unknown step field(s) {sorted(unknown)}")
    return Step(id=step_id, **{k: v for k, v in data.items() if k != "id"})


def _apply_ops(workflow: Workflow, ops: list[dict]) -> Workflow:
    steps: dict[str, Step] = {s.id: s for s in workflow.steps}
    order: list[str] = [s.id for s in workflow.steps]

    for op in ops:
        if not isinstance(op, dict):
            raise RpaError("repair: each op must be a mapping")
        kind = op.get("op")

        if kind == "replace_step":
            step_id = op.get("step_id")
            if not isinstance(step_id, str) or step_id not in steps:
                raise RpaError(f"repair: unknown step {step_id!r}")
            steps[step_id] = _merge_step(steps[step_id], op.get("step") or {})

        elif kind == "insert_step_after":
            after_id = op.get("after")
            if not isinstance(after_id, str) or after_id not in steps:
                raise RpaError(f"repair: unknown step {after_id!r}")
            step_data = op.get("step")
            if not isinstance(step_data, dict):
                raise RpaError("repair: insert_step_after.step must be a mapping")
            if "root" not in step_data:
                step_data = {**step_data, "root": steps[after_id].root}
            new_step = _new_step(step_data)
            if new_step.id in steps:
                raise RpaError(f"repair: duplicate step id {new_step.id!r}")
            steps[new_step.id] = new_step
            order.insert(order.index(after_id) + 1, new_step.id)

        elif kind == "delete_step":
            step_id = op.get("step_id")
            if not isinstance(step_id, str) or step_id not in steps:
                raise RpaError(f"repair: unknown step {step_id!r}")
            del steps[step_id]
            order.remove(step_id)

        else:
            raise RpaError(f"repair: unknown op {kind!r}")

    return replace(workflow, steps=[steps[sid] for sid in order])


def _changed_confirm_steps(old: Workflow, new: Workflow) -> list[str]:
    """Confirm steps (`step.confirm` truthy in old or new) that were added,
    deleted, or whose content changed."""
    old_by_id = {s.id: s for s in old.steps}
    new_by_id = {s.id: s for s in new.steps}
    changed: list[str] = []
    for step in new.steps:
        old_step = old_by_id.get(step.id)
        if not (step.confirm or (old_step is not None and old_step.confirm)):
            continue
        if old_step is None or step_hash(old_step) != step_hash(step):
            changed.append(step.id)
    for step in old.steps:
        if step.confirm and step.id not in new_by_id:
            changed.append(step.id)
    return changed


# -- preview / write ------------------------------------------------------------


def preview_patch(store: WorkflowStore, name: str, ops: list[dict]) -> PatchPreview:
    """Apply `ops` to an in-memory copy of `name` and validate the result.
    Writes nothing."""
    old_workflow = store.load(name)
    old_yaml = dump_workflow(old_workflow)
    base_hash = workflow_hash(old_workflow)

    new_workflow = _apply_ops(old_workflow, ops)
    # Re-validate through a full parse round-trip, exactly like compiler.apply_cleanup:
    # this also rejects anything an op above should never have been able to reach.
    new_workflow = parse_workflow(yaml.safe_load(dump_workflow(new_workflow)))
    new_yaml = dump_workflow(new_workflow)

    diff_text = "".join(unified_diff(
        old_yaml.splitlines(keepends=True), new_yaml.splitlines(keepends=True),
        fromfile="workflow.yaml", tofile="workflow.yaml",
    ))

    return PatchPreview(
        workflow=new_workflow,
        yaml_text=new_yaml,
        diff_text=diff_text,
        changed_confirm_steps=_changed_confirm_steps(old_workflow, new_workflow),
        base_hash=base_hash,
    )


def write_patch(store: WorkflowStore, name: str, preview: PatchPreview) -> None:
    """Write `preview`'s workflow and drop its changed confirm steps' approved
    hashes. Refuses if `workflow.yaml` changed since the preview was built."""
    current_hash = workflow_hash(store.load(name))
    if current_hash != preview.base_hash:
        raise RpaError(f"workflow {name!r} changed since the patch preview; call rpa_repair again")

    status = store.state(name)["status"]
    store.save(preview.workflow, status=status)

    if preview.changed_confirm_steps:
        store.clear_confirm_approvals(name, preview.changed_confirm_steps)
