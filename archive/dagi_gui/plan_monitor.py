"""Plan-file monitor — watches PLAN.md (or any path) for changes and
emits plan_update events to the GUI via the EventWriter.

Strategy:
  1. Try watchdog (watchfiles-style inotify/ReadDirectoryChangesW) — instant.
  2. Fall back to 5-second polling if watchdog is unavailable.

The monitor runs in a daemon thread and is safe to start/stop multiple times.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dagi_gui.protocol import EventWriter


class PlanMonitor:
    """Watch a PLAN.md file and emit plan_update events on change.

    Usage:
        monitor = PlanMonitor(writer, plan_path)
        monitor.start()
        # ... later ...
        monitor.stop()
    """

    _POLL_INTERVAL: float = 5.0

    def __init__(self, writer: "EventWriter", plan_path: Path | str) -> None:
        self._writer = writer
        self._path = Path(plan_path)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start monitoring in a daemon thread. No-op if already running."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        # Emit current content immediately so the GUI shows it on connect
        self._emit_if_exists()
        try:
            self._thread = threading.Thread(
                target=self._watch_watchdog, daemon=True, name="plan-monitor-wd"
            )
            self._thread.start()
        except Exception:
            self._thread = threading.Thread(
                target=self._watch_poll, daemon=True, name="plan-monitor-poll"
            )
            self._thread.start()

    def stop(self) -> None:
        """Signal the monitor thread to exit."""
        self._stop_event.set()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit_if_exists(self) -> None:
        if self._path.exists():
            try:
                content = self._path.read_text(encoding="utf-8")
                self._writer.write("plan_update", content=content)
            except OSError:
                pass

    def _watch_watchdog(self) -> None:
        """Use watchdog for instant filesystem events."""
        from watchdog.observers import Observer  # type: ignore[import-untyped]
        from watchdog.events import FileSystemEventHandler, FileSystemEvent  # type: ignore

        plan_path = self._path

        class _Handler(FileSystemEventHandler):
            def __init__(self, monitor: PlanMonitor) -> None:
                self._monitor = monitor

            def on_modified(self, event: FileSystemEvent) -> None:
                if Path(str(event.src_path)).resolve() == plan_path.resolve():
                    self._monitor._emit_if_exists()

            def on_created(self, event: FileSystemEvent) -> None:
                self.on_modified(event)

        observer = Observer()
        observer.schedule(_Handler(self), str(plan_path.parent), recursive=False)
        observer.start()
        try:
            while not self._stop_event.is_set():
                time.sleep(0.5)
        finally:
            observer.stop()
            observer.join(timeout=2)

    def _watch_poll(self) -> None:
        """Polling fallback — checks mtime every _POLL_INTERVAL seconds."""
        last_mtime: float | None = None
        while not self._stop_event.wait(timeout=self._POLL_INTERVAL):
            try:
                mtime = self._path.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    self._emit_if_exists()
            except OSError:
                last_mtime = None
