"""Atomic parent-side orchestration for the inherited ``/wtf`` subagent."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from agent import session_events as sev
from agent.wtf_report import parse_wtf_report
from tools.subagent_api import run_subagent

if TYPE_CHECKING:
    from agent.loop import AgentLoop


@dataclass(frozen=True, slots=True)
class WtfResult:
    """The safe parent-side reference to a validated diagnostic report."""

    description: str
    report_path: Path
    branch_id: str


def _literal_invocation(description: str | None) -> str:
    return "/wtf" if description is None else f"/wtf {description}"


def _task_text(description: str | None) -> str:
    if description is None:
        return (
            "This is a bare /wtf request. Infer the likely problem from the inherited context "
            "and investigate it read-only."
        )
    return f"Investigate this diagnostic hint verbatim:\n{description}"


def _has_active_conversation(loop: "AgentLoop") -> bool:
    return any(message.get("role") != "system" for message in loop.log.derive_messages())


def _validated_report_path(loop: "AgentLoop", result) -> tuple[Path, Path, str]:
    if result.status != "ok":
        raise RuntimeError(f"/wtf subagent did not complete successfully (status: {result.status})")
    if not result.branch_id:
        raise RuntimeError("/wtf subagent returned no branch id")
    branch = loop.log.branch_event(result.branch_id)
    if branch is None:
        raise RuntimeError("/wtf subagent did not record branch metadata")
    fork_generation = branch.data["parent_surface_generation"]
    if loop.log.surface.generation != fork_generation:
        raise RuntimeError("/wtf report is stale: the parent surface changed during diagnosis")
    raw_path = result.handoff_path
    if raw_path is None:
        raise RuntimeError("/wtf subagent returned no handoff path")
    report_path = Path(raw_path).resolve()
    if not report_path.is_file():
        raise RuntimeError(f"/wtf handoff was not written: {report_path}")
    try:
        relative_path = report_path.relative_to(loop.config.project_path.resolve())
    except ValueError as exc:
        raise RuntimeError("/wtf handoff path is outside the project") from exc
    try:
        description = parse_wtf_report(result.handoff_text).description
    except ValueError as exc:
        raise RuntimeError(f"/wtf handoff is malformed: {exc}") from exc
    return report_path, relative_path, description


def _append_reference(loop: "AgentLoop", invocation: str, relative_path: Path, branch_id: str) -> None:
    content = (
        f"{invocation}\n\nDiagnostic report: {relative_path.as_posix()}\nBranch: {branch_id}"
    )
    loop._log_user_message("user", content, "wtf")


def run_wtf(loop: "AgentLoop", description: str | None) -> WtfResult:
    """Run a stable inherited diagnostic and append its reference only after validation."""
    if not _has_active_conversation(loop):
        raise RuntimeError("/wtf requires an active conversation before it can be diagnosed")
    was_idle = loop.log.open_turn is None
    result = run_subagent(
        task=_task_text(description),
        preset="wtf",
        project_path=loop.config.project_path,
        parent_context=loop.parent_context_provider,
        fork_mode="stable",
        handoff_dir=loop.config.project_path / ".dagi" / "errors",
    )
    report_path, relative_path, parsed_description = _validated_report_path(loop, result)
    if was_idle:
        turn = loop.log.next_turn()
        loop.log.append(sev.TURN_START, {"turn": turn})
        try:
            _append_reference(loop, _literal_invocation(description), relative_path, result.branch_id)
        finally:
            loop._close_turn(turn, sev.reason_completed())
    else:
        _append_reference(loop, _literal_invocation(description), relative_path, result.branch_id)
    return WtfResult(parsed_description, report_path, result.branch_id)
