"""A private, GUI-owned temporary message board process and its run folders."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from agent import DAGI_ROOT
from agent.board_client import BoardClient, BoardError
from services.message_board.runtime_records import (
    RecordError, discover_record, lock_file, open_lock, protect,
)


def check_health(client, remaining: float) -> dict:
    if remaining <= 0:
        raise BoardError("TIMEOUT", "message board startup deadline expired")
    original = getattr(client, "timeout", None)
    if original is not None:
        client.timeout = min(float(original), max(0.001, remaining))
    try:
        health = client.health()
    finally:
        if original is not None:
            client.timeout = original
    if not isinstance(health, dict) or type(health.get("version")) is not int:
        raise BoardError("NOT_A_BOARD", "the address returned an incompatible health response")
    if health["version"] != 1:
        raise BoardError("NOT_A_BOARD", "the address runs an incompatible board version")
    return health


def is_cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


def _lock_owned(path: Path, *, blocking: bool):
    stream = open_lock(path)
    try:
        if lock_file(stream, blocking=blocking):
            return stream
    except BaseException:
        stream.close()
        raise
    stream.close()
    return None


def _sweep_stale_locked(root: Path) -> None:
    for run in root.iterdir():
        if not run.is_dir():
            continue
        owner = _lock_owned(run / "owner.lock", blocking=False)
        if owner is not None:
            lock_file(owner, unlock=True)
            owner.close()
            shutil.rmtree(run, ignore_errors=True)


def sweep_stale(root: Path) -> None:
    """Remove run folders whose owner lock is no longer held."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    protect(root)
    lifecycle = _lock_owned(root / ".lifecycle.lock", blocking=True)
    try:
        _sweep_stale_locked(root)
    finally:
        lock_file(lifecycle, unlock=True)
        lifecycle.close()


def _spawn_temp(command, *, run_dir: Path, spawn=subprocess.Popen):
    options = {
        "cwd": DAGI_ROOT,
        "stdin": subprocess.PIPE,
        "stdout": None,
        "stderr": None,
        "close_fds": True,
    }
    log = (run_dir / "board.log").open("ab")
    options["stdout"] = log
    options["stderr"] = log
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return spawn(command, **options)
    finally:
        log.close()


class TempBoard:
    """A private board process whose lifetime and temporary data belong to this GUI run."""

    def __init__(self, run_dir: Path, process, owner_lock, url: str) -> None:
        self.run_dir = Path(run_dir)
        self.process = process
        self.url = url
        self._owner_lock = owner_lock
        self._closed = False
        self._close_lock = threading.Lock()

    @classmethod
    def start(cls, root=DAGI_ROOT / ".dagi" / "board" / "temp", *,
              spawn=None, wait_s: float = 10.0, cancel=None) -> TempBoard:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        protect(root)
        lifecycle = _lock_owned(root / ".lifecycle.lock", blocking=True)
        run_dir = None
        created = False
        owner = None
        process = None
        try:
            _sweep_stale_locked(root)
            run_dir = root / uuid.uuid4().hex[:8]
            try:
                run_dir.mkdir()
                created = True
                protect(run_dir)
                owner = _lock_owned(run_dir / "owner.lock", blocking=False)
                if owner is None:
                    raise BoardError("SPAWN_FAILED", "cannot claim temporary board run folder")
            except BaseException:
                if owner is not None:
                    lock_file(owner, unlock=True)
                    owner.close()
                    owner = None
                if created:
                    shutil.rmtree(run_dir, ignore_errors=True)
                raise
        finally:
            lock_file(lifecycle, unlock=True)
            lifecycle.close()

        try:
            command = [
                sys.executable, "-m", "services.message_board", "serve",
                "--host", "127.0.0.1", "--port", "0",
                "--db", str(run_dir / "board.sqlite3"),
                "--runtime-dir", str(run_dir / "run"), "--exit-with-stdin", "--no-token",
            ]
            process = _spawn_temp(command, run_dir=run_dir, spawn=spawn or subprocess.Popen)
            deadline = time.monotonic() + wait_s
            record = None
            record_error = None
            while time.monotonic() < deadline:
                if is_cancelled(cancel):
                    raise BoardError("CANCELLED", "message board startup cancelled")
                if process.poll() is not None:
                    detail = (run_dir / "board.log").read_text(errors="replace")
                    raise BoardError("SPAWN_FAILED", detail.strip() or
                                     "temporary message board exited during startup")
                try:
                    record = discover_record(run_dir / "run")
                    break
                except (OSError, RecordError, ValueError) as error:
                    record_error = str(error)
                    time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            if record is None:
                detail = (run_dir / "board.log").read_text(errors="replace")
                parts = [part for part in (record_error, detail.strip()) if part]
                reason = "; ".join(parts) or "no protected runtime record found"
                raise BoardError("SPAWN_FAILED", f"temporary message board did not publish its runtime record: {reason}")
            port = record["port"]
            url = record["url"]
            expected = f"http://127.0.0.1:{port}"
            if url != expected:
                raise BoardError("SPAWN_FAILED", "temporary message board published an invalid URL")
            client = BoardClient(url, None, timeout=min(1.0, max(0.1, wait_s)))
            try:
                while time.monotonic() < deadline:
                    if is_cancelled(cancel):
                        raise BoardError("CANCELLED", "message board startup cancelled")
                    if process.poll() is not None:
                        raise BoardError("SPAWN_FAILED", "temporary message board exited during startup")
                    try:
                        check_health(client, max(0.1, deadline - time.monotonic()))
                        return cls(run_dir, process, owner, url)
                    except BoardError as error:
                        if error.code not in ("UNREACHABLE", "TIMEOUT"):
                            raise BoardError("SPAWN_FAILED", error.message) from error
                    time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
            finally:
                client.close()
            raise BoardError("SPAWN_FAILED", "temporary message board did not become ready")
        except BaseException as error:
            if process is not None:
                _stop_process(process)
            if owner is not None:
                lock_file(owner, unlock=True)
                owner.close()
            if run_dir is not None:
                shutil.rmtree(run_dir, ignore_errors=True)
            if isinstance(error, BoardError):
                raise
            raise BoardError("SPAWN_FAILED", "cannot start the temporary message board") from error

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            _stop_process(self.process)
            lock_file(self._owner_lock, unlock=True)
            self._owner_lock.close()
            shutil.rmtree(self.run_dir, ignore_errors=True)


def _stop_process(process) -> None:
    stdin = getattr(process, "stdin", None)
    if stdin is not None and not stdin.closed:
        stdin.close()
    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
