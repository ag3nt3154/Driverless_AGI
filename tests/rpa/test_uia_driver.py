"""tests/rpa/test_uia_driver.py — ControlType/role/bbox/Electron unit tests + desktop tests.

The unit tests (no marker) check pure functions and run anywhere. The desktop
tests (`@pytest.mark.desktop`) start `tests/rpa/fixtures/qt_fixture.py` as a
subprocess and drive it with the real `UiaDriver`; they are skipped unless
`DAGI_DESKTOP_TESTS=1` (see tests/conftest.py) and must run unsandboxed. Each
desktop test that starts a fixture process always terminates it, even on
failure, via the `qt_fixture_proc` fixture's finalizer.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from rpa.drivers.uia import (
    ELECTRON_APPS,
    INTERACTIVE_ROLES,
    bbox_relative_to_window,
    control_type_to_role,
    electron_launch_args,
    is_interactive_role,
)
from rpa.resolver import is_unstable_id

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_TITLE = "RPA Qt Fixture"


# -- unit tests: pure functions, no UIA/Qt required --------------------------


@pytest.mark.parametrize(
    "control_type_name,expected",
    [
        ("ButtonControl", "Button"),
        ("EditControl", "Edit"),
        ("WindowControl", "Window"),
        ("PaneControl", "Pane"),
        ("Custom", "Custom"),  # no "Control" suffix: unchanged
    ],
)
def test_control_type_to_role(control_type_name, expected):
    assert control_type_to_role(control_type_name) == expected


@pytest.mark.parametrize("role", sorted(INTERACTIVE_ROLES))
def test_interactive_roles_are_interactive(role):
    assert is_interactive_role(role) is True


@pytest.mark.parametrize("role", ["Window", "Pane", "Group", "Text", "ToolBar"])
def test_container_roles_are_not_interactive(role):
    assert is_interactive_role(role) is False


@pytest.mark.parametrize("exe_name", sorted(ELECTRON_APPS))
def test_electron_apps_get_accessibility_flag(exe_name):
    assert electron_launch_args(exe_name) == ["--force-renderer-accessibility"]


def test_non_electron_app_gets_no_extra_args():
    assert electron_launch_args("notepad.exe") == []


class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


def test_bbox_relative_to_window_with_rect_objects():
    window_rect = _FakeRect(100, 50, 900, 650)
    element_rect = _FakeRect(120, 70, 220, 100)
    assert bbox_relative_to_window(element_rect, window_rect) == (20, 20, 120, 50)


def test_bbox_relative_to_window_with_plain_tuples():
    window_rect = (100, 50, 900, 650)
    element_rect = (120, 70, 220, 100)
    assert bbox_relative_to_window(element_rect, window_rect) == (20, 20, 120, 50)


# -- desktop tests: real UIA + real Qt fixture --------------------------------

pytestmark_desktop = pytest.mark.desktop


@pytest.fixture
def qt_fixture_proc():
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.rpa.fixtures.qt_fixture"],
        cwd=str(REPO_ROOT),
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _find_root(driver, title: str, pid: int, timeout: float = 10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for r in driver.roots():
            if r.title == title and r.pid == pid:
                return r
        time.sleep(0.2)
    raise AssertionError(f"window {title!r} (pid {pid}) did not appear within {timeout}s")


@pytest.mark.desktop
def test_outline_has_export_csv_and_secure_password(qt_fixture_proc):
    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)
    outline = driver.outline(root)

    export = next(e for e in outline.elements if e.name == "Export CSV")
    assert export.role == "Button"

    password = next(e for e in outline.elements if e.name == "Password")
    assert password.secure is True
    assert password.value == "[secure]"


@pytest.mark.desktop
def test_find_role_name_duplicates_and_stable_id(qt_fixture_proc):
    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)

    ok_matches = driver.find(root, {"uia": {"role": "Button", "name": "OK"}})
    assert len(ok_matches) == 2

    # Qt's AutomationId is a dotted path ending in the objectName (e.g.
    # "QApplication.FixtureWindow.QWidget.btnExport"), not the bare name.
    export = next(e for e in driver.outline(root).elements if e.name == "Export CSV")
    assert export.automation_id is not None
    assert export.automation_id.endswith("btnExport")
    assert not is_unstable_id(export.automation_id)

    stable_matches = driver.find(root, {"uia": {"automation_id": export.automation_id}})
    assert len(stable_matches) == 1
    assert stable_matches[0].name == "Export CSV"


@pytest.mark.desktop
def test_random_object_name_unstable_across_two_launches(qt_fixture_proc):
    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root1 = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)
    random1 = next(e for e in driver.outline(root1).elements if e.name == "Random")
    assert is_unstable_id(random1.automation_id)

    proc2 = subprocess.Popen(
        [sys.executable, "-m", "tests.rpa.fixtures.qt_fixture"],
        cwd=str(REPO_ROOT),
    )
    try:
        root2 = _find_root(driver, FIXTURE_TITLE, proc2.pid)
        random2 = next(e for e in driver.outline(root2).elements if e.name == "Random")
        assert is_unstable_id(random2.automation_id)
        assert random1.automation_id != random2.automation_id
    finally:
        proc2.terminate()
        proc2.wait(timeout=5)


@pytest.mark.desktop
def test_minimized_window_is_restored_and_outlined(qt_fixture_proc):
    import uiautomation as auto

    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)

    window = auto.ControlFromHandle(int(root.id))
    wp = window.GetPattern(auto.PatternId.WindowPattern)
    wp.SetWindowVisualState(auto.WindowVisualState.Minimized)
    time.sleep(0.3)

    outline = driver.outline(root)
    assert any(e.name == "Export CSV" for e in outline.elements)


@pytest.mark.desktop
def test_click_export_opens_save_as_and_close_window_closes_it(qt_fixture_proc):
    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)
    outline = driver.outline(root)
    export = next(e for e in outline.elements if e.name == "Export CSV")

    driver.act(root, export, "click")

    # Qt's modal dialog shows up as a nested WindowControl inside the same
    # root's tree, not as a separate top-level root.
    deadline = time.time() + 5.0
    dialog = None
    while time.time() < deadline and dialog is None:
        after = driver.outline(root)
        dialog = next((e for e in after.elements if e.role == "Window" and e.name == "Save As"), None)
        if dialog is None:
            time.sleep(0.2)
    assert dialog is not None, "Save As dialog did not appear"
    assert any(e.name == "File name:" for e in after.elements)

    driver.act(root, dialog, "close_window")

    deadline = time.time() + 5.0
    gone = False
    while time.time() < deadline:
        after = driver.outline(root)
        if not any(e.role == "Window" and e.name == "Save As" for e in after.elements):
            gone = True
            break
        time.sleep(0.2)
    assert gone, "Save As dialog did not close"


def test_act_refuses_when_the_live_element_at_the_index_changed(monkeypatch):
    """A different control now sits at the element's index: WrongElement, nothing dispatched."""
    from rpa.drivers.base import WrongElement
    from rpa.drivers.uia import UiaDriver
    from rpa.model import Element, Root

    seen = Element(index=3, role="Button", name="OK", automation_id=None,
                   bbox=(0, 0, 10, 10), value=None, secure=False, interactive=True, path=("Pane:Form",))
    now = Element(index=3, role="Button", name="Delete", automation_id=None,
                  bbox=(0, 0, 10, 10), value=None, secure=False, interactive=True, path=("Pane:Form",))
    driver = UiaDriver()
    monkeypatch.setattr(driver, "_walk", lambda root, depth=None: ([now], {3: object()}))
    dispatched = []
    monkeypatch.setattr(driver, "_dispatch", lambda *a: dispatched.append(a))
    monkeypatch.setattr("rpa.drivers.uia._failsafe_check", lambda: None)
    root = Root(id="1", kind="window", title="T", pid=1, url=None, app="a.exe")
    with pytest.raises(WrongElement):
        driver.act(root, seen, "click")
    assert dispatched == []


