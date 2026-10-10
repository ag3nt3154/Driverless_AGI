"""Qt-free message board lifecycle, persistent GUI identity and SSE listener."""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent import DAGI_ROOT
from agent.board_client import BoardClient, BoardError, BoardSession
from services.message_board.lifecycle import DEFAULT_URL
from services.message_board.runtime_records import (
    RecordError, discover_record, lock_file, open_lock, protect,
)
from services.message_board.settings import DEFAULT_BIND

DEFAULT_BOARD_URL = DEFAULT_URL
_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


def error_text(error: BaseException) -> str:
    """User-facing text for a board failure shown in status lines and cards."""
    if isinstance(error, BoardError):
        return error.message
    return str(error) or type(error).__name__


def should_render_inline(post: dict, main_handle: str, meme_map: dict[str, Path]) -> Path | None:
    """Resolve a main-agent meme for the conversation without trusting remote paths."""
    if post.get("author") != main_handle:
        return None
    meme = post.get("meme")
    return meme_map.get(meme) if isinstance(meme, str) else None


def is_loopback_url(url: str) -> bool:
    try:
        host, _ = _service_address(url)
    except BoardError:
        return False
    try:
        if host.lower().rstrip(".") == "localhost":
            return True
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_loopback


def _valid_handle(value: str, slug: str) -> bool:
    head, separator, tail = value.partition("_")
    return head == slug and separator == "_" and len(tail) == 8 and all(
        char in "0123456789abcdef" for char in tail
    )


def load_or_create_handle(path: Path, slug: str) -> str:
    """Return the persisted ``<slug>_<uuid8>`` at ``path``, creating it when absent or invalid."""
    path = Path(path)
    if path.is_symlink():
        raise BoardError("IDENTITY_ERROR", "board identity path must not be a link")
    try:
        value = path.read_text(encoding="utf-8").strip()
        if _valid_handle(value, slug):
            return value
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    value = f"{slug}_{uuid.uuid4().hex[:8]}"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(value + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise BoardError("IDENTITY_ERROR", "cannot persist the board user identity") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return value


@dataclass
class BoardRuntime:
    client: BoardClient
    session: BoardSession
    url: str = DEFAULT_URL
    central_url: str | None = None
    temp: TempBoard | None = None


def _health(client, remaining: float) -> dict:
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


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


def register_runtime(client, state_dir: Path) -> BoardRuntime:
    """Register the persistent main-agent handle on ``client``'s board."""
    agent_handle = load_or_create_handle(state_dir / "main_handle", "main")
    host = socket.gethostname()
    client.register(agent_handle, "agent", host=host)
    return BoardRuntime(client, BoardSession(client, agent_handle))


def local_url(bind: str, port: int) -> str:
    """The loopback URL that reaches a board listening on ``bind``."""
    host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(bind, bind)
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def _service_address(url: str) -> tuple[str, int]:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "http" and bool(parsed.hostname)
            and not any((parsed.username, parsed.password, parsed.query, parsed.fragment))
            and parsed.path in ("", "/")
        )
        if not valid:
            raise ValueError
        return parsed.hostname or "", parsed.port or 80
    except (TypeError, ValueError) as error:
        raise BoardError("NOT_A_BOARD", "board URL must be an HTTP service root") from error


def probe(client, timeout_s: float) -> bool:
    """True when a compatible board answers; False when unreachable; raises otherwise."""
    try:
        _health(client, timeout_s)
        return True
    except (TypeError, ValueError) as error:
        raise BoardError("NOT_A_BOARD", "the address returned malformed health data") from error
    except BoardError as error:
        if error.code in ("UNREACHABLE", "TIMEOUT"):
            return False
        if error.code in ("UNAUTHORIZED", "FORBIDDEN", "NOT_A_BOARD"):
            raise
        raise BoardError("NOT_A_BOARD", "the address is not a compatible board") from error


