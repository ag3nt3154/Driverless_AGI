"""rpa/drivers/uia.py — UiaDriver: Driver implementation for Windows desktop apps.

Backed by `uiautomation` (UIA). Element -> live control mapping: `Element` is a
snapshot (no control handle survives across calls), so `act()` never reuses a
control from a previous `outline()`/`find()` call. Instead `act()` runs a fresh
`_walk()` of `root` immediately before acting and looks the live control up by
`element.index` (document-order walk index, same convention as `FakeDriver`:
rebuilt on every walk), then checks the live node's role, name, automation_id
and path equal `element`'s — a difference raises `WrongElement` instead of
acting on whatever now sits at that index. This is also why `index` assignment must be
deterministic: `outline()`, `find()` and `act()` all walk the same tree with
the same pre-order traversal, so the same node gets the same index within one
call. `close_window` closes the nearest `WindowControl` ancestor of `element`
(itself if `element` is already a window): a Qt modal dialog, for example,
shows up as a nested `WindowControl` inside the parent's own tree rather than
as a separate top-level root, so a plain "close the root window" would be
wrong for it.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import time
from pathlib import Path

import psutil
import uiautomation as auto

from rpa import RpaError
from rpa.drivers.base import WrongElement
from rpa.model import ACTIONS, Element, Locator, Outline, Root, validate_locator

MAX_DEPTH = 30
MAX_NODES = 1500

#: Known Electron apps that need `--force-renderer-accessibility` to expose a
#: full UIA tree (S0: without it VS Code exposed 19 nodes instead of 403).
ELECTRON_APPS = {"Code.exe", "Claude.exe", "Slack.exe", "Discord.exe", "Teams.exe"}

#: ControlTypeName values (role, "Control" suffix stripped) that are
#: actionable leaf controls (S0 probes: Button/Edit/etc. carry Invoke/Value/
#: Toggle/SelectionItem patterns; containers like Window/Pane/Group do not).
INTERACTIVE_ROLES = {
    "Button",
    "Edit",
    "CheckBox",
    "ComboBox",
    "RadioButton",
    "MenuItem",
    "ListItem",
    "TabItem",
    "Hyperlink",
    "Slider",
    "Spinner",
    "TreeItem",
    "DataItem",
    "SplitButton",
}

#: Actions that drive (or may fall back to) the real mouse/keyboard and need the
#: desktop lock (D4/D10). `click` falls back to a real click when the control has
#: no Invoke/Toggle/SelectionItem pattern, which is only known at act time.
_LOCK_ACTIONS = {"click", "type", "key", "double_click", "right_click"}


class FailsafeAbort(RpaError):
    """The cursor sat in a screen corner right before a real-input action."""


def control_type_to_role(control_type_name: str) -> str:
    """'ButtonControl' -> 'Button'. Pure, unit-testable without a live UIA tree."""
    return control_type_name[: -len("Control")] if control_type_name.endswith("Control") else control_type_name


def is_interactive_role(role: str) -> bool:
    """True if `role` (already stripped of 'Control') is an actionable leaf control type."""
    return role in INTERACTIVE_ROLES


def electron_launch_args(exe_name: str) -> list[str]:
    """`--force-renderer-accessibility` if `exe_name` (a name or path) is a known Electron app (S0)."""
    name = os.path.basename(exe_name).lower()
    return ["--force-renderer-accessibility"] if name in {a.lower() for a in ELECTRON_APPS} else []


def bbox_relative_to_window(rect, window_rect) -> tuple[int, int, int, int]:
    """Convert a screen-coordinate rect to one relative to `window_rect`'s top-left corner.

    Accepts a `uiautomation` `Rect` (`.left/.top/.right/.bottom`) or a plain
    4-tuple for either argument, so this is testable without a live window.
    """

    def _coords(r) -> tuple[int, int, int, int]:
        if hasattr(r, "left"):
            return r.left, r.top, r.right, r.bottom
        return tuple(r)  # type: ignore[return-value]

    left, top, right, bottom = _coords(rect)
    win_left, win_top, _, _ = _coords(window_rect)
    return (left - win_left, top - win_top, right - win_left, bottom - win_top)


_GA_ROOTOWNER = 3


def _before_real_input(root: Root) -> None:
    """Gate every real mouse/keyboard event: failsafe corner, then root in front.

    Brings `root` to the foreground and refuses (WrongElement) unless the
    foreground window is `root` or a window it owns (a modal dialog is a separate
    owned HWND even though UIA nests it in the parent's tree).
    """
    _failsafe_check()
    window = auto.ControlFromHandle(int(root.id))
    if window is None:
        raise WrongElement(f"UiaDriver: window {root.title!r} no longer exists")
    window.SetActive()
    user32 = ctypes.windll.user32
    fg = user32.GetForegroundWindow()
    if fg != int(root.id) and user32.GetAncestor(fg, _GA_ROOTOWNER) != int(root.id):
        raise WrongElement(
            f"UiaDriver: {root.title!r} is not the foreground window; refusing real input"
        )


def _make_dpi_aware() -> None:
    """Per-monitor DPI awareness so UIA rects, the cursor and mss share physical pixels.

    Best-effort: a process that already set it (Qt does at startup) keeps its own.
    """
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except (AttributeError, OSError):
        pass


def _identity(element: Element) -> tuple:
    return element.role, element.name, element.automation_id, element.path


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _cursor_in_corner(margin: int = 2) -> bool:
    """True if the mouse cursor sits within `margin` px of any screen corner."""
    user32 = ctypes.windll.user32

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = _Point()
    user32.GetCursorPos(ctypes.byref(pt))
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    return any(abs(pt.x - cx) <= margin and abs(pt.y - cy) <= margin for cx, cy in corners)


def _failsafe_check() -> None:
    if _cursor_in_corner():
        raise FailsafeAbort("cursor is in a screen corner; aborting real input")


def _read_value(ctrl: auto.Control) -> str | None:
    vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
    if vp is None:
        return None
    try:
        return vp.Value
    except Exception:
        return None


class UiaDriver:
    """Driver for Windows desktop windows, via `uiautomation`."""

    def __init__(self, exclude_pids: set[int] | None = None) -> None:
        _make_dpi_aware()
        self._exclude_pids = set(exclude_pids or set()) | {os.getpid()}

    # -- Driver protocol -------------------------------------------------

    def roots(self) -> list[Root]:
        out: list[Root] = []
        for ctrl in auto.GetRootControl().GetChildren():
            if ctrl.ControlTypeName != "WindowControl":
                continue
            try:
                pid = ctrl.ProcessId
                handle = ctrl.NativeWindowHandle
            except Exception:
                continue
            if pid in self._exclude_pids or not handle:
                continue
            out.append(
                Root(id=str(handle), kind="window", title=ctrl.Name or "", pid=pid, url=None, app=_process_name(pid))
            )
        return out

    def outline(self, root: Root, *, query: str | None = None, depth: int | None = None) -> Outline:
        elements, _controls = self._walk(root, depth=depth)
        if query is not None:
            elements = [e for e in elements if query.lower() in e.name.lower()]
        return Outline(root=root, elements=elements)

    def find(self, root: Root, locator: Locator) -> list[Element]:
        validate_locator(locator)
        kind = next(iter(locator))
        elements, _controls = self._walk(root)
        if kind == "uia":
            spec = locator["uia"]
            return [e for e in elements if self._match_uia(e, spec)]
        if kind == "coords":
            point = locator["coords"]
            return [e for e in elements if self._contains(e.bbox, point["x"], point["y"])]
        # css/aria/ocr/image: not resolved by the desktop driver.
        return []

    def act(self, root: Root, element: Element, action: str, value: str | None = None) -> None:
        if action not in ACTIONS:
            raise RpaError(f"UiaDriver.act: unknown action {action!r}")

        if self.needs_desktop_lock(action):
            _failsafe_check()

        elements, controls = self._walk(root)
        ctrl = controls.get(element.index)
        live = next((e for e in elements if e.index == element.index), None)
        if ctrl is None or live is None or _identity(live) != _identity(element):
            raise WrongElement(
                f"UiaDriver.act: the UI changed; {element.role} {element.name!r} is no longer "
                f"at index {element.index}; re-resolve it"
            )
        self._dispatch(ctrl, action, value, root)

    def screenshot(self, root: Root, region: tuple[int, int, int, int] | None = None):
        import mss
        from PIL import Image

        window = self._get_window(root)
        rect = window.BoundingRectangle
        left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        if region is not None:
            rx0, ry0, rx1, ry1 = region
            left, top, right, bottom = left + rx0, top + ry0, left + rx0 + (rx1 - rx0), top + ry0 + (ry1 - ry0)
        box = {"left": left, "top": top, "width": max(1, right - left), "height": max(1, bottom - top)}
        with mss.mss() as sct:
            shot = sct.grab(box)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def needs_desktop_lock(self, action: str) -> bool:
        return action in _LOCK_ACTIONS

    def needs_desktop_lock_to_observe(self, root: Root) -> bool:
        """Observing a minimized window restores it first, which takes focus."""
        wp = self._get_window(root).GetPattern(auto.PatternId.WindowPattern)
        return wp is not None and wp.WindowVisualState == auto.WindowVisualState.Minimized

    def launch(self, target: str) -> Root:
        exe_name = os.path.basename(target)
        args = electron_launch_args(exe_name)
        before_handles = {r.id for r in self.roots()}
        proc = subprocess.Popen([target, *args])
        stem = Path(target).stem.lower()

        deadline = time.time() + 20
        while time.time() < deadline:
            for ctrl in auto.GetRootControl().GetChildren():
                if ctrl.ControlTypeName != "WindowControl":
                    continue
                try:
                    pid = ctrl.ProcessId
                    handle = ctrl.NativeWindowHandle
                except Exception:
                    continue
                if not handle or str(handle) in before_handles:
                    continue
                title = ctrl.Name or ""
                if pid == proc.pid or stem in title.lower():
                    return Root(id=str(handle), kind="window", title=title, pid=pid, url=None, app=_process_name(pid))
            time.sleep(0.2)
        proc.kill()
        raise RpaError(f"UiaDriver.launch: no window appeared for {target!r} within 20s")

    # -- internals ---------------------------------------------------------

    def _get_window(self, root: Root) -> auto.Control:
        window = auto.ControlFromHandle(int(root.id))
        if window is None:
            raise RpaError(f"UiaDriver: window handle {root.id} no longer exists")
        return window

    def _restore_if_minimized(self, window: auto.Control) -> None:
        wp = window.GetPattern(auto.PatternId.WindowPattern)
        if wp is not None and wp.WindowVisualState == auto.WindowVisualState.Minimized:
            wp.SetWindowVisualState(auto.WindowVisualState.Normal)
            time.sleep(0.3)

    def _walk(self, root: Root, *, depth: int | None = None) -> tuple[list[Element], dict[int, auto.Control]]:
        """Walk `root`'s window in document order, building elements and an index->control map.

        `depth` bounds levels below the window (default `MAX_DEPTH`); the walk
        also stops after `MAX_NODES` elements. Restores a minimized window first
        (S0: minimized windows expose ~nothing).
        """
        window = self._get_window(root)
        self._restore_if_minimized(window)
        window_rect = window.BoundingRectangle
        max_depth = depth if depth is not None else MAX_DEPTH

        elements: list[Element] = []
        controls: dict[int, auto.Control] = {}
        ancestors_by_depth: dict[int, auto.Control] = {}
        index = 0

        for ctrl, level in auto.WalkControl(window, includeTop=True, maxDepth=max_depth):
            if level == 0:
                continue  # the window itself: not an outline element, not part of `path`
            if index >= MAX_NODES:
                break
            for stale in [d for d in ancestors_by_depth if d >= level]:
                del ancestors_by_depth[stale]
            path = tuple(
                f"{control_type_to_role(ancestors_by_depth[d].ControlTypeName)}:{ancestors_by_depth[d].Name or ''}"
                for d in sorted(ancestors_by_depth)
            )
            ancestors_by_depth[level] = ctrl

            role = control_type_to_role(ctrl.ControlTypeName)
            try:
                secure = bool(ctrl.IsPassword)
            except Exception:
                secure = False
            try:
                rect = ctrl.BoundingRectangle
            except Exception:
                rect = window_rect
            value = "[secure]" if secure else _read_value(ctrl)
            element = Element(
                index=index,
                role=role,
                name=ctrl.Name or "",
                automation_id=ctrl.AutomationId or None,
                bbox=bbox_relative_to_window(rect, window_rect),
                value=value,
                secure=secure,
                interactive=is_interactive_role(role),
                path=path,
            )
            elements.append(element)
            controls[index] = ctrl
            index += 1

        return elements, controls

    def _dispatch(self, ctrl: auto.Control, action: str, value: str | None, root: Root) -> None:
        if action == "click":
            self._click(ctrl, root)
        elif action == "double_click":
            _before_real_input(root)
            ctrl.DoubleClick()
        elif action == "right_click":
            _before_real_input(root)
            ctrl.RightClick()
        elif action == "set_value":
            vp = ctrl.GetPattern(auto.PatternId.ValuePattern)
            if vp is None:
                raise RpaError("UiaDriver.act: set_value requires a ValuePattern")
            vp.SetValue(value or "")
        elif action in ("type", "key"):
            _before_real_input(root)
            ctrl.SetFocus()
            _before_real_input(root)  # SetFocus must not have moved focus out of root
            ctrl.SendKeys(value or "")
        elif action == "scroll":
            self._scroll(ctrl, value)
        elif action == "select":
            sip = ctrl.GetPattern(auto.PatternId.SelectionItemPattern)
            if sip is None:
                raise RpaError("UiaDriver.act: select requires a SelectionItemPattern")
            sip.Select()
        elif action == "focus":
            ctrl.SetFocus()
        elif action == "close_window":
            self._close_window(ctrl)
        elif action == "upload":
            raise RpaError("UiaDriver.act: upload is not supported by the desktop driver")
        else:
            raise RpaError(f"UiaDriver.act: action {action!r} is not implemented")

    def _close_window(self, ctrl: auto.Control) -> None:
        """Close `ctrl`'s own window, or its nearest WindowControl ancestor.

        A modal child (e.g. a Qt "Save As" dialog) shows up in UIA as a nested
        `WindowControl` under the parent's tree rather than as a separate top-
        level root, so `close_window` walks up from any element to the window
        that owns it instead of always targeting `root`'s own window.
        """
        target: auto.Control | None = ctrl
        while target is not None and target.ControlTypeName != "WindowControl":
            target = target.GetParentControl()
        if target is None:
            raise RpaError("UiaDriver.act: close_window found no window ancestor")
        wp = target.GetPattern(auto.PatternId.WindowPattern)
        if wp is None:
            raise RpaError("UiaDriver.act: close_window requires a WindowPattern")
        wp.Close()

    def _click(self, ctrl: auto.Control, root: Root) -> None:
        ip = ctrl.GetPattern(auto.PatternId.InvokePattern)
        if ip is not None:
            ip.Invoke()
            return
        tp = ctrl.GetPattern(auto.PatternId.TogglePattern)
        if tp is not None:
            tp.Toggle()
            return
        sip = ctrl.GetPattern(auto.PatternId.SelectionItemPattern)
        if sip is not None:
            sip.Select()
            return
        _before_real_input(root)
        ctrl.Click()

    def _scroll(self, ctrl: auto.Control, value: str | None) -> None:
        sp = ctrl.GetPattern(auto.PatternId.ScrollPattern)
        if sp is None:
            raise RpaError("UiaDriver.act: scroll requires a ScrollPattern")
        direction = (value or "down").lower()
        amount = auto.ScrollAmount.SmallIncrement if direction == "down" else auto.ScrollAmount.SmallDecrement
        sp.Scroll(auto.ScrollAmount.NoAmount, amount)

    @staticmethod
    def _contains(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bbox
        return x0 <= x <= x1 and y0 <= y <= y1

    @staticmethod
    def _match_uia(element: Element, spec: dict) -> bool:
        if "automation_id" in spec and element.automation_id != spec["automation_id"]:
            return False
        if "role" in spec and element.role != spec["role"]:
            return False
        if "name" in spec and element.name != spec["name"]:
            return False
        if "name_re" in spec:
            import re

            if not re.search(spec["name_re"], element.name):
                return False
        within = spec.get("within")
        if within is not None:
            wanted = [within] if isinstance(within, str) else list(within)
            if not all(w in element.path for w in wanted):
                return False
        return True
