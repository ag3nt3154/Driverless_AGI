"""rpa/__main__.py — `python -m rpa`: run a workflow from the shell, approve it,
list and show workflows (Subtask 16). No model calls; `rpa/` stays agent-free so
this works with no dagi process running.

Exit codes for `run`: 0 ok, 1 degraded, 2 halted, 3 usage/config error (an
RpaError or an unknown workflow before/around the run, or a bad `--param`).
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import threading
from pathlib import Path
from typing import Callable

from rpa import RpaError
from rpa.hotkey import EscWatcher
from rpa.interpreter import RunResult, run_workflow
from rpa.lock import DesktopLock
from rpa.safety import is_allow_answer
from rpa.store import WorkflowStore
from rpa.workflow import Step

__all__ = ["main"]

_RPA_SUBPATH = Path(".dagi") / "rpa"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpa")
    parser.add_argument("--project", default=None, help="Project root (default: cwd).")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Run a workflow step by step.")
    run_p.add_argument("name")
    run_p.add_argument("--param", action="append", default=[], help="key=value, repeatable.")
    run_p.add_argument("--from-step", dest="from_step", default=None)
    run_p.add_argument("--verify", action="store_true")

    approve_p = sub.add_parser("approve", help="Approve a workflow after a clean verify run.")
    approve_p.add_argument("name")

    sub.add_parser("list", help="List workflows.")

    show_p = sub.add_parser("show", help="Show a workflow's YAML and state.")
    show_p.add_argument("name")

    return parser


def _parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise RpaError(f"--param must be key=value, got {pair!r}")
        params[key] = value
    return params


def _default_drivers(project: Path) -> dict:
    from rpa.drivers.browser import FirefoxDriver
    from rpa.drivers.uia import UiaDriver

    return {
        "window": UiaDriver(),
        "browser": FirefoxDriver(profile_dir=project / _RPA_SUBPATH / "firefox-profile"),
    }


def _quit_browser(drivers: dict) -> None:
    browser = drivers.get("browser") if hasattr(drivers, "get") else None
    quit_fn = getattr(browser, "quit", None)
    if quit_fn is not None:
        try:
            quit_fn()
        except Exception:  # noqa: BLE001 — shutdown must never mask the run's exit code
            pass


def _print_run_summary(result: RunResult) -> None:
    print(f"status: {result.status}")
    print(f"steps: {len(result.steps)}")
    for log in result.steps:
        rung = f" (rung {log.rung_index})" if log.rung_index else ""
        print(f"  {log.step_id}: {log.status}{rung}")
    if result.halted_step is not None:
        print(f"halted step: {result.halted_step}")
        print(f"reason: {result.reason}")
    print(f"run dir: {result.run_dir}")


def _run_cmd(
    args, store: WorkflowStore, drivers: dict, input_fn: Callable[[str], str], isatty: Callable[[], bool],
    watch_escape: bool = True,
) -> int:
    try:
        params = _parse_params(args.param)
    except RpaError as exc:
        print(f"rpa: {exc}", file=sys.stderr)
        return 3

    if args.name not in store.list():
        print(f"rpa: unknown workflow {args.name!r}", file=sys.stderr)
        return 3

    state = store.state(args.name)
    if state["status"] != "approved" and not args.verify:
        print(
            f"rpa: warning: workflow {args.name!r} is not approved; "
            "run with --verify, then `rpa approve`.",
            file=sys.stderr,
        )

    def confirm(step: Step, question: str) -> bool:
        if not isatty():
            return False
        answer = input_fn(f"Confirm step {step.id!r}: {question} [y/N] ")
        return is_allow_answer(answer, "y")

    try:
        stop = threading.Event()
        # Esc anywhere stops the run (a real keyboard hook: only with real drivers).
        with EscWatcher(stop.set) if watch_escape else contextlib.nullcontext():
            result = run_workflow(
                store, args.name, drivers=drivers, params=params, confirm=confirm,
                start_at=args.from_step, verify=args.verify, lock=DesktopLock(), agent="rpa-cli",
                cancelled=stop.is_set,
            )
    except RpaError as exc:
        print(f"rpa: {exc}", file=sys.stderr)
        return 3

    _print_run_summary(result)
    return {"ok": 0, "degraded": 1, "halted": 2}[result.status]


def _approve_cmd(
    args, store: WorkflowStore, input_fn: Callable[[str], str], isatty: Callable[[], bool],
) -> int:
    if args.name not in store.list():
        print(f"rpa: unknown workflow {args.name!r}", file=sys.stderr)
        return 3

    workflow = store.load(args.name)
    confirm_steps = [s.id for s in workflow.steps if s.confirm]
    if confirm_steps:
        print(f"Pre-approving confirm steps: {', '.join(confirm_steps)}")
    else:
        print("No confirm steps.")

    if not isatty():
        print("rpa: approve requires a TTY", file=sys.stderr)
        return 3

    answer = input_fn(f"Approve {args.name!r}? [y/N] ")
    if not is_allow_answer(answer, "y"):
        print("rpa: not approved", file=sys.stderr)
        return 3

    try:
        store.approve(args.name)
    except RpaError as exc:
        print(f"rpa: {exc}", file=sys.stderr)
        return 3

    print(f"approved {args.name!r}")
    return 0


def _list_cmd(store: WorkflowStore) -> int:
    names = store.list()
    if not names:
        print("(no workflows)")
        return 0
    for name in names:
        state = store.state(name)
        last_run = state.get("last_run") or {}
        last_at = last_run.get("at")
        last_str = f"{last_at:.0f}" if isinstance(last_at, (int, float)) else "never"
        print(f"{name} | {store.display_status(name)} | last run: {last_str}")
    return 0


def _show_cmd(args, store: WorkflowStore) -> int:
    if args.name not in store.list():
        print(f"rpa: unknown workflow {args.name!r}", file=sys.stderr)
        return 3
    yaml_path = store.dir(args.name) / "workflow.yaml"
    print(yaml_path.read_text(encoding="utf-8"))
    state = store.state(args.name)
    print(f"status: {state['status']}")
    last_run = state.get("last_run") or {}
    if last_run:
        print(f"last run: {last_run.get('status')} ({last_run.get('reason') or 'no reason'})")
    return 0


def main(
    argv: "list[str] | None" = None,
    *,
    drivers: "dict | None" = None,
    store: "WorkflowStore | None" = None,
    input_fn: Callable[[str], str] = input,
    isatty: Callable[[], bool] = sys.stdin.isatty,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return 3

    if args.command is None:
        parser.print_usage(sys.stderr)
        return 3

    project = Path(args.project) if args.project else Path.cwd()
    if store is None:
        store = WorkflowStore(project / _RPA_SUBPATH)

    if args.command == "list":
        return _list_cmd(store)
    if args.command == "show":
        return _show_cmd(args, store)
    if args.command == "approve":
        return _approve_cmd(args, store, input_fn, isatty)

    # args.command == "run"
    owns_drivers = drivers is None
    run_drivers = drivers if drivers is not None else _default_drivers(project)
    try:
        return _run_cmd(args, store, run_drivers, input_fn, isatty, watch_escape=owns_drivers)
    finally:
        if owns_drivers:
            _quit_browser(run_drivers)


if __name__ == "__main__":
    sys.exit(main())
