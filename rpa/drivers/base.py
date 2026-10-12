"""rpa/drivers/base.py — the Driver protocol shared by UIA, browser and fake drivers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from rpa import RpaError
from rpa.model import ACTIONS, Element, Locator, Outline, Root

if TYPE_CHECKING:
    from PIL import Image

__all__ = ["ACTIONS", "Driver", "WrongElement"]



class WrongElement(RpaError):
    """The live element a driver is about to act on is not the one it was given."""


class Driver(Protocol):
    """One root-type's implementation: UIA windows, Firefox tabs, or the test fake."""

    def roots(self) -> list[Root]:
        """List the currently available roots (windows or browser tabs)."""
        ...

    def outline(self, root: Root, *, query: str | None = None, depth: int | None = None) -> Outline:
        """Snapshot `root`'s element tree, optionally filtered by `query` or limited by `depth`."""
        ...

    def find(self, root: Root, locator: Locator) -> list[Element]:
        """Return every element in `root` matching `locator` (0, 1, or many)."""
        ...

    def act(self, root: Root, element: Element, action: str, value: str | None = None) -> None:
        """Perform `action` (one of ACTIONS) on `element`, with an optional `value`.

        Must raise `WrongElement` rather than act if the live element at
        `element.index` is no longer the same element."""
        ...

    def screenshot(self, root: Root, region: tuple[int, int, int, int] | None = None) -> "Image.Image":
        """Capture `root` (or `region` within it) as a PIL image."""
        ...

    def needs_desktop_lock(self, action: str) -> bool:
        """True if `action` drives the real mouse/keyboard and needs the desktop lock."""
        ...

    def close_root(self, root: Root) -> None:
        """Close the root window / browser tab itself (no element needed)."""
        ...

    def needs_desktop_lock_to_observe(self, root: Root) -> bool:
        """True if observing `root` changes the desktop (e.g. restoring a minimized window)."""
        ...

    def launch(self, target: str) -> Root:
        """Start or open `target` (exe path or URL) and return its new Root."""
        ...
