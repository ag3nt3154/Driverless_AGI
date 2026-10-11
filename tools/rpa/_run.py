"""tools/rpa/_run.py — rpa_run / rpa_approve: run a workflow from chat and move it
through verify -> approve (Subtask 16). `confirm`/approval both go through the
session's `ask_user` callback with no recommended option; an autonomous config
or a session with no frontend always denies without asking.
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from rpa import RpaError
from rpa.interpreter import run_workflow
from rpa.safety import is_allow_answer
from rpa.store import WorkflowStore
from rpa.workflow import Step
from tools.ui._session import UiSession

_RPA_SUBPATH = Path(".dagi") / "rpa"


def _store_for(session: UiSession) -> WorkflowStore:
    project_path = getattr(session.config, "project_path", None)
    if project_path is None:
        from agent import DAGI_ROOT
        project_path = DAGI_ROOT
    return WorkflowStore(Path(project_path) / _RPA_SUBPATH)


def _error(exc: RpaError) -> str:
    return f"Error ({type(exc).__name__}): {exc}"


def _can_ask(session: UiSession) -> bool:
    if bool(getattr(session.config, "autonomous", False)):
        return False
    callbacks = session.callbacks
    return callbacks is not None and getattr(callbacks, "on_ask_user", None) is not None


def _confirm_for(session: UiSession):
    """`confirm` for `run_workflow`: asks the session, no recommended option.
    Autonomous config or no frontend -> always deny, without asking."""

    def confirm(step: Step, question: str) -> bool:
        if not _can_ask(session):
            return False
        options = [
            {"label": "Allow once", "description": "Perform this one step now."},
            {"label": "Deny", "description": "Do not perform this step."},
        ]
        try:
            answer = session.callbacks.on_ask_user(question, options, None)
        except Exception:
            return False
        return is_allow_answer(answer, "Allow once")

    return confirm


class RpaRunTool(BaseTool):
    name = "rpa_run"
    description = (
        "Run a saved workflow step by step, with no model calls. Warns when the "
        "workflow is not approved and `verify` is not set. On HALT, offer the "
        "Admiral a repair (rpa_repair) — never start it unasked."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name."},
            "params": {"type": "object", "description": "Workflow parameter values."},
            "from_step": {
                "type": "string",
                "description": "Resume from this step id; its pre-check must pass or the run halts.",
            },
            "verify": {
                "type": "boolean",
                "description": "Verify run: a clean run records the content rpa_approve needs.",
            },
        },
        "required": ["name"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(
        self,
        name: str,
        params: "dict | None" = None,
        from_step: "str | None" = None,
        verify: bool = False,
    ) -> str:
        session = self.session
        session.cancel_event.clear()  # an ESC from an earlier turn must not stop this run
        store = _store_for(session)
        if name not in store.list():
            return f"Error (RpaError): unknown workflow {name!r}"

        lines: list[str] = []
        state = store.state(name)
        if state["status"] != "approved" and not verify:
            lines.append(
                f"Warning: workflow {name!r} is not approved; consider rpa_run with verify=true first."
            )

        drivers = {"window": session.uia(), "browser": session.browser()}
        try:
            session.note_existing_windows()
        except RpaError:
            pass
        try:
            result = run_workflow(
                store, name, drivers=drivers, params=params or {}, confirm=_confirm_for(session),
                start_at=from_step, verify=verify, lock=session.lock, agent=session.agent_name,
                cancelled=session.cancel_event.is_set,
            )
        except RpaError as exc:
            return _error(exc)

        # Windows/tabs the replay opened are dagi's: listed by ui_roots, closable later.
        for root in result.launched:
            session.adopt(root)
            driver = drivers["window" if root.kind == "window" else "browser"]
            lines.append(f"opened: {session.remember(driver, root)} | {root.app} | {root.title}")

        lines.append(f"status: {result.status}")
        lines.append(f"steps: {len(result.steps)}")
        for log in result.steps:
            rung = f" (rung {log.rung_index})" if log.rung_index else ""
            lines.append(f"  {log.step_id}: {log.status}{rung}")

        if result.status == "halted":
            lines.append(
                f"Step `{result.halted_step}` halted: {result.reason}. Evidence: {result.run_dir}. "
                "Offer the Admiral a repair (rpa_repair) — do not start it unasked."
            )
        elif verify and result.status == "ok":
            lines.append("Verified. Ask the Admiral to approve with rpa_approve.")

        return "\n".join(lines)


class RpaApproveTool(BaseTool):
    name = "rpa_approve"
    description = (
        "Ask the Admiral to approve a workflow (pre-approves its confirm steps) after "
        "a clean verify run of the current content. Refuses without asking when "
        "autonomous or when there is no frontend to ask."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name."},
        },
        "required": ["name"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, name: str) -> str:
        session = self.session
        store = _store_for(session)
        if name not in store.list():
            return f"Error (RpaError): unknown workflow {name!r}"

        if not _can_ask(session):
            return "Error (RpaError): approval requires asking the Admiral; refused (autonomous or no frontend)"

        workflow = store.load(name)
        confirm_steps = [s.id for s in workflow.steps if s.confirm]
        steps_text = ", ".join(confirm_steps) if confirm_steps else "(none)"
        question = f"Approve workflow {name!r}? Confirm steps to pre-approve: {steps_text}"
        options = [
            {"label": "Approve", "description": f"Pre-approve {name!r}'s confirm steps and mark it approved."},
            {"label": "Reject", "description": "Do not approve."},
        ]
        try:
            answer = session.callbacks.on_ask_user(question, options, None)
        except Exception:
            return "Error (RpaError): approval ask failed"

        if not is_allow_answer(answer, "Approve"):
            return f"not approved: {name!r}"

        try:
            store.approve(name)
        except RpaError as exc:
            return _error(exc)
        return f"approved {name!r}"
