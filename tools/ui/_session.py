"""tools/ui/_session.py — UiSession: shared desktop/browser state for the ui_* tools.

One UiSession lives per tool registry (one per agent session, created in
agent/tools.py only when `config.computer_use` is true). It lazily creates the
UIA and Firefox drivers only on first use — importing `uiautomation` is
Windows-only and slow, and constructing a FirefoxDriver should not spawn a
real browser process until a tool actually needs one — and holds the
ObservationStore, DesktopLock and SafetyGate that every ui_* tool call shares.

Only windows dagi opened are listed (privacy: window titles go to the model
provider): the window `ui_roots(launch=...)` returned, plus later windows of a
process dagi launched that were not already open before the launch. Browser
tabs all belong to dagi's own Firefox profile.

Root ids exposed to the model are prefixed so they stay unique across drivers:
"w:<hwnd>" for UIA windows, "b:<handle>" for Firefox tabs. `_roots` caches the
(driver, Root) pair behind each prefixed id so ui_observe/ui_act/ui_wait can
look a root up without re-listing every call.
"""
from __future__ import annotations

import os
import threading
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


class _ProcessUiState:
    """What must outlive one registry: the GUI builds a new registry (and UiSession)
    per turn, but the windows dagi opened, its drivers and its one Firefox belong to
    the dagi process. Without this, each turn forgot its windows and started another
    Firefox."""

    def __init__(self) -> None:
        self.uia_driver: Driver | None = None
        self.browser_driver: Driver | None = None
        self.owned_handles: set[str] = set()
        self.owned_pids: set[int] = set()
        self.preexisting: set[str] = set()


_PROCESS_STATE = _ProcessUiState()


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
        # Injected drivers (tests) get private state; real sessions share the process state.
        injected = uia_driver is not None or browser_driver is not None
        self._shared = _ProcessUiState() if injected else _PROCESS_STATE
        if uia_driver is not None:
            self._shared.uia_driver = uia_driver
        if browser_driver is not None:
            self._shared.browser_driver = browser_driver
        self.lock = lock if lock is not None else DesktopLock()
        self.store = ObservationStore()
        self.safety = SafetyGate(
            ask=_ask_wrapper(callbacks), autonomous=bool(getattr(config, "autonomous", False))
        )
        display = (getattr(config, "display_name", "") or getattr(config, "model", "") or "dagi")
        self.agent_name = f"{display}#{uuid.uuid4().hex[:8]}"
        # Filled in by Subtask 13 (trace recorder); None here means "not recording".
        self.recorder = None
        # Set by ESC (AgentLoop.interrupt -> UiActTool.cancel); a running replay stops at
        # its next step or wait. Cleared when the next rpa_run starts.
        self.cancel_event = threading.Event()
        # root_id (prefixed, e.g. "w:1234") -> (driver, Root); per session (re-list with ui_roots)
        self._roots: dict[str, tuple[Driver, Root]] = {}

    # -- lazy drivers --------------------------------------------------------

    def uia(self) -> Driver:
        shared = self._shared
        if shared.uia_driver is None:
            from rpa.drivers.uia import UiaDriver

            # dagi's own Firefox is driven through the browser driver (b: roots), never as a window.
            shared.uia_driver = UiaDriver(
                exclude_pids={os.getpid()},
                exclude=lambda: shared.browser_driver.pids() if shared.browser_driver is not None else set(),
            )
        return shared.uia_driver

    def browser(self) -> Driver:
        if self._shared.browser_driver is None:
            from agent import DAGI_ROOT
            from rpa.drivers.browser import FirefoxDriver

            self._shared.browser_driver = FirefoxDriver(profile_dir=DAGI_ROOT / _FIREFOX_PROFILE_SUBPATH)
        return self._shared.browser_driver

    def browser_started(self) -> bool:
        """True if dagi's Firefox is actually running — listing roots must never start it."""
        driver = self._shared.browser_driver
        return driver is not None and bool(getattr(driver, "started", True))

    # -- root bookkeeping -----------------------------------------------------

    @staticmethod
    def prefixed_id(root: Root) -> str:
        return f"w:{root.id}" if root.kind == "window" else f"b:{root.id}"

    def remember(self, driver: Driver, root: Root) -> str:
        """Cache `root` under its prefixed id and return that id."""
        root_id = self.prefixed_id(root)
        self._roots[root_id] = (driver, root)
        return root_id

    def launch_window(self, target: str) -> Root:
        """Launch a desktop app and mark its window (and later new windows of its process) as dagi's."""
        driver = self.uia()
        shared = self._shared
        shared.preexisting |= {r.id for r in driver.roots()}
        root = driver.launch(target)
        shared.owned_handles.add(root.id)
        if root.pid:
            shared.owned_pids.add(root.pid)
        return root

    def note_existing_windows(self) -> None:
        """Snapshot current windows as not-dagi's, before something (a replay) launches more."""
        self._shared.preexisting |= {r.id for r in self.uia().roots()}

    def adopt(self, root: Root) -> None:
        """Mark a window/tab that dagi launched outside ui_roots (e.g. a replay) as dagi's."""
        if root.kind == "window":
            self._shared.owned_handles.add(root.id)
            if root.pid:
                self._shared.owned_pids.add(root.pid)

    def opened_by_dagi(self, root: Root) -> bool:
        shared = self._shared
        return root.id in shared.owned_handles or (
            root.pid in shared.owned_pids and root.id not in shared.preexisting
        )

    def forget(self, root_id: str) -> None:
        self._roots.pop(root_id, None)

    def lookup(self, root_id: str) -> "tuple[Driver, Root] | None":
        return self._roots.get(root_id)

    # -- lifecycle --------------------------------------------------------

    def end_turn(self) -> None:
        """Release the desktop lock if this session holds it. Never raises."""
        try:
            self.lock.release(self.agent_name)
        except Exception:  # noqa: BLE001 — releasing must never fail the turn close
            pass
