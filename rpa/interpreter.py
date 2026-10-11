"""rpa/interpreter.py — run a workflow step by step with no model calls (Subtask 15).

See plan.md Subtask 15 and research.md D1 (interpreter loop), D2 (locator ladder /
degraded), D5 (confirm once/every_run + content hashes), D7 (resume from step N only
if its pre-check passes), D8. The interpreter never guesses: an ambiguous or missing
locator halts; a changed, unapproved `confirm: once` step halts; secrets are rendered
into values only, never written to `run.json`, `outline.txt` or a halt reason.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from rpa import RpaError
from rpa.drivers.base import Driver, WrongElement
from rpa.lock import DesktopLock
from rpa.model import Root
from rpa.observe import format_outline
from rpa.resolver import Ambiguous, NotFound, resolve
from rpa.screen import to_png_bytes
from rpa.store import WorkflowStore
from rpa.workflow import Step, render, resolve_secrets

__all__ = ["RunResult", "StepLog", "run_workflow"]

_ROOT_WAIT_S = 10.0
_EXPECT_DEFAULT_TIMEOUT_S = 10.0
_RETRY_BACKOFF_S = 1.0
_ROOT_POLL_S = 0.2
_EXPECT_POLL_S = 0.2

_SINGLE_PLACEHOLDER_RE = re.compile(r"^\{\{\s*([A-Za-z0-9_]+)\s*\}\}$")


@dataclass
class StepLog:
    """One logged step (or one `for_each` item) execution."""

    step_id: str
    rung_index: int | None
    ms: float
    status: str  # "ok" | "degraded" | "skipped" | "failed" | "halted"


@dataclass
class RunResult:
    status: str  # "ok" | "degraded" | "halted"
    halted_step: str | None
    reason: str | None
    steps: list[StepLog]
    run_dir: Path
    launched: list[Root] = field(default_factory=list)  # windows/tabs this run opened


class _Halt(RpaError):
    """Internal signal: stop the run now. `root` is the halting root, if any."""

    def __init__(self, reason: str, root: Root | None = None) -> None:
        self.reason = reason
        self.root = root
        super().__init__(reason)


class _NeedsApproval(RpaError):
    """A confirm gate refused; never retried."""


class _ExpectTimeout(RpaError):
    """An `expect` condition never became true within its timeout."""


_CANCELLED = "cancelled by the Admiral"
_MIN_REDACTABLE = 4  # shorter secrets withhold outline.txt rather than redact it

_RETRYABLE = (Ambiguous, NotFound, WrongElement, _ExpectTimeout)


def run_workflow(
    store: WorkflowStore,
    name: str,
    *,
    drivers: dict[str, Driver],
    params: dict[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    confirm: Callable[[Step, str], bool] | None = None,
    start_at: str | None = None,
    verify: bool = False,
    lock: DesktopLock | None = None,
    agent: str = "rpa-run",
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> RunResult:
    """Run workflow `name` from `store` step by step; no model calls.

    Each step renders its templates, finds its root, is pre-checked, resolved,
    confirmed, locked if the action needs real input, acted on, and `expect`-
    checked. A halt writes evidence to `store.dir(name)/"runs"/<ts>/`.
    `cancelled()` (ESC) is checked before every step and in every wait/poll,
    and halts the run with "cancelled by the Admiral".
    """
    wait = sleep

    def sleep(seconds: float) -> None:  # every poll and backoff is a cancel point
        if cancelled():
            raise _Halt(_CANCELLED)
        wait(seconds)

    workflow = store.load(name)
    started_at = now() if now is not None else datetime.now(timezone.utc)
    today = started_at.date()

    ctx = _build_context(workflow, params, environ, today)
    secret_values = [v for v in ctx["secrets"].values() if v]

    ts = started_at.strftime("%Y%m%dT%H%M%S%f") + "Z"
    run_dir = store.dir(name) / "runs" / ts
    ctx["run_dir"] = str(run_dir)

    logs: list[StepLog] = []
    extra_roots: dict[str, Root] = {}
    lock_taken = [False]

    halted_step: str | None = None
    halt_reason: str | None = None
    halt_root: Root | None = None
    any_degraded = False

    steps = workflow.steps
    start_index = 0
    if start_at is not None:
        ids = [s.id for s in steps]
        if start_at not in ids:
            raise RpaError(f"start_at: unknown step id {start_at!r}")
        start_index = ids.index(start_at)

    try:
        for i, step in enumerate(steps):
            if i < start_index:
                continue
            is_start_step = start_at is not None and i == start_index
            try:
                if cancelled():
                    raise _Halt(_CANCELLED)
                if step.for_each is not None:
                    for item in _for_each_items(step.for_each, ctx):
                        item_ctx = dict(ctx, item=item)
                        log, _root = _dispatch_step(
                            step, drivers, item_ctx, today, store, name, confirm, verify,
                            lock, agent, sleep, clock, extra_roots, is_start_step, lock_taken,
                        )
                        logs.append(log)
                        any_degraded = any_degraded or log.status == "degraded"
                else:
                    log, _root = _dispatch_step(
                        step, drivers, ctx, today, store, name, confirm, verify,
                        lock, agent, sleep, clock, extra_roots, is_start_step, lock_taken,
                    )
                    logs.append(log)
                    any_degraded = any_degraded or log.status == "degraded"
            except _Halt as halt:
                halted_step = step.id
                halt_reason = halt.reason
                halt_root = halt.root
                logs.append(StepLog(step.id, None, 0.0, "halted"))
                break
    finally:
        if lock is not None and lock_taken[0]:
            lock.release(agent)

    status = "halted" if halted_step is not None else ("degraded" if any_degraded else "ok")

    if verify and status == "ok":
        store.mark_verified(name)

    def _redact(text: str | None) -> str | None:
        if text is None:
            return None
        for value in secret_values:
            text = text.replace(value, "[secret]")
        return text

    reason = _redact(halt_reason)
    ended_at = now() if now is not None else datetime.now(timezone.utc)

    run_dir.mkdir(parents=True, exist_ok=True)
    run_json = {
        "name": name,
        "status": status,
        "halted_step": halted_step,
        "reason": reason,
        "steps": [
            {"step_id": s.step_id, "rung_index": s.rung_index, "ms": s.ms, "status": s.status}
            for s in logs
        ],
        "params": {k: v for k, v in ctx.items() if k not in ("secrets", "run_dir")},
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
    }
    (run_dir / "run.json").write_text(
        json.dumps(run_json, indent=2, sort_keys=True, default=str), encoding="utf-8"
    )
    store.record_run(name, status, reason=reason, run_dir=run_dir, verify=verify)

    if halted_step is not None and halt_root is not None:
        driver = drivers.get(halt_root.kind)
        if driver is not None:
            try:
                # Literal redaction of a 1–3 character secret would garble the whole
                # outline and still be guessable: withhold the outline instead.
                if any(len(v) < _MIN_REDACTABLE for v in secret_values):
                    outline_text = "[outline withheld: a secret is too short to redact safely]"
                else:
                    outline_text = _redact(format_outline(driver.outline(halt_root)))
                (run_dir / "outline.txt").write_text(outline_text or "", encoding="utf-8")
            except Exception:
                pass
            try:
                image = driver.screenshot(halt_root)
                (run_dir / "halt.png").write_bytes(to_png_bytes(image))
            except Exception:
                pass

    launched = list({r.id: r for key, r in extra_roots.items() if key.startswith("@")}.values())
    return RunResult(status=status, halted_step=halted_step, reason=reason, steps=logs, run_dir=run_dir,
                     launched=launched)


# -- context / templating ---------------------------------------------------


def _build_context(workflow, params, environ, today: date) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for pname, p in workflow.params.items():
        default = p.default
        ctx[pname] = render(default, {}, now=today) if isinstance(default, str) else default
    for key, value in (params or {}).items():
        ctx[key] = value
    env = dict(environ) if environ is not None else dict(os.environ)
    ctx["secrets"] = resolve_secrets(workflow, env)
    return ctx


def _deep_render(obj: Any, ctx: dict, today: date) -> Any:
    if isinstance(obj, str):
        return render(obj, ctx, now=today)
    if isinstance(obj, dict):
        return {k: _deep_render(v, ctx, today) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_render(v, ctx, today) for v in obj]
    return obj


def _for_each_items(expr: str, ctx: dict) -> list:
    match = _SINGLE_PLACEHOLDER_RE.match(expr.strip())
    name = match.group(1) if match else None
    value = ctx.get(name) if name else None
    if value is None:
        raise RpaError(f"for_each: unknown or empty param {expr!r}")
    if isinstance(value, str):
        return [line for line in value.splitlines() if line]
    if isinstance(value, list):
        return list(value)
    raise RpaError(f"for_each: {expr!r} is not a list or a newline-delimited string")


# -- step dispatch -----------------------------------------------------------


def _dispatch_step(
    step, drivers, ctx, today, store, name, confirm, verify, lock, agent, sleep, clock,
    extra_roots, is_start_step, lock_taken,
) -> tuple[StepLog, Root | None]:
    if step.launch is not None:
        return _run_launch_step(step, drivers, ctx, today, extra_roots, sleep, clock)
    return _run_act_step(
        step, drivers, ctx, today, store, name, confirm, verify, lock, agent,
        sleep, clock, extra_roots, is_start_step, lock_taken,
    )


def _ms(t0: float, clock: Callable[[], float]) -> float:
    return (clock() - t0) * 1000.0


def _run_launch_step(step, drivers, ctx, today, extra_roots, sleep, clock) -> tuple[StepLog, Root | None]:
    t0 = clock()
    target = render(step.launch, ctx, now=today)
    is_url = target.startswith("http://") or target.startswith("https://")
    kind = "browser" if is_url else "window"
    driver = drivers[kind]
    try:
        new_root = driver.launch(target)
    except RpaError as exc:
        raise _Halt(str(exc)) from exc
    extra_roots[new_root.id] = new_root
    extra_roots["@" + step.id] = new_root  # for root.*.launched_by
    try:
        _check_expect(step, driver, drivers, new_root, [], ctx, today, sleep, clock)
    except _ExpectTimeout as exc:
        if step.on_fail == "continue":
            return StepLog(step.id, None, _ms(t0, clock), "failed"), new_root
        raise _Halt(str(exc), new_root) from exc
    return StepLog(step.id, None, _ms(t0, clock), "ok"), new_root


def _run_act_step(
    step, drivers, ctx, today, store, name, confirm, verify, lock, agent, sleep, clock,
    extra_roots, is_start_step, lock_taken,
) -> tuple[StepLog, Root | None]:
    t0 = clock()
    rendered_value = _deep_render(step.value, ctx, today)
    locators = _deep_render((step.target or {}).get("locators") or [], ctx, today)
    root_spec = _deep_render(step.root, ctx, today)

    root: Root | None = None
    if root_spec is not None:
        try:
            root = _find_root(root_spec, drivers, extra_roots, sleep, clock)
        except _Halt:
            if is_start_step:
                raise _Halt("pre-check failed")
            raise

    # Observing can change the desktop (UIA restores a minimized window): take the
    # lock before the first find, not only before the act.
    if root is not None and lock is not None and drivers[root.kind].needs_desktop_lock_to_observe(root):
        lock.acquire(agent)
        lock_taken[0] = True

    if step.act == "close_window" and not locators:  # close the root window/tab itself
        if root is None:
            raise _Halt("close_window without a target needs a root")
        try:
            _confirm_gate(step, store, name, confirm, verify)
            drivers[root.kind].close_root(root)
        except _NeedsApproval as exc:
            raise _Halt(str(exc), root) from exc
        except RpaError as exc:
            if step.on_fail == "continue":
                return StepLog(step.id, None, _ms(t0, clock), "failed"), root
            raise _Halt(str(exc), root) from exc
        return StepLog(step.id, 0, _ms(t0, clock), "ok"), root

    if is_start_step:
        if root is None:
            raise _Halt("pre-check failed")
        try:
            resolve(drivers[root.kind], root, locators, allow_coords=step.allow_coords)
        except (Ambiguous, NotFound) as exc:
            raise _Halt("pre-check failed", root) from exc

    if step.if_present is not None:
        if_present = _deep_render(step.if_present, ctx, today)
        try:
            resolve(drivers[root.kind], root, [if_present], allow_coords=step.allow_coords)
        except NotFound:
            return StepLog(step.id, None, _ms(t0, clock), "skipped"), root
        except Ambiguous:
            pass  # present, just not unique — proceed

    attempts = max(1, step.retry + 1)
    rung_index: int | None = None
    failure_reason: str | None = None
    driver = drivers[root.kind] if root is not None else None

    for attempt in range(attempts):
        try:
            resolution = resolve(driver, root, locators, allow_coords=step.allow_coords)
            _confirm_gate(step, store, name, confirm, verify)
            if driver.needs_desktop_lock(step.act) or driver.needs_desktop_lock_to_observe(root):
                if lock is not None:
                    lock.acquire(agent)
                    lock_taken[0] = True
            driver.act(root, resolution.element, step.act, rendered_value)
            _check_expect(step, driver, drivers, root, locators, ctx, today, sleep, clock)
            rung_index = resolution.rung_index
            failure_reason = None
            break
        except _NeedsApproval as exc:
            failure_reason = str(exc)
            break  # not retryable
        except _RETRYABLE as exc:
            failure_reason = str(exc)
            if attempt + 1 < attempts:
                sleep(_RETRY_BACKOFF_S)
                continue
            break

    if failure_reason is not None:
        if step.on_fail == "continue":
            return StepLog(step.id, None, _ms(t0, clock), "failed"), root
        raise _Halt(failure_reason, root)

    status = "ok" if rung_index == 0 else "degraded"
    return StepLog(step.id, rung_index, _ms(t0, clock), status), root


# -- root finding -------------------------------------------------------------


def _find_root(root_spec: dict, drivers: dict[str, Driver], extra_roots: dict[str, Root], sleep, clock) -> Root:
    kind = "window" if "window" in root_spec else "browser"
    sub = root_spec[kind] or {}
    pattern = sub.get("title_re") if kind == "window" else sub.get("url_re")
    driver = drivers[kind]
    deadline = clock() + _ROOT_WAIT_S

    launched_by = sub.get("launched_by")
    if launched_by is not None and ("@" + launched_by) in extra_roots:
        # Bound to the window/tab its launch step opened: titles change, it does not.
        mine = extra_roots["@" + launched_by]
        while True:
            if any(r.id == mine.id for r in driver.roots()):
                return mine
            if clock() >= deadline:
                raise _Halt(f"the {kind} opened by {launched_by!r} is gone")
            sleep(_ROOT_POLL_S)
    # No launched_by, or its launch step was skipped (start_at): match by pattern.

    while True:
        candidates: dict[str, Root] = {r.id: r for r in driver.roots()}
        for r in extra_roots.values():
            if r.kind == kind:
                candidates[r.id] = r
        matched = [
            r for r in candidates.values()
            if pattern is None
            or re.search(pattern, (r.title if kind == "window" else (r.url or "")))
        ]
        launched = [r for r in matched if r.id in extra_roots]
        if launched:  # a window/tab this run launched beats a lookalike the user had open
            matched = launched
        if len(matched) > 1:
            raise _Halt(f"ambiguous root: {pattern!r} matched {len(matched)} roots")
        if len(matched) == 1:
            return matched[0]
        if clock() >= deadline:
            raise _Halt(f"root not found: {pattern!r}")
        sleep(_ROOT_POLL_S)


# -- confirm gate -------------------------------------------------------------


def _confirm_gate(step, store, name, confirm, verify) -> None:
    if step.confirm is None:
        return
    question = f'Confirm {step.act} on step {step.id!r}?'
    if step.confirm == "once" and not verify:
        if not store.confirm_ok(name, step):
            raise _NeedsApproval("needs approval")
        return
    if confirm is None:
        raise _NeedsApproval("needs approval")
    if not confirm(step, question):
        raise _NeedsApproval("denied")


# -- expect -------------------------------------------------------------------


def _check_expect(step, driver, drivers, root, locators, ctx, today, sleep, clock) -> None:
    expect = step.expect
    if not expect:
        return
    timeout = expect.get("timeout", _EXPECT_DEFAULT_TIMEOUT_S)
    keys = [k for k in expect if k != "timeout"]
    if not keys:
        return
    key = keys[0]
    spec = _deep_render(expect[key], ctx, today)
    deadline = clock() + timeout

    while True:
        if _expect_ok(key, spec, driver, drivers, root, locators, step):
            return
        if clock() >= deadline:
            raise _ExpectTimeout(f"expect.{key} timed out after {timeout}s")
        sleep(_EXPECT_POLL_S)


def _expect_ok(key, spec, driver, drivers, root, locators, step) -> bool:
    if key == "present":
        return len(driver.find(root, spec)) >= 1
    if key == "gone":
        return len(driver.find(root, spec)) == 0
    if key == "window":
        pattern = spec.get("title_re") if isinstance(spec, dict) else spec
        if not pattern:
            return True
        return any(re.search(pattern, r.title) for r in drivers["window"].roots())
    if key == "text":
        contains = spec.get("contains") if isinstance(spec, dict) else spec
        return contains in format_outline(driver.outline(root))
    if key == "value_equals":
        wanted = spec.get("value") if isinstance(spec, dict) else spec
        try:
            resolution = resolve(driver, root, locators, allow_coords=step.allow_coords)
        except (Ambiguous, NotFound):
            return False
        return resolution.element.value == wanted
    if key == "file_exists":
        path = spec.get("path") if isinstance(spec, dict) else spec
        return Path(path).exists()
    return False
