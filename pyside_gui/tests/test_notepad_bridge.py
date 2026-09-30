from __future__ import annotations

import sys
import threading
import time

import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QCoreApplication, QObject, Slot
from PySide6.QtWidgets import QApplication

from agent import notepad_store as store
from pyside_gui import bridge as bridge_mod
from pyside_gui.bridge import AgentBridge
from tools.read_notepad import ReadNotepadTool

_app = QApplication.instance() or QApplication(sys.argv)


class _GuiPet(QObject):
    """Stands in for DesktopPetWindow on the GUI thread."""

    def __init__(self, root) -> None:
        super().__init__()
        self.root = root
        self.threads: list[threading.Thread] = []

    @Slot(object)
    def flush(self, done) -> None:
        self.threads.append(threading.current_thread())
        store.write_text("flushed by gui", self.root)
        done.set()


def _run_in_worker(fn):
    out = {}
    worker = threading.Thread(target=lambda: out.setdefault("value", fn()))
    worker.start()
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    worker.join(timeout=1)
    return out.get("value")


def test_callbacks_expose_flush():
    bridge = AgentBridge()
    assert bridge.build_callbacks().on_flush_notepad == bridge._flush_notepad


def test_worker_flush_runs_on_gui_thread_before_read(tmp_path):
    bridge = AgentBridge()
    pet = _GuiPet(tmp_path)
    bridge.notepad_flush_requested.connect(pet.flush)
    tool = ReadNotepadTool(on_flush=bridge.build_callbacks().on_flush_notepad, root=tmp_path)

    result = _run_in_worker(tool.run)

    assert pet.threads == [threading.main_thread()]
    assert result.endswith("flushed by gui")
    assert "may be missing" not in result


def test_flush_times_out_when_gui_never_answers(monkeypatch):
    monkeypatch.setattr(bridge_mod, "NOTEPAD_FLUSH_TIMEOUT_S", 0.05)
    bridge = AgentBridge()
    started = time.monotonic()
    assert _run_in_worker(bridge._flush_notepad) is False
    assert time.monotonic() - started < 2
