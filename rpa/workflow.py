"""rpa/workflow.py — D1 workflow format: dataclasses, validation, templating, hashing.

A workflow is a YAML document with top-level keys `name`, `description`, `params`,
`secrets` and `steps` (see the D1 decision in `research.md` and Subtask 12 of
`plan.md`). Unknown keys anywhere raise `RpaError` naming the key path, e.g.
`"steps[3].targt"`. `code:` steps (the v1 escape hatch) are rejected outright —
see the "Open Issues" note in plan.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from rpa import RpaError
from rpa.keys import parse_chord
from rpa.model import ACTIONS, validate_locator

__all__ = [
    "Param",
    "SecretRef",
    "Step",
    "Workflow",
    "load_workflow",
    "parse_workflow",
    "dump_workflow",
    "render",
    "resolve_secrets",
    "step_hash",
]

_TOP_KEYS = {"name", "description", "params", "secrets", "steps"}
_PARAM_KEYS = {"default"}
_SECRET_KEYS = {"env"}
_STEP_KEYS = {
    "id", "act", "launch", "root", "target", "value", "expect", "confirm",
    "sensitive", "allow_coords", "retry", "on_fail", "for_each", "if_present",
}
_ROOT_KEYS = {"window", "browser"}
_TARGET_KEYS = {"locators", "image"}
_CONFIRM_VALUES = {"once", "every_run"}
_ON_FAIL_VALUES = {"halt", "continue"}
_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SECRET_REF_RE = re.compile(r"\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")


@dataclass(frozen=True)
class Param:
    """A declared workflow parameter. `default` may itself be a template string."""

    default: Any = None


@dataclass(frozen=True)
class SecretRef:
    """A declared secret, resolved from an environment variable at run time only."""

    env: str


@dataclass(frozen=True)
class Step:
    """One workflow step. Exactly one of `act` / `launch` is set."""

    id: str
    act: str | None = None
    launch: str | None = None
    root: dict | None = None
    target: dict | None = None
    value: Any = None
    expect: dict | None = None
    confirm: str | None = None
    sensitive: bool = False
    allow_coords: bool = False
    retry: int = 0
    on_fail: str = "halt"
    for_each: str | None = None
    if_present: dict | None = None


@dataclass(frozen=True)
class Workflow:
    """A parsed, validated workflow."""

    name: str
    description: str = ""
    params: dict[str, Param] = field(default_factory=dict)
    secrets: dict[str, SecretRef] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)


def _check_unknown(d: dict, allowed: set[str], ctx: str) -> None:
    for key in d:
        if key not in allowed:
            raise RpaError(f"unknown key: {ctx}{key}")


def _iter_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _check_secret_refs(obj: Any, ctx: str, declared: set[str]) -> None:
    for text in _iter_strings(obj):
        for secret_name in _SECRET_REF_RE.findall(text):
            if secret_name not in declared:
                raise RpaError(f"{ctx}undeclared secret: secrets.{secret_name}")


def parse_workflow(data: dict) -> Workflow:
    """Validate a raw YAML-loaded dict and build a `Workflow`. Raises `RpaError`."""
    if not isinstance(data, dict):
        raise RpaError("workflow: must be a mapping")
    _check_unknown(data, _TOP_KEYS, "")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise RpaError("name: is required")
    description = data.get("description", "")

    params: dict[str, Param] = {}
    for pname, pdata in (data.get("params") or {}).items():
        pdata = pdata or {}
        _check_unknown(pdata, _PARAM_KEYS, f"params.{pname}.")
        params[pname] = Param(default=pdata.get("default"))

    secrets: dict[str, SecretRef] = {}
    for sname, sdata in (data.get("secrets") or {}).items():
        sdata = sdata or {}
        _check_unknown(sdata, _SECRET_KEYS, f"secrets.{sname}.")
        env = sdata.get("env")
        if not env:
            raise RpaError(f"secrets.{sname}.env: is required")
        secrets[sname] = SecretRef(env=env)
    declared_secrets = set(secrets)

    steps: list[Step] = []
    seen_ids: set[str] = set()
    for i, sdata in enumerate(data.get("steps") or []):
        ctx = f"steps[{i}]."
        if not isinstance(sdata, dict):
            raise RpaError(f"{ctx[:-1]}: must be a mapping")
        if "code" in sdata:
            raise RpaError("code steps are not supported in v1")
        _check_unknown(sdata, _STEP_KEYS, ctx)

        step_id = sdata.get("id")
        if not isinstance(step_id, str) or not _ID_RE.match(step_id):
            raise RpaError(f"{ctx}id: must match ^[a-z0-9_]+$, got {step_id!r}")
        if step_id in seen_ids:
            raise RpaError(f"{ctx}id: duplicate step id {step_id!r}")
        seen_ids.add(step_id)

        act = sdata.get("act")
        launch = sdata.get("launch")
        if (act is None) == (launch is None):
            raise RpaError(f"{ctx}: exactly one of 'act' or 'launch' is required")
        if act is not None and act not in ACTIONS:
            raise RpaError(f"{ctx}act: unknown action {act!r}")

        root = sdata.get("root")
        if root is not None:
            if not isinstance(root, dict):
                raise RpaError(f"{ctx}root: must be a mapping")
            _check_unknown(root, _ROOT_KEYS, f"{ctx}root.")
            if len(root) != 1:
                raise RpaError(f"{ctx}root: exactly one of 'window' or 'browser' is required")
            if "window" in root:
                _check_unknown(root["window"] or {}, {"title_re"}, f"{ctx}root.window.")
            else:
                _check_unknown(root["browser"] or {}, {"url_re"}, f"{ctx}root.browser.")

        target = sdata.get("target")
        if target is not None:
            if not isinstance(target, dict):
                raise RpaError(f"{ctx}target: must be a mapping")
            _check_unknown(target, _TARGET_KEYS, f"{ctx}target.")
            for j, loc in enumerate(target.get("locators") or []):
                try:
                    validate_locator(loc)
                except RpaError as exc:
                    raise RpaError(f"{ctx}target.locators[{j}]: {exc}") from exc

        value = sdata.get("value")
        expect = sdata.get("expect")
        if expect is not None and not isinstance(expect, dict):
            raise RpaError(f"{ctx}expect: must be a mapping")

        confirm = sdata.get("confirm")
        if confirm is not None and confirm not in _CONFIRM_VALUES:
            raise RpaError(f"{ctx}confirm: must be 'once' or 'every_run', got {confirm!r}")

        sensitive = bool(sdata.get("sensitive", False))
        allow_coords = bool(sdata.get("allow_coords", False))
        retry = int(sdata.get("retry", 0))

        on_fail = sdata.get("on_fail", "halt")
        if on_fail not in _ON_FAIL_VALUES:
            raise RpaError(f"{ctx}on_fail: must be 'halt' or 'continue', got {on_fail!r}")

        for_each = sdata.get("for_each")
        if_present = sdata.get("if_present")
        if if_present is not None:
            try:
                validate_locator(if_present)
            except RpaError as exc:
                raise RpaError(f"{ctx}if_present: {exc}") from exc

        if act == "key" and value is not None and "{{" not in str(value):
            parse_chord(value)

        _check_secret_refs(sdata, ctx, declared_secrets)

        steps.append(Step(
            id=step_id, act=act, launch=launch, root=root, target=target, value=value,
            expect=expect, confirm=confirm, sensitive=sensitive, allow_coords=allow_coords,
            retry=retry, on_fail=on_fail, for_each=for_each, if_present=if_present,
        ))

    return Workflow(name=name, description=description, params=params, secrets=secrets, steps=steps)


def load_workflow(path: str | Path) -> Workflow:
    """Read and parse a `workflow.yaml` file."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return parse_workflow(data)


