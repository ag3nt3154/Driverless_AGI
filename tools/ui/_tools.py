"""tools/ui/_tools.py — the four computer-use tools: ui_roots, ui_observe, ui_act, ui_wait.

Registered only when `AgentConfig.computer_use` is true (agent/tools.py). All
four share one `UiSession` (desktop/browser drivers, the observation store,
the desktop lock and the safety gate). Every `RpaError` (and its subclasses —
Ambiguous, NotFound, StaleTarget, WrongElement, SafetyDenied, DesktopBusy,
FailsafeAbort) a driver/resolver/safety call raises is turned into a single
"Error (<Kind>): <message>" string rather than propagating, so the model sees
a plain, recoverable tool result instead of a traceback.

Secrets (D5): a `ui_act` value of the form `${env:NAME}` is read from the
environment inside the tool, so the tool-call arguments (and the session log
that records them) hold only the reference. Typing into a secure (password)
element requires such a reference; a literal value is refused.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from agent.base_tool import BaseTool
from agent.protocol import SideEffect, ToolResult
from agent.user_input import ImageAttachment
from rpa import RpaError
from rpa.model import Outline, validate_locator
from rpa.observe import diff, format_outline, rebind
from rpa.resolver import resolve
from rpa.screen import fit_width, mark, to_png_bytes
from tools.ui._session import UiSession


def _error_result(exc: RpaError) -> str:
    """"Error (<Kind>): <message>" — the one error shape every ui_* tool returns."""
    return f"Error ({type(exc).__name__}): {exc}"


def _unknown_root(root_id: str) -> str:
    return f"Error (NotFound): unknown root {root_id!r}; call ui_roots first"


def _resolve_region(
    region: "int | list[int] | tuple[int, ...] | None", outline: Outline
) -> "tuple[int, int, int, int] | None":
    """`region` as an element index (crop its bbox + 40px, left/top clamped to >= 0)
    or an explicit [left, top, right, bottom] box, in the outline's bbox frame."""
    if region is None:
        return None
    if isinstance(region, bool):  # bool is an int subclass; never a valid index
        raise RpaError(f"ui_observe: invalid region {region!r}")
    if isinstance(region, (list, tuple)) and len(region) == 1:
        region = region[0]
    if isinstance(region, str):
        region = _element_index(region)
    if isinstance(region, int):
        element = next((e for e in outline.elements if e.index == region), None)
        if element is None:
            raise RpaError(f"ui_observe: region index {region} is not in this outline")
        left, top, right, bottom = element.bbox
        return (max(0, left - 40), max(0, top - 40), right + 40, bottom + 40)
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise RpaError(f"ui_observe: region must be an element index or [left, top, right, bottom], got {region!r}")
    left, top, right, bottom = region
    return (int(left), int(top), int(right), int(bottom))


def _element_index(target) -> int:
    """An element index given as 12, "12" or "[12]" (models copy the outline's brackets)."""
    if isinstance(target, int) and not isinstance(target, bool):
        return target
    text = str(target).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    if not text.isdigit():
        raise RpaError(f"target must be an element index like 12 or [12], or a locator dict; got {target!r}")
    return int(text)


def _check_condition(driver, root_obj, condition: dict) -> "tuple[bool, str]":
    if "present" in condition:
        matches = driver.find(root_obj, condition["present"])
        return len(matches) >= 1, f"present: {len(matches)} match(es)"
    if "gone" in condition:
        matches = driver.find(root_obj, condition["gone"])
        return len(matches) == 0, f"gone: {len(matches)} match(es) remain"
    if "text" in condition:
        text = format_outline(driver.outline(root_obj))
        found = condition["text"] in text
        return found, f'text {condition["text"]!r} {"found" if found else "not found"}'
    if "window" in condition:
        pattern = condition["window"]
        for live_root in driver.roots():
            if live_root.id == root_obj.id and re.search(pattern, live_root.title):
                return True, f"window title matches {pattern!r}"
        return False, f"window title does not match {pattern!r}"
    if "file_exists" in condition:
        path = condition["file_exists"]
        exists = Path(path).exists()
        return exists, f'file {"exists" if exists else "missing"}: {path}'
    raise RpaError(f"ui_wait: unknown condition key(s) {list(condition)}")