def _reachable_with_retry(client, probe_s: float, retry_s: float, sleep, cancel) -> bool:
    if probe(client, probe_s):
        return True
    sleep(retry_s)
    if _cancelled(cancel):
        raise BoardError("CANCELLED", "message board startup cancelled")
    return probe(client, probe_s)


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
                if _cancelled(cancel):
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
                    if _cancelled(cancel):
                        raise BoardError("CANCELLED", "message board startup cancelled")
                    if process.poll() is not None:
                        raise BoardError("SPAWN_FAILED", "temporary message board exited during startup")
                    try:
                        _health(client, max(0.1, deadline - time.monotonic()))
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


def start_board(url: str, token: str | None, *, state_dir: Path, bind: str = DEFAULT_BIND,
                client_factory=BoardClient, temp_factory=TempBoard.start, spawn=None,
                wait_s: float = 10.0,
                probe_s: float = 3.0, retry_s: float = 2.0,
                sleep=time.sleep, clock=time.monotonic, cancel=None) -> BoardRuntime:
    """Connect to the configured board or create a private, GUI-owned temporary board.

    Only an unreachable board (refused, timed out, DNS failure) triggers the fallback. An auth
    failure or a non-board reply raises, because something is answering at ``url``.
    """
    state_dir = Path(state_dir)
    _service_address(url)
    client = client_factory(url, token, timeout=probe_s)
    runtime = None
    temp = None
    try:
        if not _reachable_with_retry(client, probe_s, retry_s, sleep, cancel):
            client.close()
            options = {"root": state_dir / "temp", "wait_s": wait_s, "cancel": cancel}
            if spawn is not None:
                options["spawn"] = spawn
            temp = temp_factory(**options)
            client = client_factory(temp.url, None, timeout=probe_s)
        if _cancelled(cancel):
            raise BoardError("CANCELLED", "message board startup cancelled")
        runtime = register_runtime(client, state_dir)
        runtime.url = temp.url if temp is not None else url
        runtime.central_url = url if temp is not None else None
        runtime.temp = temp
        return runtime
    except (OSError, ValueError) as error:
        raise BoardError("SPAWN_FAILED", "cannot start the message board service") from error
    finally:
        if runtime is None:
            client.close()
            if temp is not None:
                temp.close()


def _decode_event(event: str | None, data: list[str]) -> dict | None:
    if event != "post" or not data:
        return None
    try:
        value = json.loads("\n".join(data))
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def parse_sse(lines):
    event = None
    data = []
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            value = _decode_event(event, data)
            if value is not None:
                yield value
            event, data = None, []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].lstrip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    value = _decode_event(event, data)
    if value is not None:
        yield value


class StreamListener(threading.Thread):
    def __init__(self, client, after: int, on_post, on_status, *, backoff=_BACKOFF) -> None:
        super().__init__(daemon=True)
        self.client = client
        self.after = after
        self.on_post = on_post
        self.on_status = on_status
        self.backoff = tuple(backoff) or (30.0,)
        self._stop_event = threading.Event()
        self._active = None
        self._active_lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()
        with self._active_lock:
            active = self._active
        if active is not None:
            active.close()

    def _activate(self, active) -> bool:
        with self._active_lock:
            if self._stop_event.is_set():
                return False
            self._active = active
            return True

    def _clear_active(self) -> None:
        with self._active_lock:
            self._active = None

    def _listen_once(self) -> bool:
        delivered = False
        with self.client.stream(self.after) as lines:
            if not self._activate(lines):
                lines.close()
                return delivered
            if self._stop_event.is_set():
                lines.close()
                return delivered
            self.on_status("connected")
            for post in parse_sse(lines):
                if self._stop_event.is_set():
                    return delivered
                post_id = post.get("id")
                if type(post_id) is int and post_id > self.after:
                    self.after = post_id
                    self.on_post(post)
                    delivered = True
            if not self._stop_event.is_set():
                self.on_status("reconnecting: stream ended")
        return delivered

    def run(self) -> None:
        failures = 0
        while not self._stop_event.is_set():
            try:
                if self._listen_once():
                    failures = 0
            except Exception as error:
                if self._stop_event.is_set():
                    return
                reason = str(error) or type(error).__name__
                self.on_status(f"reconnecting: {reason}")
            finally:
                self._clear_active()
            if self._stop_event.is_set():
                return
            delay = self.backoff[min(failures, len(self.backoff) - 1)]
            failures += 1
            self._stop_event.wait(delay)
