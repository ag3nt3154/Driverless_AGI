"""rpa/store.py — on-disk workflow store: `.dagi/rpa/<name>/`, state and approvals.

Layout per workflow: `workflow.yaml`, `crops/`, `runs/`, `state.json`
(`{status, approved_hash_by_step, verified_at, verified_hash, approved_hash, last_run}`).
See Subtask 12 of plan.md and the D5/D8 decisions in research.md.

Verify and approve are tied to content, not file times: a verify run records the
`workflow_hash` it ran, approve needs that hash to equal the current workflow,
and any later edit (a repair patch, a hand edit) makes `state()` report "draft"
until it is verified and approved again.

`status` is approval only (draft / approved). The health of the latest run
(ok / degraded / halted) is kept separately in `last_run`, so a draft that
halts during its verify run still shows that it halted; `display_status`
combines the two for lists and GUI chips.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from rpa import RpaError
from rpa.workflow import Step, Workflow, dump_workflow, load_workflow, step_hash, workflow_hash

__all__ = ["WorkflowStore"]

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_STATUSES = ("draft", "approved")  # approval only; run health lives in last_run
_RUN_STATUSES = ("ok", "degraded", "halted", "cancelled")
_EMPTY_STATE = {
    "status": "draft",
    "approved_hash_by_step": {},
    "verified_at": None,
    "verified_hash": None,
    "approved_hash": None,
    "last_run": None,
}


class WorkflowStore:
    """Workflow folders under `root` (the project's `.dagi/rpa` dir)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _check_name(self, name: str) -> None:
        if not _NAME_RE.match(name):
            raise RpaError(f"invalid workflow name: {name!r}; expected to match {_NAME_RE.pattern}")

    def dir(self, name: str) -> Path:
        """`root/<name>/`, creating `crops/` and `runs/` if needed."""
        self._check_name(name)
        path = self.root / name
        (path / "crops").mkdir(parents=True, exist_ok=True)
        (path / "runs").mkdir(parents=True, exist_ok=True)
        return path

    def _yaml_path(self, name: str) -> Path:
        return self.dir(name) / "workflow.yaml"

    def _state_path(self, name: str) -> Path:
        return self.dir(name) / "state.json"

    def save(self, workflow: Workflow, status: str = "draft") -> None:
        """Write `workflow.yaml`; create or update `state.json`'s status."""
        if status not in _STATUSES:
            raise RpaError(f"invalid status: {status!r}")
        self._yaml_path(workflow.name).write_text(dump_workflow(workflow), encoding="utf-8")
        state = self.state(workflow.name)
        state["status"] = status
        self._write_state(workflow.name, state)

    def load(self, name: str) -> Workflow:
        return load_workflow(self._yaml_path(name))

    def state(self, name: str) -> dict:
        """Stored state; a workflow edited since its approval reports status "draft"."""
        path = self._state_path(name)
        if not path.exists():
            return dict(_EMPTY_STATE, approved_hash_by_step={})
        state = {**_EMPTY_STATE, **json.loads(path.read_text(encoding="utf-8"))}
        if state["status"] != "draft" and self._yaml_path(name).exists():
            if state.get("approved_hash") != workflow_hash(self.load(name)):
                state["status"] = "draft"
        return state

    def _write_state(self, name: str, state: dict) -> None:
        self._state_path(name).write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8"
        )

    def set_status(self, name: str, status: str) -> None:
        if status not in _STATUSES:
            raise RpaError(f"invalid status: {status!r}")
        state = self.state(name)
        state["status"] = status
        self._write_state(name, state)

    def record_run(self, name: str, status: str, *, reason: str | None, run_dir: Path,
                   verify: bool, when: float | None = None) -> None:
        """Store the latest run's outcome (never its secrets: `reason` is already redacted)."""
        if status not in _RUN_STATUSES:
            raise RpaError(f"invalid run status: {status!r}")
        state = self.state(name)
        state["last_run"] = {
            "status": status, "reason": reason, "run_dir": str(run_dir), "verify": verify,
            "at": when if when is not None else time.time(),
        }
        self._write_state(name, state)

    def display_status(self, name: str) -> str:
        """`halted` / `degraded` when the latest run says so, else the approval status."""
        state = self.state(name)
        last = state.get("last_run") or {}
        return last.get("status") if last.get("status") in ("halted", "degraded") else state["status"]

    def mark_verified(self, name: str, when: float | None = None) -> None:
        """Record a clean verify run of the workflow as it is now."""
        state = self.state(name)
        state["verified_at"] = when if when is not None else time.time()
        state["verified_hash"] = workflow_hash(self.load(name))
        self._write_state(name, state)

    def approve(self, name: str) -> None:
        """Record the hash of every `confirm` step and set status `approved`.

        Requires a verify run of exactly the current workflow content.
        """
        if not self._yaml_path(name).exists():
            raise RpaError(f"workflow {name!r}: no workflow.yaml to approve")
        state = self.state(name)
        workflow = self.load(name)
        current = workflow_hash(workflow)
        if state.get("verified_hash") != current:
            raise RpaError(
                f"workflow {name!r}: approve requires a clean verify run of the current workflow"
            )
        state["approved_hash"] = current
        state["approved_hash_by_step"] = {
            s.id: step_hash(s) for s in workflow.steps if s.confirm
        }
        state["status"] = "approved"
        self._write_state(name, state)

    def confirm_ok(self, name: str, step: Step) -> bool:
        """True iff `step`'s current hash matches the one recorded on approve."""
        state = self.state(name)
        return state.get("approved_hash_by_step", {}).get(step.id) == step_hash(step)

    def list(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and (p / "workflow.yaml").exists()
        )