class UiRootsTool(BaseTool):
    name = "ui_roots"
    description = (
        "List the windows and Firefox tabs dagi opened, as root ids (needed by "
        "ui_observe/ui_act/ui_wait). Other windows are hidden. Pass `launch` to open "
        "something first: an http(s):// URL opens a new Firefox tab, anything else "
        "launches that exe."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "launch": {
                "type": "string",
                "description": "Optional: an http(s):// URL (opens in Firefox), or an exe path/name to launch.",
            },
        },
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, launch: "str | None" = None) -> str:
        session = self.session
        try:
            if launch:
                if launch.startswith("http://") or launch.startswith("https://"):
                    launched_root = session.browser().launch(launch)
                    session.remember(session.browser(), launched_root)
                else:
                    launched_root = session.launch_window(launch)
                    session.remember(session.uia(), launched_root)
                if session.recorder is not None:
                    session.recorder.record_launch(launched_root, launch)

            lines = ["root_id | kind | app | title"]
            hidden = 0
            for root in session.uia().roots():
                if not session.opened_by_dagi(root):
                    hidden += 1
                    continue
                root_id = session.remember(session.uia(), root)
                lines.append(f"{root_id} | {root.kind} | {root.app} | {root.title}")
            if session.browser_started():
                for root in session.browser().roots():
                    root_id = session.remember(session.browser(), root)
                    lines.append(f"{root_id} | {root.kind} | {root.app} | {root.title}")
        except RpaError as exc:
            return _error_result(exc)
        if hidden:
            lines.append(f"({hidden} other windows not opened by dagi are hidden; open an app with launch=)")
        return "\n".join(lines)