_STEP_ORDER = (
    "act", "launch", "root", "target", "value", "expect", "confirm", "sensitive",
    "allow_coords", "retry", "on_fail", "for_each", "if_present",
)
_STEP_DEFAULTS: dict[str, Any] = {
    "act": None, "launch": None, "root": None, "target": None, "value": None,
    "expect": None, "confirm": None, "sensitive": False, "allow_coords": False,
    "retry": 0, "on_fail": "halt", "for_each": None, "if_present": None,
}


def _step_to_dict(step: Step, *, include_defaults: bool = False) -> dict:
    out: dict[str, Any] = {"id": step.id}
    for key in _STEP_ORDER:
        value = getattr(step, key)
        if not include_defaults and value == _STEP_DEFAULTS[key]:
            continue
        out[key] = value
    return out


def dump_workflow(workflow: Workflow) -> str:
    """Render a `Workflow` back to YAML text with a stable key order."""
    data: dict[str, Any] = {"name": workflow.name}
    if workflow.description:
        data["description"] = workflow.description
    if workflow.params:
        data["params"] = {n: {"default": p.default} for n, p in workflow.params.items()}
    if workflow.secrets:
        data["secrets"] = {n: {"env": s.env} for n, s in workflow.secrets.items()}
    data["steps"] = [_step_to_dict(s) for s in workflow.steps]
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False, allow_unicode=True)


