"""tools/rpa/_repair.py — rpa_repair / rpa_patch: fix a halted workflow with a
small, reviewed YAML patch (Subtask 17). The model never invents a locator or
edits workflow.yaml directly: a new target is only `{root, obs, index}` — an
element already shown by ui_observe — and this tool resolves it (session
lookup + observation + rebind, exactly like ui_act) and calls
`generate_locators` itself.
"""
from __future__ import annotations

import re

from agent.base_tool import BaseTool
from rpa import RpaError
from rpa.observe import rebind
from rpa.repair import preview_patch, write_patch
from rpa.resolver import generate_locators
from rpa.safety import is_allow_answer
from rpa.store import WorkflowStore
from tools.rpa._run import RpaRunTool, _can_ask, _store_for
from tools.ui._session import UiSession
from tools.ui._tools import _element_index

__all__ = ["RpaRepairTool", "RpaPatchTool"]

_TARGET_DESC_KEYS = {"root", "obs", "index"}


def _error(exc: RpaError) -> str:
    return f"Error ({type(exc).__name__}): {exc}"


def _fence_diff(diff_text: str) -> str:
    """Fence `diff_text` as a ```diff block, with a longer fence than any
    backtick run already inside it (the page renders ask_user questions as
    markdown, so an unfenced diff mangles)."""
    longest = max((len(run) for run in re.findall(r"`+", diff_text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}diff\n{diff_text.rstrip(chr(10))}\n{ticks}"


def _locators_from(session: UiSession, desc, field: str) -> list:
    """`{root, obs, index}` -> the element's generated locators, resolved live. Any
    other form (locators/css/automation_id/name/coords/...) is refused: a locator
    must come from a ui_observe observation, never a literal the model invented."""
    if not isinstance(desc, dict):
        raise RpaError(f"rpa_patch: {field} must be a mapping with root/obs/index")
    extra = set(desc) - _TARGET_DESC_KEYS
    if extra:
        raise RpaError(
            f"rpa_patch: {field} may only have root/obs/index, got extra key(s) {sorted(extra)}; "
            "a locator must come from a ui_observe observation, not a literal"
        )
    missing = _TARGET_DESC_KEYS - set(desc)
    if missing:
        raise RpaError(f"rpa_patch: {field} is missing {sorted(missing)}")

    root_id, obs_id, index = desc["root"], desc["obs"], desc["index"]
    found = session.lookup(root_id)
    if found is None:
        raise RpaError(f"rpa_patch: unknown root {root_id!r}; call ui_roots first")
    driver, root_obj = found

    before_outline = session.store.get(obs_id)
    if before_outline.root.id != root_obj.id or before_outline.root.kind != root_obj.kind:
        raise RpaError(f"rpa_patch: observation {obs_id!r} does not belong to root {root_id!r}")

    element = rebind(session.store, obs_id, _element_index(index), driver, root_obj)
    locators = generate_locators(driver, root_obj, element)
    if not locators:
        raise RpaError(f"rpa_patch: could not generate any locator for {field}")
    return locators


def _resolve_step_fields(session: UiSession, fields: dict) -> dict:
    """Turn every locator-bearing field into generated locators. `target` keeps the
    whole ladder; `if_present` and `expect.present`/`expect.gone` hold one locator,
    so they get the best rung."""
    if "root" in fields:
        # A root is a title/url pattern outside the locator ladder: a patch could widen
        # it to match any window. Changing the window or page means re-recording.
        raise RpaError("rpa_patch: a patch cannot change a step's root; re-record to change the window or page")
    fields = dict(fields)
    if fields.get("target") is not None:
        fields["target"] = {"locators": _locators_from(session, fields["target"], "target")}
    if fields.get("if_present") is not None:
        fields["if_present"] = _locators_from(session, fields["if_present"], "if_present")[0]
    expect = fields.get("expect")
    if isinstance(expect, dict):
        expect = dict(expect)
        for key in ("present", "gone"):
            if expect.get(key) is not None:
                expect[key] = _locators_from(session, expect[key], f"expect.{key}")[0]
        fields["expect"] = expect
    return fields


def _resolve_ops(session: UiSession, raw_ops) -> list[dict]:
    """Resolve every `target` descriptor in `raw_ops` before they reach `rpa.repair`."""
    if not isinstance(raw_ops, list):
        raise RpaError("rpa_patch: ops must be a list")
    resolved: list[dict] = []
    for op in raw_ops:
        if not isinstance(op, dict):
            raise RpaError("rpa_patch: each op must be a mapping")
        kind = op.get("op")
        if kind in ("replace_step", "insert_step_after"):
            fields = op.get("step")
            if not isinstance(fields, dict):
                raise RpaError(f"rpa_patch: {kind}.step must be a mapping")
            resolved.append({**op, "step": _resolve_step_fields(session, fields)})
        elif kind == "delete_step":
            resolved.append(op)
        else:
            raise RpaError(f"rpa_patch: unknown op {kind!r}")
    return resolved


class RpaRepairTool(BaseTool):
    name = "rpa_repair"
    description = (
        "Show the evidence for a halted workflow's latest run: the halted step's "
        "YAML, the halt reason, its recorded `before` state, and the outline/"
        "screenshot evidence paths. Explore read-only first with ui_roots/"
        "ui_observe, then fix it with rpa_patch — never edit workflow.yaml with "
        "file tools, and never approve the result yourself."
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

        from rpa.repair import repair_context

        try:
            ctx = repair_context(store, name)
        except RpaError as exc:
            return _error(exc)

        lines = [
            f"workflow: {ctx['name']}",
            f"halted step: {ctx['halted_step']}",
            f"reason: {ctx['reason']}",
            f"run dir: {ctx['run_dir']}",
        ]
        if ctx["before"] is not None:
            lines.append(f"before (recorded): {ctx['before']}")
        if ctx["outline_path"]:
            lines.append(f"outline: {ctx['outline_path']}")
        if ctx["screenshot_path"]:
            lines.append(f"screenshot: {ctx['screenshot_path']}")
        lines.append("")
        lines.append("halted step YAML:")
        lines.append(ctx["step_yaml"])
        lines.append(
            "Explore read-only first with ui_roots/ui_observe to find the fix. Then call "
            "rpa_patch with ops (replace_step/insert_step_after/delete_step). Every locator "
            "(target, if_present, expect.present, expect.gone) must come from a ui_observe "
            'observation — {"root": <root id>, "obs": "obs_N", "index": <int>} — never a literal '
            "locator. A patch cannot change a step's root. Never edit workflow.yaml with file "
            "tools, and never approve the patched result yourself."
        )
        return "\n".join(lines)


class RpaPatchTool(BaseTool):
    name = "rpa_patch"
    description = (
        "Patch a workflow's steps (replace_step/insert_step_after/delete_step) after "
        "rpa_repair. Every locator (target, if_present, expect.present, expect.gone) is "
        "given as `{\"root\": <root id>, \"obs\": \"obs_N\", \"index\": <int>}` from a "
        "ui_observe observation — a literal locator is rejected; a step's root cannot "
        "change. Shows the unified diff and asks the Admiral to approve before writing "
        "anything; a changed confirm step needs a second, explicit confirmation. "
        "On approval, writes the patch and re-runs the workflow with verify=true."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Workflow name."},
            "ops": {
                "type": "array",
                "description": (
                    "{\"op\":\"replace_step\",\"step_id\":id,\"step\":{...fields}}, "
                    "{\"op\":\"insert_step_after\",\"after\":id,\"step\":{...full step}}, "
                    "{\"op\":\"delete_step\",\"step_id\":id}."
                ),
                "items": {"type": "object"},
            },
            "from_step": {
                "type": "string",
                "description": "Resume the re-run from this step id (passed to rpa_run) after approval.",
            },
        },
        "required": ["name", "ops"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, name: str, ops: list, from_step: "str | None" = None) -> str:
        session = self.session
        store = _store_for(session)
        if name not in store.list():
            return f"Error (RpaError): unknown workflow {name!r}"

        if not _can_ask(session):
            return "Error (RpaError): a patch requires asking the Admiral; refused (autonomous or no frontend)"

        try:
            resolved_ops = _resolve_ops(session, ops)
            preview = preview_patch(store, name, resolved_ops)
        except RpaError as exc:
            return _error(exc)

        if not preview.diff_text:
            return f"no change: these ops leave {name!r} as it is; nothing to approve"

        question = f"Patch workflow {name!r}?\n\n{_fence_diff(preview.diff_text)}"
        options = [
            {"label": "Approve and re-run", "description": "Write this patch and re-run the workflow."},
            {"label": "Reject", "description": "Do not patch."},
        ]
        try:
            answer = session.callbacks.on_ask_user(question, options, None)
        except Exception:
            return "not patched"
        if not is_allow_answer(answer, "Approve and re-run"):
            return "not patched"

        if preview.changed_confirm_steps:
            steps_text = ", ".join(preview.changed_confirm_steps)
            question2 = (
                f"This patch changes confirm step(s) {steps_text} in {name!r}; they will need "
                "re-confirmation on their next run. Continue?"
            )
            options2 = [
                {"label": "Confirm change", "description": "Clear their approval and write the patch."},
                {"label": "Cancel", "description": "Do not patch."},
            ]
            try:
                answer2 = session.callbacks.on_ask_user(question2, options2, None)
            except Exception:
                return "not patched"
            if not is_allow_answer(answer2, "Confirm change"):
                return "not patched"

        try:
            write_patch(store, name, preview)
        except RpaError as exc:
            return _error(exc)

        lines = [f"patched {name!r}:", preview.diff_text, RpaRunTool(session).run(
            name=name, from_step=from_step, verify=True,
        )]
        return "\n".join(lines)
