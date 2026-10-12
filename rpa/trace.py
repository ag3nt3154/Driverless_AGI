"""rpa/trace.py — Recorder: appends `trace.jsonl` entries while a workflow is
being recorded (`rpa_record` / `rpa_save`, Subtask 13).

Each successful `computer_use_interact_with_window` call appends one "act" entry;
each `computer_use_list_windows(launch=...)`
call while recording appends one "launch" entry. Nothing is written for a
failed or refused act (the caller only calls `record_act` after a successful
`driver.act`).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from rpa import RpaError
from rpa.drivers.base import Driver
from rpa.model import Element, Outline, Root
from rpa.resolver import generate_locators
from rpa.screen import crop_element
from rpa.store import WorkflowStore

__all__ = ["Recorder"]

_SECRET_REF_RE = re.compile(r"^\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}$")
_DIGITS_RE = re.compile(r"\d+")


def _title_re(title: str) -> str:
    """Anchored `re.escape(title)` with digit runs generalised to `\\d+` and a leading
    "*" (the OS "unsaved changes" marker) made optional. Anchored so a short or
    empty title never matches an unrelated window."""
    esc = re.escape(title)
    esc = _DIGITS_RE.sub(r"\\d+", esc)
    if esc.startswith(r"\*"):
        esc = esc[2:]
    return r"^\*?" + esc + "$"


def _url_re(url: "str | None") -> str:
    """scheme://host/path regex for `url`, with the query string dropped."""
    parts = urlsplit(url or "")
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return "^" + re.escape(base) + r"(?:[?#].*)?$"


def _root_descriptor(root: Root) -> dict:
    if root.kind == "window":
        return {"kind": "window", "app": root.app, "title_re": _title_re(root.title)}
    return {"kind": "browser", "app": root.app, "url_re": _url_re(root.url)}


def _value_for_trace(element: Element, value) -> object:
    """Never the literal of a secure element; a `${env:NAME}` reference becomes
    `{"secret_env": NAME}` so the compiler can re-declare it, never the value."""
    if value is None:
        return None
    if isinstance(value, str):
        m = _SECRET_REF_RE.match(value)
        if m:
            return {"secret_env": m.group(1)}
    if element.secure:
        return {"secret": True}
    return value


def _elem_key(el: Element) -> tuple:
    return (el.path, el.role, el.name, el.automation_id)


def _before_summary(element: Element) -> dict:
    return {"role": element.role, "name": element.name, "path": list(element.path)}


def _expect_candidates(
    driver: Driver, root: Root, element: Element, before: Outline, after: Outline
) -> list[dict]:
    """window appeared → {"window": title}; a new element present → {"present": its
    best locator}; the acted-on element's value changed → {"value_equals": new value}
    (never for a secure element, whose `value` never actually changes from "[secure]")."""
    candidates: list[dict] = []

    if before.root.title != after.root.title:
        candidates.append({"window": after.root.title})

    # One "present" candidate only: locator generation walks the whole tree several
    # times per element, and a dialog adds 100+ elements (a Save As dialog made this
    # take over a minute and time UIA out). Prefer a new window/dialog, else the
    # first new interactive element.
    before_keys = {_elem_key(el) for el in before.elements}
    new = [el for el in after.elements if _elem_key(el) not in before_keys]
    pick = next((el for el in new if el.role in ("Window", "Dialog")), None) or next(
        (el for el in new if el.interactive), None
    )
    if pick is not None:
        try:
            locators = generate_locators(driver, root, pick)
        except RpaError:
            locators = []
        if locators:
            candidates.append({"present": locators[0]})

    if not element.secure:
        before_by_key = {_elem_key(el): el for el in before.elements}
        after_by_key = {_elem_key(el): el for el in after.elements}
        live_after = after_by_key.get(_elem_key(element))
        live_before = before_by_key.get(_elem_key(element))
        if live_after is not None and (live_before is None or live_before.value != live_after.value):
            candidates.append({"value_equals": live_after.value})

    return candidates


