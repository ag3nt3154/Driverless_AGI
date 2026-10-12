"""rpa/observe.py — observation store, outline formatting, diffing and rebinding.

An "observation" is a numbered snapshot (`Outline`) that the agent was shown.
`rebind` lets a later `computer_use_interact_with_window` on `obs_N index` keep working after the UI
reshuffles element indices, by falling back to the resolver's locators.
"""
from __future__ import annotations

from rpa import RpaError
from rpa.drivers.base import Driver
from rpa.model import Element, Locator, Outline, Root
from rpa.resolver import Ambiguous, NotFound, css_token_value, is_unstable_id, resolve

__all__ = ["ObservationStore", "StaleTarget", "format_outline", "diff", "rebind"]

_MAX_PER_ROOT = 10
_MAX_DIFF_LINES = 15


class StaleTarget(RpaError):
    """The element named by an observation id + index no longer exists or moved."""


class ObservationStore:
    """Keeps the last `_MAX_PER_ROOT` outlines per root, under monotonic obs_N ids."""

    def __init__(self) -> None:
        self._counter = 0
        self._by_id: dict[str, Outline] = {}
        self._ids_by_root: dict[str, list[str]] = {}

    def record(self, outline: Outline) -> str:
        """Store `outline`, returning its new "obs_N" id."""
        self._counter += 1
        obs_id = f"obs_{self._counter}"
        self._by_id[obs_id] = outline
        ids = self._ids_by_root.setdefault(outline.root.id, [])
        ids.append(obs_id)
        while len(ids) > _MAX_PER_ROOT:
            evicted = ids.pop(0)
            self._by_id.pop(evicted, None)
        return obs_id

    def get(self, obs_id: str) -> Outline:
        """Return the outline for `obs_id`; raise `RpaError` if unknown or evicted."""
        try:
            return self._by_id[obs_id]
        except KeyError:
            raise RpaError(f"observation {obs_id!r} is unknown or has been evicted") from None

    def latest(self, root_id: str) -> Outline | None:
        """Return the most recently recorded outline for `root_id`, or None."""
        ids = self._ids_by_root.get(root_id)
        if not ids:
            return None
        return self._by_id[ids[-1]]


def format_outline(outline: Outline, *, max_lines: int = 300) -> str:
    """Render `outline` as one line per element, indented by ancestor depth.

    Non-interactive elements with no name are omitted. Each line is
    `[index] Role "name" id=<automation_id>`, plus ` value="<v>"` when the
    element has a value (secure elements already carry `"[secure]"`).
    """
    shown = [el for el in outline.elements if el.interactive or el.name]
    truncated = len(shown) - max_lines
    lines: list[str] = []
    for el in shown[:max_lines]:
        indent = "  " * len(el.path)
        line = f'{indent}[{el.index}] {el.role} "{el.name}"'
        if el.automation_id:
            line += f" id={el.automation_id}"
        if el.value is not None:
            line += f' value="{el.value}"'
        lines.append(line)
    if truncated > 0:
        lines.append(f"… {truncated} more elements (use query=/depth=)")
    return "\n".join(lines)


def _key(el: Element) -> tuple[tuple[str, ...], str, str, str | None]:
    return (el.path, el.role, el.name, el.automation_id)


def diff(before: Outline, after: Outline) -> list[str]:
    """Summarize what changed between two outlines of the same root (max 15 lines).

    Elements are matched by (path, role, name, automation_id); reports
    appeared (`+`) / disappeared (`-`) elements, value changes (`~`, never
    showing secure values), and a root title change.
    """
    lines: list[str] = []

    if before.root.title != after.root.title:
        lines.append(f'~ title: "{before.root.title}" → "{after.root.title}"')

    before_by_key = {_key(el): el for el in before.elements}
    after_by_key = {_key(el): el for el in after.elements}

    for key, el in before_by_key.items():
        if key not in after_by_key:
            lines.append(f'- [{el.index}] {el.role} "{el.name}"')

    for key, el in after_by_key.items():
        if key not in before_by_key:
            lines.append(f'+ [{el.index}] {el.role} "{el.name}"')

    for key, before_el in before_by_key.items():
        after_el = after_by_key.get(key)
        if after_el is not None and before_el.value != after_el.value:
            lines.append(
                f'~ [{after_el.index}] {after_el.role} "{after_el.name}": '
                f'"{before_el.value}" → "{after_el.value}"'
            )

    return lines[:_MAX_DIFF_LINES]


def _fallback_locators(old: Element, root: Root) -> list[Locator]:
    """Rung-1 (automation_id) and rung-2 (role+name, scoped by path) candidates for `old`.

    Unlike `resolver.generate_locators`, this never checks the candidate against
    `old.index` — that index is exactly what may no longer be current.
    """
    locators: list[Locator] = []

    aid = old.automation_id
    if aid:
        raw = aid if root.kind == "window" else css_token_value(aid)
        if raw and not is_unstable_id(raw):
            locators.append({"uia": {"automation_id": aid}} if root.kind == "window" else {"css": aid})

    kind = "uia" if root.kind == "window" else "aria"
    base: dict = {"role": old.role, "name": old.name}
    if old.path:
        base["within"] = list(old.path)
    locators.append({kind: base})

    return locators


def _index_trustworthy(old_outline: Outline, live_outline: Outline, old: Element) -> bool:
    """The same index still means the same element: its key is unique in both outlines,
    or the outline is unchanged. Duplicates (two "OK" buttons) shift silently otherwise."""
    old_keys = [_key(el) for el in old_outline.elements]
    live_keys = [_key(el) for el in live_outline.elements]
    key = _key(old)
    return (old_keys.count(key) == 1 and live_keys.count(key) == 1) or old_keys == live_keys


def rebind(store: ObservationStore, obs_id: str, index: int, driver: Driver, root: Root) -> Element:
    """Resolve the element `index` referred to a prior observation against the live UI.

    If the live outline still has an identical element (same path, role, name,
    automation_id) at `index`, return it. Otherwise rebuild locators from the
    old element's fields and resolve them live. Raises `StaleTarget` if the
    element is gone or ambiguous; never returns an element whose identity differs.
    """
    outline = store.get(obs_id)
    old = next((el for el in outline.elements if el.index == index), None)
    if old is None:
        raise StaleTarget(f"observation {obs_id!r} has no element with index {index}")

    live_outline = driver.outline(root)
    live = next((el for el in live_outline.elements if el.index == index), None)
    if live is not None and _key(live) == _key(old) and _index_trustworthy(outline, live_outline, old):
        return live

    locators = _fallback_locators(old, root)
    try:
        resolution = resolve(driver, root, locators)
    except (Ambiguous, NotFound) as exc:
        raise StaleTarget(f"element at index {index} from {obs_id!r} is stale: {exc}") from exc
    return resolution.element
