"""rpa/lock.py — process-wide desktop lock.

One holder of the real mouse and keyboard at a time across all agents and
processes. Identity is (pid, agent): two different agents running in the
same process must still exclude each other.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from rpa import RpaError

DEFAULT_PATH = Path.home() / ".dagi" / "rpa" / "desktop.lock"
# A holder writes its JSON right after the exclusive create; an unreadable file
# younger than this may be mid-write, so it is not treated as corrupt yet.
_CORRUPT_GRACE_S = 2.0
# GUI agents are threads of one process: serialize their check-then-take.
_process_lock = threading.Lock()


class DesktopBusy(RpaError):
    """Raised when another (pid, agent) holds the desktop lock."""

    def __init__(self, holder_agent: str, since: str):
        self.holder_agent = holder_agent
        self.since = since
        super().__init__(f"Desktop is locked by agent {holder_agent!r} since {since}")


class DesktopLock:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else DEFAULT_PATH

    def _read(self) -> dict | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict) or not {"pid", "agent", "since"} <= data.keys():
            return None
        return data

    def _write(self, agent: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "agent": agent,
                "since": datetime.now(timezone.utc).isoformat(),
            }
        ).encode("utf-8")
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)

    def acquire(self, agent: str) -> None:
        with _process_lock:
            self._acquire(agent)

    def _acquire(self, agent: str) -> None:
        try:
            self._write(agent)
            return
        except FileExistsError:
            pass

        holder = self._read()
        if holder is not None:
            if holder["pid"] == os.getpid() and holder["agent"] == agent:
                return  # same (pid, agent): no-op
            if psutil.pid_exists(holder["pid"]):
                raise DesktopBusy(holder["agent"], holder["since"])
            # Dead holder: remove and retry once.
        elif self._age() < _CORRUPT_GRACE_S:
            raise DesktopBusy("<starting>", "just now")
        # holder is None and the file is old: unreadable/corrupt, remove and retry once.
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

        try:
            self._write(agent)
        except FileExistsError:
            # Race: another process re-created it in between. Report that holder.
            holder = self._read()
            if holder is not None:
                raise DesktopBusy(holder["agent"], holder["since"])
            raise

    def _age(self) -> float:
        try:
            return time.time() - self.path.stat().st_mtime
        except OSError:
            return _CORRUPT_GRACE_S

    def release(self, agent: str) -> None:
        with _process_lock:
            self._release(agent)

    def _release(self, agent: str) -> None:
        holder = self._read()
        if holder is None:
            return
        if holder["pid"] == os.getpid() and holder["agent"] == agent:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def holder(self) -> dict | None:
        return self._read()
