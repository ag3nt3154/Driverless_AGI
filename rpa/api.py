"""rpa/api.py — read-only summary/detail views over the workflow store (Subtask 18).

No Qt, no agent imports (same isolation rule as the rest of ``rpa/``, see
``tests/rpa/test_isolation.py``): the GUI's workflows rail view and the CLI
both read workflows through this module, never ``WorkflowStore`` directly, so
there is exactly one place that decides what a workflow "looks like" from the
outside. Secret *values* never appear here — only the declared secret names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from rpa import RPA_HOME_DIRNAME, RpaError
from rpa.store import WorkflowStore
from rpa.workflow import workflow_hash

__all__ = ["Summary", "StepInfo", "Detail", "list_workflows", "workflow_detail"]

# A hand-edited or half-written workflow must not break the views over the others.
_READ_ERRORS = (RpaError, yaml.YAMLError, OSError, ValueError, TypeError, KeyError)


@dataclass(frozen=True)
class Summary:
    """One row for a workflow list."""

    name: str
    display_status: str
    last_run_status: str | None
    last_run_at: float | None


@dataclass(frozen=True)
class StepInfo:
    """One row of a workflow's steps table."""

    id: str
    act: str | None
    confirm: str | None
    last_rung: int | None


@dataclass(frozen=True)
class Detail:
    """Everything the GUI (or CLI) shows about one workflow."""

    name: str
    goal: str
    approval_status: str
    display_status: str
    verified: bool
    params: list[tuple[str, object]]
    secret_names: list[str]
    last_run: dict | None
    steps: list[StepInfo]


def _store(project: Path) -> WorkflowStore:
    return WorkflowStore(Path(project) / RPA_HOME_DIRNAME)


def list_workflows(project: Path) -> list[Summary]:
    """Every workflow under ``project``'s `.dagi/rpa`, sorted by name.

    Returns an empty list when there is no `.dagi/rpa` directory yet.
    """
    store = _store(project)
    summaries = []
    for name in store.list():
        try:
            store.load(name)  # a draft's state never reads the YAML: parse it here
            state = store.state(name)
            display_status = store.display_status(name)
        except _READ_ERRORS:
            summaries.append(Summary(name=name, display_status="error",
                                     last_run_status=None, last_run_at=None))
            continue
        last_run = state.get("last_run") or {}
        summaries.append(Summary(
            name=name,
            display_status=display_status,
            last_run_status=last_run.get("status"),
            last_run_at=last_run.get("at"),
        ))
    return summaries


def _last_rungs(run_dir: str | None) -> dict[str, int | None]:
    """step_id -> rung_index from the last run's ``run.json``, or {} if unavailable."""
    if not run_dir:
        return {}
    run_json = Path(run_dir) / "run.json"
    if not run_json.exists():
        return {}
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {s.get("step_id"): s.get("rung_index") for s in data.get("steps", [])}


def workflow_detail(project: Path, name: str) -> Detail:
    """Full detail view for one workflow. Raises `RpaError` for an unknown name
    or a workflow that cannot be read."""
    store = _store(project)
    if name not in store.list():
        raise RpaError(f"workflow {name!r}: not found")
    try:
        workflow = store.load(name)
        state = store.state(name)
    except RpaError as exc:
        raise RpaError(f"workflow {name!r}: cannot read workflow.yaml: {exc}") from exc
    except _READ_ERRORS as exc:
        raise RpaError(f"workflow {name!r}: cannot read workflow.yaml: {type(exc).__name__}: {exc}") from exc
    verified = state.get("verified_hash") == workflow_hash(workflow)
    last_run = state.get("last_run")
    rungs = _last_rungs(last_run.get("run_dir") if last_run else None)
    steps = [
        StepInfo(id=s.id, act=s.act, confirm=s.confirm, last_rung=rungs.get(s.id))
        for s in workflow.steps
    ]
    return Detail(
        name=workflow.name,
        goal=workflow.description,
        approval_status=state["status"],
        display_status=store.display_status(name),
        verified=verified,
        params=[(pname, p.default) for pname, p in workflow.params.items()],
        secret_names=sorted(workflow.secrets),
        last_run=last_run,
        steps=steps,
    )