class Recorder:
    """One recording session, writing `<store>/<name>/trace.jsonl` as it goes."""

    def __init__(
        self,
        store: WorkflowStore,
        name: str,
        goal: str,
        *,
        driver_for: Callable[[Root], Driver],
    ) -> None:
        self.name = name
        self.goal = goal
        self._store = store
        self._driver_for = driver_for
        self._n = 0
        self._entries: list[dict] = []
        self._path: "Path | None" = None
        self._launch_ids: dict[str, int] = {}  # root id -> launch_id

    def start(self) -> None:
        """Refuse if a workflow or an unfinished recording already exists for `name`."""
        workflow_dir = self._store.dir(self.name)
        workflow_path = workflow_dir / "workflow.yaml"
        trace_path = workflow_dir / "trace.jsonl"
        if workflow_path.exists() or trace_path.exists():
            raise RpaError(
                f"a recording or workflow named {self.name!r} already exists; "
                "remove it first or pick a different name"
            )
        self._path = trace_path
        self._write({"kind": "header", "name": self.name, "goal": self.goal, "started_at": time.time()})

    def _write(self, entry: dict) -> None:
        self._entries.append(entry)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    def record_launch(self, root: Root, target: str) -> None:
        """A launch gets a `launch_id`; later acts on that window/tab carry it, so the
        compiled step can bind to the launched root instead of its (changing) title."""
        self._launch_ids[root.id] = len(self._launch_ids) + 1
        self._write({**_root_descriptor(root), "kind": "launch", "target": target,
                     "launch_id": self._launch_ids[root.id]})

    def record_close(self, root: Root) -> None:
        """The root window/tab itself was closed (no element, so no locators)."""
        self._n += 1
        self._write({
            "kind": "act", "n": self._n, "action": "close_window", "value": None,
            "root": {**_root_descriptor(root), **(
                {"launch_id": self._launch_ids[root.id]} if root.id in self._launch_ids else {}
            )},
            "locators": [], "expect_candidates": [], "before": {},
        })

    def prepare(self, root: Root, element: Element) -> dict:
        """Locators and crop for `element` as the UI is NOW — call before acting.

        `generate_locators` checks uniqueness against the live UI, so it must run
        before the act changes it (a dialog opening shifts indices; a closed root
        cannot be searched at all). A failed act just leaves the result unused.
        """
        n = self._n + 1
        driver = self._driver_for(root)
        return {"n": n, "locators": self._fill_image(driver, root, element, generate_locators(driver, root, element), n)}

    def record_act(
        self,
        root: Root,
        element: Element,
        action: str,
        value,
        before_outline: Outline,
        after_outline: "Outline | None",
        *,
        prepared: "dict | None" = None,
    ) -> None:
        """Append a successful act. `after_outline` is None when the root could not be
        observed after the act (e.g. it closed itself): the step gets no expect candidates."""
        prepared = prepared if prepared is not None else self.prepare(root, element)
        n = self._n = prepared["n"]
        locators = prepared["locators"]
        driver = self._driver_for(root)
        self._write({
            "kind": "act",
            "n": n,
            "root": {**_root_descriptor(root), **(
                {"launch_id": self._launch_ids[root.id]} if root.id in self._launch_ids else {}
            )},
            "action": action,
            "value": _value_for_trace(element, value),
            "locators": locators,
            "expect_candidates": (
                _expect_candidates(driver, root, element, before_outline, after_outline)
                if after_outline is not None else []
            ),
            "before": _before_summary(element),
        })

    def _fill_image(
        self, driver: Driver, root: Root, element: Element, locators: list[dict], n: int
    ) -> list[dict]:
        """Replace the `{"image": None}` placeholder with a saved crop path; drop it
        entirely (rather than fail the act) if the screenshot cannot be taken."""
        out: list[dict] = []
        for loc in locators:
            if "image" not in loc:
                out.append(loc)
                continue
            try:
                image = driver.screenshot(root)
                crop = crop_element(image, element.bbox)
                crop_path = self._store.dir(self.name) / "crops" / f"{n}.png"
                crop.save(crop_path, format="PNG")
            except Exception:  # noqa: BLE001 — any capture failure just drops this rung
                continue
            out.append({"image": f"crops/{n}.png"})
        return out

    def entries(self) -> list[dict]:
        """A read-only snapshot of the entries recorded so far (header included)."""
        return list(self._entries)

    def stop(self) -> list[dict]:
        """Finalize the recording and return its entries. Call only after the trace
        has been successfully compiled and saved — a failed save should keep
        recording active, so callers should use `entries()` to try compiling first."""
        entries = list(self._entries)
        self._entries = []
        self._path = None
        return entries
