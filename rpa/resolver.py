"""rpa/resolver.py — turn a locator list into exactly one element, and the reverse:
generate a ranked, unique locator list for a chosen element.

Element identity: within one outline/find call, two elements are the "same
element" iff they have the same `Element.index` (the fake driver and the real
drivers both number elements by outline-walk order).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rpa import RpaError
from rpa.drivers.base import Driver
from rpa.model import Element, Locator, Root

__all__ = [
    "Resolution",
    "Ambiguous",
    "NotFound",
    "resolve",
    "generate_locators",
    "is_unstable_id",
]


class Ambiguous(RpaError):
    """More than one element matched a locator; resolution halts immediately."""

    def __init__(self, locator: Locator, count: int) -> None:
        self.locator = locator
        self.count = count
        super().__init__(f"ambiguous locator {locator!r}: {count} matches")


class NotFound(RpaError):
    """No locator in the list matched exactly one element."""

    def __init__(self, locators: list[Locator]) -> None:
        self.locators = locators
        super().__init__(f"no locator matched a single element: {locators!r}")


@dataclass(frozen=True)
class Resolution:
    """The result of a successful `resolve()` call."""

    element: Element
    rung_index: int
    locator: Locator


def resolve(
    driver: Driver,
    root: Root,
    locators: list[Locator],
    *,
    allow_coords: bool = False,
) -> Resolution:
    """Walk `locators` in order; the first rung with exactly one match wins.

    `ocr` and `image` rungs are skipped silently (not resolved in v1). `coords`
    is skipped unless `allow_coords`. More than one match on a rung raises
    `Ambiguous` immediately — resolution never falls through an ambiguous rung.
    """
    for rung_index, locator in enumerate(locators):
        if "ocr" in locator or "image" in locator:
            continue
        if "coords" in locator and not allow_coords:
            continue
        matches = driver.find(root, locator)
        if len(matches) == 1:
            return Resolution(element=matches[0], rung_index=rung_index, locator=locator)
        if len(matches) > 1:
            raise Ambiguous(locator, len(matches))
        # zero matches: try the next rung
    raise NotFound(locators)


_GUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)
_HEX_RE = re.compile(r"^(0[xX])?[0-9a-fA-F]{12,}$")
_TRAILING_DIGITS_RE = re.compile(r"[_\-.:]\d{3,}$")


def is_unstable_id(value: str | None) -> bool:
    """True for GUIDs, long hex strings (optionally `0x`-prefixed), or ids ending in `sep + 3+ digits`."""
    if not value:
        return False
    if _GUID_RE.match(value):
        return True
    if _HEX_RE.match(value):
        return True
    if _TRAILING_DIGITS_RE.search(value):
        return True
    return False


def _matches_exactly(driver: Driver, root: Root, locator: Locator, element: Element) -> bool:
    matches = driver.find(root, locator)
    return len(matches) == 1 and matches[0].index == element.index


_CSS_TOKEN_RE = re.compile(r'^(?:#(?P<id>.+)|\[data-testid="(?P<testid>.*)"\])$')


def _css_token_value(token: str) -> str | None:
    """Raw id inside a browser driver's `#id` / `[data-testid="x"]` token; None if neither."""
    m = _CSS_TOKEN_RE.match(token)
    return (m.group("id") or m.group("testid")) if m else None


def _rung1(driver: Driver, root: Root, element: Element) -> Locator | None:
    # Window roots hold a raw UIA AutomationId; browser roots hold a ready CSS token
    # (`#id` or `[data-testid="x"]`, set by the browser driver).
    value = element.automation_id
    if not value:
        return None
    raw = value if root.kind == "window" else _css_token_value(value)
    if not raw or is_unstable_id(raw):
        return None
    candidate: Locator = {"uia": {"automation_id": value}} if root.kind == "window" else {"css": value}
    return candidate if _matches_exactly(driver, root, candidate, element) else None


def _rung2(driver: Driver, root: Root, element: Element) -> Locator | None:
    kind = "uia" if root.kind == "window" else "aria"
    base = {"role": element.role, "name": element.name}
    bare: Locator = {kind: dict(base)}
    if _matches_exactly(driver, root, bare, element):
        return bare
    # Narrow with `within`, nearest ancestor first, growing until unique.
    nearest_first = list(reversed(element.path))
    for n in range(1, len(nearest_first) + 1):
        within = nearest_first[:n]
        candidate: Locator = {kind: {**base, "within": within}}
        if _matches_exactly(driver, root, candidate, element):
            return candidate
    return None


def generate_locators(driver: Driver, root: Root, element: Element) -> list[Locator]:
    """Build a ranked, ladder-order locator list that resolves uniquely to `element`.

    Rung 1 (stable id) and rung 2 (role+name, narrowed with `within` if needed)
    are included only if they resolve to exactly `element`; otherwise they are
    omitted (never a guess). Rung 3 (`ocr`) is appended if the element has a
    name, rung 4 (`image`) is always a placeholder, and rung 5 (`coords`) is
    always the bbox centre, window-relative.
    """
    locators: list[Locator] = []

    rung1 = _rung1(driver, root, element)
    if rung1 is not None:
        locators.append(rung1)

    rung2 = _rung2(driver, root, element)
    if rung2 is not None:
        locators.append(rung2)

    if element.name:  # no text to find by OCR when the element is unnamed
        locators.append({"ocr": {"text": element.name}})
    locators.append({"image": None})

    x0, y0, x1, y1 = element.bbox
    locators.append({"coords": {"x": (x0 + x1) // 2, "y": (y0 + y1) // 2}})

    return locators
