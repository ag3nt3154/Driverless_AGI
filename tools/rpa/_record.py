"""tools/rpa/_record.py — rpa_record / rpa_save: capture a `ui_*` session as a
trace, then compile it into a draft `workflow.yaml` (Subtask 13 / 14).
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from rpa import RpaError
from rpa.compiler import apply_cleanup, compile_trace
from rpa.store import WorkflowStore
from rpa.trace import Recorder
from rpa.workflow import dump_workflow
from tools.ui._session import UiSession

_RPA_SUBPATH = Path(".dagi") / "rpa"


def _store_for(session: UiSession) -> WorkflowStore:
    project_path = getattr(session.config, "project_path", None)
    if project_path is None:
        from agent import DAGI_ROOT
        project_path = DAGI_ROOT
    return WorkflowStore(Path(project_path) / _RPA_SUBPATH)


def _driver_for(session: UiSession):
    def pick(root):
        return session.uia() if root.kind == "window" else session.browser()
    return pick


def _error(exc: RpaError) -> str:
    return f"Error ({type(exc).__name__}): {exc}"


class RpaRecordTool(BaseTool):
    name = "rpa_record"
    description = (
        "Start recording a workflow: every successful ui_act, and every ui_roots "
        "launch, is appended to a trace until rpa_save. Only one recording runs at "
        "a time; refused if a workflow or trace already exists for this `name` "
        "(remove it or pick another name)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name (lowercase letters, digits, - or _)."},
            "goal": {"type": "string", "description": "One line describing what this workflow accomplishes."},
        },
        "required": ["name", "goal"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, name: str, goal: str) -> str:
        session = self.session
        if session.recorder is not None:
            return "Error (RpaError): already recording; call rpa_save first"
        recorder = Recorder(_store_for(session), name, goal, driver_for=_driver_for(session))
        try:
            recorder.start()
        except RpaError as exc:
            return _error(exc)
        session.recorder = recorder
        return f"recording {name!r}… act with the ui_* tools, then call rpa_save."


class RpaSaveTool(BaseTool):
    name = "rpa_save"
    description = (
        "Stop the current recording and compile it to a draft workflow.yaml. `cleanup` "
        "may delete, rename, parameterize and flag steps — never add or change a "
        "locator: {\"op\":\"delete\",\"step\":id}, {\"op\":\"rename\",\"step\":id,\"to\":new_id}, "
        "{\"op\":\"param\",\"step\":id,\"field\":\"value\",\"name\":p,\"default\":literal}, "
        "{\"op\":\"flag\",\"step\":id,\"confirm\":\"once\"|\"every_run\"|null,\"sensitive\":bool,"
        "\"expect_file\":path}. On error the recording stays open — fix `cleanup` and retry."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "cleanup": {
                "type": "array",
                "description": "Cleanup ops applied to the compiled draft before saving.",
                "items": {"type": "object"},
            },
        },
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, cleanup: "list | None" = None) -> str:
        session = self.session
        recorder = session.recorder
        if recorder is None:
            return "Error (RpaError): not recording; call rpa_record first"

        entries = recorder.entries()
        try:
            workflow = compile_trace(entries, recorder.name, recorder.goal)
            workflow = apply_cleanup(workflow, cleanup or [])
        except RpaError as exc:
            return _error(exc)  # recorder stays active: fix cleanup and retry

        store = _store_for(session)
        store.save(workflow, status="draft")
        recorder.stop()
        session.recorder = None

        yaml_path = store.dir(workflow.name) / "workflow.yaml"
        yaml_text = dump_workflow(workflow)
        return (
            f"saved draft workflow {workflow.name!r} to {yaml_path}\n\n{yaml_text}\n"
            "Next: review the YAML, then run it with verify (rpa_run verify=true — Subtask 16)."
        )