def test_click_needs_the_desktop_lock_because_it_may_fall_back_to_a_real_click():
    from rpa.drivers.uia import UiaDriver
    assert UiaDriver().needs_desktop_lock("click")


def test_real_input_is_refused_when_another_window_is_in_front(monkeypatch):
    """`key` on a control of root while some other window holds the foreground:
    WrongElement, and no keystroke is sent."""
    import ctypes
    from rpa.drivers import uia
    from rpa.drivers.base import WrongElement
    from rpa.model import Root

    class _Win:
        def SetActive(self):
            return True

    class _Ctrl:
        sent: list = []
        def SetFocus(self):
            return True
        def SendKeys(self, keys):
            self.sent.append(keys)

    monkeypatch.setattr(uia, "_failsafe_check", lambda: None)
    monkeypatch.setattr(uia.auto, "ControlFromHandle", lambda handle: _Win())
    monkeypatch.setattr(ctypes.windll.user32, "GetForegroundWindow", lambda: 999)
    monkeypatch.setattr(ctypes.windll.user32, "GetAncestor", lambda hwnd, flag: 999)
    root = Root(id="42", kind="window", title="Fixture", pid=1, url=None, app="a.exe")
    ctrl = _Ctrl()
    with pytest.raises(WrongElement):
        uia.UiaDriver()._dispatch(ctrl, "key", "enter", root)
    assert ctrl.sent == []


