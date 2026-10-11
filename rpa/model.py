"""rpa/model.py — shared data types: Root, Element, Locator, Outline.

Frozen dataclasses so observations and traces can be hashed/compared safely.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

from rpa import RpaError

ACTIONS = (
    "click",
    "double_click",
    "right_click",
    "set_value",
    "type",
    "key",
    "scroll",
    "select",
    "upload",
    "focus",
    "close_window",
)

_LOCATOR_KINDS = ("uia", "css", "aria", "ocr", "image", "coords")


@dataclass(frozen=True)
class Root:
    """A top-level window or browser tab/window that a driver can act on."""

    id: str
    kind: Literal["window", "browser"]
    title: str
    pid: int | None
    url: str | None
    app: str  # exe name (window) or page origin (browser) — used for D5 permissions


@dataclass(frozen=True)
class Element:
    """One node in an outline. `path` is the role:name of each ancestor, root-first.

    `bbox` is (left, top, right, bottom) in pixels relative to the root window's (or
    browser viewport's) top-left corner; every driver converts to this frame.
    """

    index: int
    role: str
    name: str
    automation_id: str | None
    bbox: tuple[int, int, int, int]
    value: str | None
    secure: bool
    interactive: bool
    path: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.secure and self.value != "[secure]":
            object.__setattr__(self, "value", "[secure]")


# A Locator is a dict with exactly one key among _LOCATOR_KINDS.
Locator = dict


def validate_locator(locator: Locator) -> None:
    """Raise RpaError unless `locator` has exactly one key from _LOCATOR_KINDS."""
    keys = [k for k in locator if k in _LOCATOR_KINDS]
    unknown = [k for k in locator if k not in _LOCATOR_KINDS]
    if unknown:
        raise RpaError(f"unknown locator key(s): {unknown}")
    if len(keys) != 1:
        raise RpaError(f"locator must have exactly one key from {_LOCATOR_KINDS}, got {list(locator)}")


@dataclass(frozen=True)
class Outline:
    """A snapshot of one root's elements at a point in time."""

    root: Root
    elements: list[Element]
    taken_at: float = field(default_factory=time.time)
