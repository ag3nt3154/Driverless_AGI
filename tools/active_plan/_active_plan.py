# tools/active_plan/_active_plan.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker

_SIDECAR_VERSION = 1


def _sidecar_path(project_path: Path, thread_id: str) -> Path:
    return project_path / ".dagi" / "session-state" / thread_id / "active-plan.json"


def _thread_id(config: "AgentConfig", tracker: "SessionTracker | None") -> str:
    if tracker is not None:
        tid = getattr(tracker, "_thread_id", None)
        if tid:
            return tid
    return config.thread_id or "default"


def _read_sidecar(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_atomic(sidecar: Path, data: dict) -> None:
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    tmp = sidecar.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, sidecar)


def _current_branch(project_path: Path) -> str | None:
    try:
        from agent._git_branch import get_current_branch
        return get_current_branch(project_path)
    except Exception:
        return None


class SetActivePlanTool(BaseTool):
    name = "set_active_plan"
    description = (
        "Attach or detach the active plan for this session. "
        "Pass a project-local path to a Markdown plan to attach, "
        "or null to detach. Attaching does not enter plan mode or start implementation."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": ["string", "null"],
                "description": (
                    "Absolute or project-relative path to an existing Markdown plan file, "
                    "or null to detach."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        **_: object,
    ) -> None:
        self._config = config
        self._tracker = tracker

    def run(self, path: str | None) -> ToolResult | str:
        project_path = Path(self._config.project_path)
        tid = _thread_id(self._config, self._tracker)
        sidecar = _sidecar_path(project_path, tid)

        if path is None:
            if sidecar.exists():
                sidecar.unlink()
            return ToolResult(
                output="Active plan detached.",
                side_effect=SideEffect.SET_ACTIVE_PLAN,
                side_effect_data={"path": None},
            )

        resolved = (project_path / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if not resolved.exists():
            return f"Error: plan file not found: {resolved}"
        if not resolved.is_file():
            return f"Error: path is not a file: {resolved}"
        try:
            resolved.relative_to(project_path.resolve())
        except ValueError:
            return f"Error: path escapes project root: {resolved}"

        branch = _current_branch(project_path)
        _write_atomic(sidecar, {
            "version": _SIDECAR_VERSION,
            "repo_root": str(project_path),
            "plan_path": str(resolved),
            "expected_branch": branch,
        })
        return ToolResult(
            output=(
                f"Active plan set: {resolved}\n"
                f"Expected branch: {branch or '(none)'}"
            ),
            side_effect=SideEffect.SET_ACTIVE_PLAN,
            side_effect_data={"path": str(resolved)},
        )


class CheckActivePlanTool(BaseTool):
    name = "check_active_plan"
    description = (
        "Returns the current active plan: association status, latest plan contents, "
        "and any mismatch between the expected and actual branch. "
        "Call this before acting on plan state after any resume or compaction."
    )
    _parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        **_: object,
    ) -> None:
        self._config = config
        self._tracker = tracker

    def run(self) -> "ToolResult | str":
        project_path = Path(self._config.project_path)
        tid = _thread_id(self._config, self._tracker)
        sidecar = _sidecar_path(project_path, tid)

        if not sidecar.exists():
            return "No active plan. Use set_active_plan to attach one."

        data = _read_sidecar(sidecar)
        if not data:
            return f"Sidecar unreadable: {sidecar}. Use set_active_plan to re-attach."

        plan_path = Path(data.get("plan_path", ""))
        if not plan_path.exists():
            return (
                f"STALE POINTER — the associated plan file no longer exists.\n"
                f"Expected: {plan_path}\n"
                "Use set_active_plan(null) to detach, then re-attach the correct file."
            )

        try:
            contents = plan_path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"Plan file is unreadable: {exc}"

        current = _current_branch(project_path)
        expected = data.get("expected_branch")
        branch_note = (
            f"Branch: {current or '(unknown)'} ✓"
            if current == expected
            else (
                f"Branch mismatch — expected: {expected or '(none)'}, "
                f"actual: {current or '(unknown)'}"
            )
        )
        output = (
            f"Active plan: {plan_path}\n"
            f"{branch_note}\n"
            f"Thread: {tid}\n\n"
            f"--- Plan contents ---\n{contents}"
        )
        # Emit SET_ACTIVE_PLAN so the loop restores config.active_plan_file on
        # resume — critical when the previous session set the plan but the new
        # one hasn't called set_active_plan yet.
        return ToolResult(
            output=output,
            side_effect=SideEffect.SET_ACTIVE_PLAN,
            side_effect_data={"path": str(plan_path)},
        )
