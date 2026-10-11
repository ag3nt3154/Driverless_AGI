"""tools/ui/_session.py — UiSession: shared desktop/browser state for the ui_* tools.

One UiSession lives per tool registry (one per agent session, created in
agent/tools.py only when `config.computer_use` is true). It lazily creates the
UIA and Firefox drivers only on first use — importing `uiautomation` is
Windows-only and slow, and constructing a FirefoxDriver should not spawn a
real browser process until a tool actually needs one — and holds the
ObservationStore, DesktopLock and SafetyGate that every ui_* tool call shares.

Root ids exposed to the model are prefixed so they stay unique across drivers:
"w:<hwnd>" for UIA windows, "b:<handle>" for Firefox tabs. `_roots` caches the
(driver, Root) pair behind each prefixed id so ui_observe/ui_act/ui_wait can
look a root up without re-listing every call.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Callable

from rpa.drivers.base import Driver
from rpa.lock import DesktopLock
from rpa.model import Root
from rpa.observe import ObservationStore
from rpa.safety import SafetyGate

_FIREFOX_PROFILE_SUBPATH = Path(".dagi") / "rpa" / "firefox-profile"


def _ask_wrapper(callbacks) -> "Callable[[str, list[dict]], str] | None":
    """`ask` for SafetyGate: calls callbacks.on_ask_user with no timeout, or
    None (deny) when there is no frontend to answer — e.g. autonomous runs."""
    if callbacks is None or getattr(callbacks, "on_ask_user", None) is None:
        return None

    def ask(question: str, options: list[dict]) -> str:
        return callbacks.on_ask_user(question, options, None)

    return ask


class UiSession:
    """Per-registry state shared by ui_roots / ui_observe / ui_act / ui_wait."""

    def __init__(
        self,
        config,
        callbacks=None,
        *,
        uia_driver: Driver | None = None,
        browser_driver: Driver | None = None,
        lock: DesktopLock | None = None,
    ) -> None:
        self.config = config
        self.callbacks = callbacks
        self._uia_driver = uia_driver
        self._browser_driver = browser_driver
        self.lock = lock if lock is not None else DesktopLock()
        self.store = ObservationStore()
        self.safety = SafetyGate(
            ask=_ask_wrapper(callbacks), autonomous=bool(getattr(config, "autonomous", False))
        )
        display = (getattr(config, "display_name", "") or getattr(config, "model", "") or "dagi")
        self.agent_name = f"{display}#{uuid.uuid4().hex[:8]}"
        # Filled in by Subtask 13 (trace recorder); None here means "not recording".
        self.recorder = None
        # root_id (prefixed, e.g. "w:1234") -> (driver, Root)
        self._roots: dict[str, tuple[Driver, Root]] = {}

    # -- lazy drivers --------------------------------------------------------

    def uia(self) -> Driver:
        if self._uia_driver is None:
            from rpa.drivers.uia import UiaDriver

            self._uia_driver = UiaDriver(exclude_pids={os.getpid()})
        return self._uia_driver

    def browser(self) -> Driver:
        if self._browser_driver is None:
            from agent import DAGI_ROOT
            from rpa.drivers.browser import FirefoxDriver

            self._browser_driver = FirefoxDriver(profile_dir=DAGI_ROOT / _FIREFOX_PROFILE_SUBPATH)
        return self._browser_driver

    def browser_started(self) -> bool:
        """True if the browser driver has been used at least once this session."""
        return self._browser_driver is not None

    # -- root bookkeeping -----------------------------------------------------

    @staticmethod
    def prefixed_id(root: Root) -> str:
        return f"w:{root.id}" if root.kind == "window" else f"b:{root.id}"

    def remember(self, driver: Driver, root: Root) -> str:
        """Cache `root` under its prefixed id and return that id."""
        root_id = self.prefixed_id(root)
        self._roots[root_id] = (driver, root)
        return root_id

    def lookup(self, root_id: str) -> "tuple[Driver, Root] | None":
        return self._roots.get(root_id)

    # -- lifecycle --------------------------------------------------------

    def end_turn(self) -> None:
        """Release the desktop lock if this session holds it. Never raises."""
        try:
            self.lock.release(self.agent_name)
        except Exception:  # noqa: BLE001 — releasing must never fail the turn close
            pass