_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")
_FILTER_CALL_RE = re.compile(r"^(\w+)\((.*)\)$")


def _resolve_name(name: str, ctx: dict, now: date) -> Any:
    if name == "today":
        return now
    if name == "yesterday":
        return now - timedelta(days=1)
    if "." in name:
        base, _, rest = name.partition(".")
        sub = ctx.get(base)
        if not isinstance(sub, dict) or rest not in sub:
            raise RpaError(f"render: unknown name {name!r}")
        return sub[rest]
    if name not in ctx:
        raise RpaError(f"render: unknown name {name!r}")
    return ctx[name]


def _apply_filter(filter_expr: str, value: Any) -> Any:
    match = _FILTER_CALL_RE.match(filter_expr.strip())
    if not match or match.group(1) != "date":
        raise RpaError(f"render: unknown filter {filter_expr!r}")
    fmt = match.group(2).strip().strip("'\"")
    return value.strftime(fmt)


def render(text: str, ctx: dict, *, now: date | None = None) -> str:
    """Minimal templater: `{{ name }}`, dotted names, `today`/`yesterday`, `| date(fmt)`."""
    if "{{" not in text:
        return text
    effective_now = now if now is not None else date.today()

    def _sub(match: re.Match) -> str:
        parts = [p.strip() for p in match.group(1).split("|")]
        value = _resolve_name(parts[0], ctx, effective_now)
        for filter_expr in parts[1:]:
            value = _apply_filter(filter_expr, value)
        return str(value)

    return _TEMPLATE_RE.sub(_sub, text)


def resolve_secrets(workflow: Workflow, environ: dict[str, str]) -> dict[str, str]:
    """Look up every declared secret's env var. Missing var → RpaError naming the var, never the value."""
    out: dict[str, str] = {}
    for name, ref in workflow.secrets.items():
        if ref.env not in environ:
            raise RpaError(f"secret {name!r}: environment variable {ref.env!r} is not set")
        out[name] = environ[ref.env]
    return out


def workflow_hash(workflow: Workflow) -> str:
    """sha256 hex of the whole workflow's content (independent of YAML layout)."""
    data = {
        "name": workflow.name,
        "description": workflow.description,
        "params": {k: v.default for k, v in sorted(workflow.params.items())},
        "secrets": {k: v.env for k, v in sorted(workflow.secrets.items())},
        "steps": [step_hash(s) for s in workflow.steps],
    }
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def step_hash(step: Step) -> str:
    """sha256 hex of the canonical JSON (sorted keys, compact) of the step's full field set."""
    data = _step_to_dict(step, include_defaults=True)
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
