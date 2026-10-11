"""tests/rpa/test_hotkey.py — a physical Esc anywhere stops a replay."""
from __future__ import annotations

import sys

import pytest

from rpa.hotkey import EscWatcher, is_physical_escape


def test_only_a_physical_escape_key_down_counts():
    assert is_physical_escape(0x1B, 0, 0x0100)
    assert is_physical_escape(0x1B, 0, 0x0104)  # with Alt held
    assert not is_physical_escape(0x1B, 0x10, 0x0100)  # injected by the replay itself
    assert not is_physical_escape(0x1B, 0, 0x0101)  # key-up
    assert not is_physical_escape(0x41, 0, 0x0100)  # "A"


@pytest.mark.desktop  # installs a real system-wide keyboard hook briefly
@pytest.mark.skipif(sys.platform != "win32", reason="Windows keyboard hook")
def test_watcher_installs_and_removes_its_hook_without_hanging():
    import time
    t0 = time.monotonic()
    with EscWatcher(lambda: None) as watcher:
        assert watcher._thread is not None and watcher._thread.is_alive()
    watcher._thread.join(2.0)
    assert not watcher._thread.is_alive() and time.monotonic() - t0 < 5


@pytest.mark.desktop  # installs a real system-wide keyboard hook briefly
@pytest.mark.skipif(sys.platform != "win32", reason="Windows keyboard hook")
def test_injected_escape_does_not_trigger_the_watcher():
    import ctypes
    import time
    hits: list = []
    with EscWatcher(lambda: hits.append(1)):
        ctypes.windll.user32.keybd_event(0x1B, 0, 0, 0)  # injected key-down
        ctypes.windll.user32.keybd_event(0x1B, 0, 2, 0)  # key-up
        time.sleep(0.3)
    assert hits == []