class UiObserveTool(BaseTool):
    name = "ui_observe"
    description = (
        "Snapshot a root's UI as a numbered outline (one obs id per call) and, when "
        "useful, a marked screenshot (context only — pick targets by [index] from the "
        "text outline, not the picture). Screenshots older than the newest 3 are elided "
        "automatically. `region` zooms: an element index (crops around it) or [l,t,r,b]."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "A root id from ui_roots."},
            "mode": {
                "type": "string",
                "enum": ["outline", "screenshot", "both"],
                "description": "outline (default) is text-only unless few interactive elements are present.",
            },
            "query": {"type": "string", "description": "Only elements whose name contains this substring."},
            "depth": {"type": "integer", "description": "Limit how many levels deep to walk."},
            "region": {
                "description": "Zoom to this element [index] (crop + 40px) or an explicit [left, top, right, bottom].",
            },
        },
        "required": ["root"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(
        self,
        root: str,
        mode: str = "outline",
        query: "str | None" = None,
        depth: "int | None" = None,
        region=None,
    ):
        session = self.session
        found = session.lookup(root)
        if found is None:
            return _unknown_root(root)
        driver, root_obj = found

        try:
            if driver.needs_desktop_lock_to_observe(root_obj):
                session.lock.acquire(session.agent_name)
            outline = driver.outline(root_obj, query=query, depth=depth)
        except RpaError as exc:
            return _error_result(exc)

        obs_id = session.store.record(outline)
        text = f"{obs_id}\n{format_outline(outline)}"

        interactive_count = sum(1 for e in outline.elements if e.interactive)
        if mode not in ("screenshot", "both") and interactive_count >= 5:
            return ToolResult(output=text)

        try:
            region_box = _resolve_region(region, outline)
            image = driver.screenshot(root_obj, region=region_box)
        except RpaError as exc:
            return _error_result(exc)

        offset = (region_box[0], region_box[1]) if region_box else (0, 0)
        fitted = fit_width(mark(image, outline.elements, offset=offset), 1280)
        attachment = ImageAttachment(
            data=to_png_bytes(fitted),
            mime_type="image/png",
            width=fitted.width,
            height=fitted.height,
            name=f"{obs_id}.png",
        )
        return ToolResult(
            output=text,
            side_effect=SideEffect.ATTACH_IMAGE,
            side_effect_data={"image": attachment, "path": f"ui_observe {obs_id}"},
        )


_SECRET_REF = re.compile(r"^\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_value(value: "str | None", element) -> "str | None":
    """Expand a `${env:NAME}` reference; refuse a literal value for a secure element."""
    if value is None:
        return None
    m = _SECRET_REF.match(value)
    if m is None:
        if element.secure:
            raise RpaError(
                f'{element.role} "{element.name}" is a password field: pass ${{env:NAME}}, not a literal value'
            )
        return value
    secret = os.environ.get(m.group(1))
    if secret is None:
        raise RpaError(f"environment variable {m.group(1)} is not set")
    return secret


class UiActTool(BaseTool):
    name = "ui_act"
    description = (
        "Act on one element of a root: click, double_click, right_click, set_value, type, "
        "key, scroll, select, upload, focus, close_window. `target` is an [index] from the "
        "named `obs` (its observation id), or a locator dict ({\"uia\":...}/{\"css\":...}/"
        "{\"aria\":...}/{\"coords\":...} — coords only with allow_coords=true). New apps and "
        "sensitive actions (send, delete, pay, publish, ...) ask the user to confirm first. "
        "For key, `value` is a chord: enter, tab, esc, ctrl+s, ctrl+shift+s, alt+f4 "
        "(modifiers ctrl/shift/alt/win joined with +); for type, `value` is typed literally. "
        "Never put a real password or secret in `value`: pass `${env:NAME}` and the tool reads "
        "environment variable NAME (password fields accept only this form). "
        "Returns the new observation id to use for the next ui_act."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "A root id from ui_roots."},
            "target": {"description": "An element [index] from `obs`, or a locator dict."},
            "action": {"type": "string", "description": "One of the supported actions (see description)."},
            "value": {"type": "string", "description": "Text/value for set_value, type, key, select, upload."},
            "obs": {"type": "string", "description": "The observation id `target` was picked from."},
            "sensitive": {"type": "boolean", "description": "Force a confirm even if the name has no keyword."},
            "allow_coords": {"type": "boolean", "description": "Allow a coords locator (last-resort rung)."},
        },
        "required": ["root", "target", "action", "obs"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def cancel(self) -> None:
        """ESC: stop a running replay at its next cancel point, then release the lock."""
        self.session.cancel_event.set()
        self.session.end_turn()

    def release_lock(self) -> None:
        """Release the desktop lock. Looked up by name (like `bash.force_kill`) from
        AgentLoop.interrupt() and from the turn-close path in agent/loop.py:run()."""
        self.session.end_turn()

    def run(
        self,
        root: str,
        target,
        action: str,
        obs: str,
        value: "str | None" = None,
        sensitive: bool = False,
        allow_coords: bool = False,
    ) -> str:
        session = self.session
        found = session.lookup(root)
        if found is None:
            return _unknown_root(root)
        driver, root_obj = found

        try:
            before_outline = session.store.get(obs)
        except RpaError as exc:
            return _error_result(exc)
        if before_outline.root.id != root_obj.id or before_outline.root.kind != root_obj.kind:
            return f"Error (RpaError): observation {obs!r} does not belong to root {root!r}"

        try:
            if isinstance(target, dict):
                validate_locator(target)
                element = resolve(driver, root_obj, [target], allow_coords=allow_coords).element
            else:
                element = rebind(session.store, obs, _element_index(target), driver, root_obj)

            session.safety.check_app(root_obj)
            session.safety.check_action(root_obj, element, action, sensitive_flag=sensitive)

            if driver.needs_desktop_lock(action):
                session.lock.acquire(session.agent_name)

            # While recording, take locators from the UI as it is before the act.
            prepared = session.recorder.prepare(root_obj, element) if session.recorder is not None else None
            driver.act(root_obj, element, action, _resolve_value(value, element))
        except RpaError as exc:
            return _error_result(exc)

        done = f'ok: {action} [{element.index}] {element.role} "{element.name}"'
        gone = None
        try:
            new_outline = driver.outline(root_obj)
        except RpaError as exc:  # e.g. close_window closed the root itself
            new_outline = None
            gone = f"{done}\n(root {root} can no longer be observed: {exc})"
        not_recorded = None
        if session.recorder is not None:
            try:
                session.recorder.record_act(
                    root_obj, element, action, value, before_outline, new_outline, prepared=prepared,
                )
            except Exception as exc:  # noqa: BLE001 — the act already happened; say so
                not_recorded = f"(warning: this act was NOT recorded: {exc})"
        if new_outline is None:
            return gone if not_recorded is None else f"{gone}\n{not_recorded}"
        new_obs_id = session.store.record(new_outline)
        diff_lines = diff(before_outline, new_outline)

        lines = [done, *diff_lines, *([not_recorded] if not_recorded else []), new_obs_id]
        return "\n".join(lines)


class UiWaitTool(BaseTool):
    name = "ui_wait"
    description = (
        'Poll a root until a condition holds, or time out. Conditions: {"present": locator}, '
        '{"gone": locator}, {"text": "substring"}, {"window": "title regex"}, '
        '{"file_exists": "path"}.'
    )
    _parameters = {
        "type": "object",
        "properties": {
            "root": {"type": "string", "description": "A root id from ui_roots."},
            "condition": {"type": "object", "description": "Exactly one of present/gone/text/window/file_exists."},
            "timeout": {"type": "number", "description": "Seconds to wait before giving up (default 10)."},
        },
        "required": ["root", "condition"],
    }

    def __init__(self, session: UiSession) -> None:
        self.session = session

    def run(self, root: str, condition: dict, timeout: float = 10) -> str:
        session = self.session
        found = session.lookup(root)
        if found is None:
            return _unknown_root(root)
        driver, root_obj = found

        deadline = time.time() + timeout
        reason = ""
        while True:
            try:
                ok, reason = _check_condition(driver, root_obj, condition)
            except RpaError as exc:
                return _error_result(exc)
            if ok:
                return f"ok: {reason}"
            if time.time() >= deadline:
                return f"timeout: {reason} (waited {timeout}s)"
            time.sleep(0.5)
