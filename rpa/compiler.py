"""rpa/compiler.py — deterministic trace -> draft `Workflow`, and restricted cleanup.

`compile_trace` never guesses: it only reshapes what the trace already recorded.
`apply_cleanup` lets the model delete, rename, parameterize and flag steps — and
nothing else; any op that would add or change a `locators` list raises `RpaError`,
as does any unrecognised op or field (Subtask 14, D8).
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import yaml

from rpa import RpaError
from rpa.model import Element
from rpa.safety import is_sensitive
from rpa.workflow import Param, SecretRef, Step, Workflow, dump_workflow, parse_workflow

__all__ = ["compile_trace", "apply_cleanup"]

_EXPECT_ORDER = ("window", "present", "value_equals")
_STEP_ID_RE = re.compile(r"^[a-z0-9_]+$")

_DELETE_KEYS = {"op", "step"}
_RENAME_KEYS = {"op", "step", "to"}
_PARAM_KEYS = {"op", "step", "field", "name", "default"}
_FLAG_KEYS = {"op", "step", "confirm", "sensitive", "expect_file"}


def _collapse_duplicate_focus(entries: list[dict]) -> list[dict]:
    """Adjacent `act` entries that are both `focus` on the same target collapse to one."""
    out: list[dict] = []
    for entry in entries:
        if (
            out
            and out[-1].get("kind") == "act"
            and out[-1].get("action") == "focus"
            and entry.get("kind") == "act"
            and entry.get("action") == "focus"
            and out[-1].get("locators") == entry.get("locators")
        ):
            continue
        out.append(entry)
    return out


def _compile_root(desc: dict, launch_steps: dict[int, str]) -> dict:
    """Title/url pattern, plus `launched_by` when the root was opened by a launch step
    of this recording (titles change with the document; the launched window does not)."""
    kind = desc["kind"]
    spec = {"title_re": desc["title_re"]} if kind == "window" else {"url_re": desc["url_re"]}
    if desc.get("launch_id") in launch_steps:
        spec["launched_by"] = launch_steps[desc["launch_id"]]
    return {kind: spec}


def _compile_value(value: Any, secrets: dict[str, SecretRef]) -> Any:
    if value is None or not isinstance(value, dict):
        return value
    if "secret_env" in value:
        env = value["secret_env"]
        secret_name = env.lower()
        secrets.setdefault(secret_name, SecretRef(env=env))
        return f"{{{{ secrets.{secret_name} }}}}"
    if value.get("secret") is True:
        raise RpaError(
            "compile_trace: a secure field was recorded with a literal value; "
            "re-record this step typing ${env:NAME} instead of a literal secret"
        )
    raise RpaError(f"compile_trace: unrecognized recorded value {value!r}")


def _compile_expect(candidates: list[dict]) -> "dict | None":
    for key in _EXPECT_ORDER:
        for candidate in candidates:
            if key in candidate:
                return {**candidate, "timeout": 10}
    return None


def _is_sensitive_before(before: dict) -> bool:
    element = Element(
        index=0,
        role=before.get("role", ""),
        name=before.get("name", ""),
        automation_id=None,
        bbox=(0, 0, 0, 0),
        value=None,
        secure=False,
        interactive=True,
        path=tuple(before.get("path", [])),
    )
    return is_sensitive(element)


def compile_trace(entries: list[dict], name: str, goal: str) -> Workflow:
    """Deterministic: the same `entries` always produce byte-identical YAML."""
    entries = [e for e in entries if e.get("kind") != "header"]
    entries = _collapse_duplicate_focus(entries)

    secrets: dict[str, SecretRef] = {}
    steps: list[Step] = []
    launch_steps: dict[int, str] = {}  # launch_id -> step id
    for i, entry in enumerate(entries, start=1):
        step_id = f"step_{i:02d}"
        kind = entry.get("kind")
        if kind == "launch":
            steps.append(Step(id=step_id, launch=entry["target"]))
            if entry.get("launch_id") is not None:
                launch_steps[entry["launch_id"]] = step_id
        elif kind == "act":
            steps.append(Step(
                id=step_id,
                act=entry["action"],
                root=_compile_root(entry["root"], launch_steps),
                target={"locators": entry["locators"]} if entry["locators"] else None,
                value=_compile_value(entry["value"], secrets),
                expect=_compile_expect(entry.get("expect_candidates") or []),
                confirm="once" if _is_sensitive_before(entry.get("before") or {}) else None,
            ))
        else:
            raise RpaError(f"compile_trace: unknown trace entry kind {kind!r}")

    return Workflow(name=name, description=goal, secrets=secrets, steps=steps)


def _check_keys(op: dict, allowed: set[str]) -> None:
    extra = set(op) - allowed
    if extra:
        raise RpaError(f"apply_cleanup: unknown field(s) {sorted(extra)} for op {op.get('op')!r}")


def _require_step(steps: dict[str, Step], step_id: Any) -> Step:
    if not isinstance(step_id, str) or step_id not in steps:
        raise RpaError(f"apply_cleanup: unknown step {step_id!r}")
    return steps[step_id]


def apply_cleanup(workflow: Workflow, ops: list[dict]) -> Workflow:
    """Apply `ops` (delete/rename/param/flag only) and re-validate the result."""
    steps: dict[str, Step] = {s.id: s for s in workflow.steps}
    order: list[str] = [s.id for s in workflow.steps]
    params = dict(workflow.params)

    for op in ops:
        kind = op.get("op")

        if kind == "delete":
            _check_keys(op, _DELETE_KEYS)
            _require_step(steps, op.get("step"))
            step_id = op["step"]
            del steps[step_id]
            order.remove(step_id)

        elif kind == "rename":
            _check_keys(op, _RENAME_KEYS)
            step = _require_step(steps, op.get("step"))
            new_id = op.get("to")
            if not isinstance(new_id, str) or not _STEP_ID_RE.match(new_id):
                raise RpaError(f"apply_cleanup: rename.to must match ^[a-z0-9_]+$, got {new_id!r}")
            if new_id != step.id and new_id in steps:
                raise RpaError(f"apply_cleanup: step id {new_id!r} already exists")
            del steps[step.id]
            order[order.index(step.id)] = new_id
            steps[new_id] = replace(step, id=new_id)

        elif kind == "param":
            _check_keys(op, _PARAM_KEYS)
            step = _require_step(steps, op.get("step"))
            if op.get("field") != "value":
                raise RpaError(f"apply_cleanup: param.field must be 'value', got {op.get('field')!r}")
            name = op.get("name")
            if not isinstance(name, str) or not name:
                raise RpaError("apply_cleanup: param.name is required")
            params[name] = Param(default=op.get("default"))
            steps[step.id] = replace(step, value=f"{{{{ {name} }}}}")

        elif kind == "flag":
            _check_keys(op, _FLAG_KEYS)
            step = _require_step(steps, op.get("step"))
            updates: dict[str, Any] = {}
            if "confirm" in op:
                confirm = op["confirm"]
                if confirm not in (None, "once", "every_run"):
                    raise RpaError(f"apply_cleanup: flag.confirm must be once/every_run/null, got {confirm!r}")
                updates["confirm"] = confirm
            if "sensitive" in op:
                updates["sensitive"] = bool(op["sensitive"])
            if "expect_file" in op:
                updates["expect"] = {"file_exists": op["expect_file"], "timeout": 10}
            steps[step.id] = replace(step, **updates)

        else:
            raise RpaError(f"apply_cleanup: unknown cleanup op {kind!r}")

    new_workflow = replace(workflow, params=params, steps=[steps[sid] for sid in order])
    # Re-validate through a full parse round-trip; this also rejects any state an
    # op above should never have been able to reach (e.g. a locator sneaking in).
    return parse_workflow(yaml.safe_load(dump_workflow(new_workflow)))