def test_electron_flag_matches_full_paths_case_insensitively():
    from rpa.drivers.uia import electron_launch_args
    assert electron_launch_args(r"C:\Program Files\Microsoft VS Code\code.EXE") == ["--force-renderer-accessibility"]


def _patched_dispatch_driver(monkeypatch):
    from rpa.drivers import uia

    class _Ctrl:
        def __init__(self):
            self.sent = []
        def SetFocus(self):
            return True
        def SendKeys(self, keys):
            self.sent.append(keys)

    guards = []
    monkeypatch.setattr(uia, "_before_real_input", lambda root: guards.append(root))
    return uia.UiaDriver(), _Ctrl(), guards


def test_key_chord_is_translated_to_uiautomation_notation(monkeypatch):
    from rpa.model import Root
    driver, ctrl, _ = _patched_dispatch_driver(monkeypatch)
    root = Root(id="1", kind="window", title="T", pid=1, url=None, app="a.exe")
    driver._dispatch(ctrl, "key", "ctrl+shift+s", root)
    assert ctrl.sent == ["{Ctrl}{Shift}s"]


def test_type_sends_braces_literally(monkeypatch):
    from rpa.model import Root
    driver, ctrl, _ = _patched_dispatch_driver(monkeypatch)
    root = Root(id="1", kind="window", title="T", pid=1, url=None, app="a.exe")
    driver._dispatch(ctrl, "type", "a{b}^+s", root)
    assert ctrl.sent == ["a{{}b{}}^+s"]


def test_bad_key_chord_fails_before_any_input(monkeypatch):
    from rpa import RpaError
    from rpa.model import Root
    driver, ctrl, guards = _patched_dispatch_driver(monkeypatch)
    root = Root(id="1", kind="window", title="T", pid=1, url=None, app="a.exe")
    with pytest.raises(RpaError):
        driver._dispatch(ctrl, "key", "^+s", root)
    assert ctrl.sent == [] and guards == []


def test_launch_does_not_hand_console_handles_to_the_app(monkeypatch):
    import subprocess as sp
    from rpa import RpaError
    from rpa.drivers import uia
    seen = {}

    class _Proc:
        pid = 0
        def kill(self):
            pass

    monkeypatch.setattr(uia.subprocess, "Popen", lambda argv, **kw: (seen.update(kw), _Proc())[1])
    driver = uia.UiaDriver()
    monkeypatch.setattr(driver, "roots", lambda: [])
    monkeypatch.setattr(uia.auto, "GetRootControl", lambda: type("R", (), {"GetChildren": lambda self: []})())
    monkeypatch.setattr(uia.time, "time", iter([0, 0, 100]).__next__)
    monkeypatch.setattr(uia.time, "sleep", lambda s: None)
    with pytest.raises(RpaError):
        driver.launch("notepad.exe")
    assert seen["stdout"] is sp.DEVNULL and seen["stderr"] is sp.DEVNULL and seen["close_fds"]


@pytest.mark.desktop
def test_type_and_key_reach_the_fixture_literally(qt_fixture_proc):
    from rpa.drivers.uia import UiaDriver

    driver = UiaDriver()
    root = _find_root(driver, FIXTURE_TITLE, qt_fixture_proc.pid)
    comment = next(e for e in driver.outline(root).elements if e.name == "Comment" and e.role == "Edit")
    driver.act(root, comment, "type", "x{y}^+s")
    comment = next(e for e in driver.outline(root).elements if e.name == "Comment" and e.role == "Edit")
    assert comment.value == "x{y}^+s"
    driver.act(root, comment, "key", "ctrl+a")
    driver.act(root, comment, "key", "backspace")
    comment = next(e for e in driver.outline(root).elements if e.name == "Comment" and e.role == "Edit")
    assert comment.value == ""
