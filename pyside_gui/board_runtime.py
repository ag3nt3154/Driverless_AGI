"""Qt-free message board lifecycle, persistent GUI identity and SSE listener."""
from __future__ import annotations

import ipaddress
import json
import os
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
from agent._board_files import MAX_ATTACHMENT
from agent.board_client import BoardClient, BoardError, BoardSession
from services.message_board.lifecycle import DEFAULT_URL
from services.message_board.settings import DEFAULT_BIND, ensure_token

DEFAULT_BOARD_URL = DEFAULT_URL
_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)


def error_text(error: BaseException) -> str:
    """User-facing text for a board failure shown in status lines and cards."""
    if isinstance(error, BoardError):
        return error.message
    return str(error) or type(error).__name__


def check_user_file(path: Path) -> str | None:
    """Return why one composer file cannot be attached, or None when it is acceptable."""
    try:
        size = path.stat().st_size
    except OSError:
        return f"Cannot attach {path.name}: file is unavailable."
    if not path.is_file() or not 1 <= size <= MAX_ATTACHMENT:
        return f"Cannot attach {path.name}: files must be 1 byte through 10 MB."
    return None


def validate_user_files(paths) -> tuple[list[Path], list[str]]:
    """Validate composer files before any upload starts."""
    candidates = [Path(path) for path in paths]
    if len(candidates) > 4:
        return [], ["Attach at most 4 files."]
    accepted, errors = [], []
    for path in candidates:
        error = check_user_file(path)
        if error is None:
            accepted.append(path)
        else:
            errors.append(error)
    return accepted, errors


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


def load_or_create_user_handle(path: Path) -> str:
    return load_or_create_handle(path, "user")


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
    user_handle: str
    spawned_pid: int | None
    url: str = DEFAULT_URL
    central_url: str | None = None  # the configured board, when running on a local fallback


class SpawnedService:
    """Owned child handle during startup; release transfers it to the operating system."""

    def __init__(self, process) -> None:
        self._process = process
        self.pid = process.pid
        self._released = False

    def terminate(self) -> None:
        if not self._released and self._process.poll() is None:
            self._process.terminate()

    def wait(self, timeout: float | None = None):
        return self._process.wait(timeout=timeout)

    def release(self) -> int:
        self._released = True
        return self.pid


def spawn_service(host: str, port: int, log_path: Path, *, db_path: Path | None = None,
                  runtime_dir: Path | None = None) -> SpawnedService:
    command = [sys.executable, "-m", "services.message_board", "serve",
               "--host", host, "--port", str(port)]
    if db_path is not None:
        command.extend(("--db", str(db_path)))
    if runtime_dir is not None:
        command.extend(("--runtime-dir", str(runtime_dir)))
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    options = {"cwd": DAGI_ROOT, "stdin": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = sum(getattr(subprocess, name) for name in (
            "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW",
        ))
    else:
        options["start_new_session"] = True
    with log_path.open("ab") as output:
        process = subprocess.Popen(command, stdout=output, stderr=output, **options)
    return SpawnedService(process)


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


def _cleanup_child(child) -> None:
    child.terminate()
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process = getattr(child, "_process", None)
        if process is not None:
            process.kill()
            process.wait(timeout=5)


def _cancelled(cancel) -> bool:
    return cancel is not None and cancel.is_set()


def register_runtime(client, state_dir: Path, spawned_pid: int | None = None) -> BoardRuntime:
    """Register the persistent main-agent and user handles on ``client``'s board."""
    agent_handle = load_or_create_handle(state_dir / "main_handle", "main")
    user_handle = load_or_create_user_handle(state_dir / "user_handle")
    host = socket.gethostname()
    client.register(agent_handle, "agent", host=host)
    client.register(user_handle, "user", host=host)
    return BoardRuntime(client, BoardSession(client, agent_handle), user_handle, spawned_pid)


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


def _await_ready(client, deadline: float, clock, sleep, cancel) -> None:
    while True:
        if _cancelled(cancel):
            raise BoardError("CANCELLED", "message board startup cancelled")
        remaining = deadline - clock()
        if remaining <= 0:
            raise BoardError("SPAWN_FAILED", "message board did not become ready")
        try:
            _health(client, remaining)
            return
        except BoardError as error:
            if error.code not in ("UNREACHABLE", "TIMEOUT"):
                raise BoardError("SPAWN_FAILED", error.message) from error
        sleep(min(0.25, max(0.0, deadline - clock())))


@dataclass
class _Launch:
    """How to launch a local board when the configured one is unreachable."""
    bind: str
    state_dir: Path
    spawn: object
    wait_s: float


def _spawn_local(launch: _Launch, port: int, token, client_factory, timing):
    """Spawn a board on ``launch.bind``; return (client, child) once it is healthy."""
    clock, sleep, cancel = timing
    token = token or ensure_token()
    client = client_factory(local_url(launch.bind, port), token,
                            timeout=min(10.0, max(0.001, launch.wait_s)))
    child = None
    try:
        child = launch.spawn(
            launch.bind, port, launch.state_dir / "board.log",
            db_path=launch.state_dir / "board.sqlite3", runtime_dir=launch.state_dir / "run",
        )
        _await_ready(client, clock() + launch.wait_s, clock, sleep, cancel)
    except BaseException:
        client.close()
        if child is not None:
            _cleanup_child(child)
        raise
    return client, child


def start_board(url: str, token: str | None, *, state_dir: Path, bind: str = DEFAULT_BIND,
                client_factory=BoardClient, spawn=spawn_service, wait_s: float = 10.0,
                probe_s: float = 3.0, retry_s: float = 2.0,
                sleep=time.sleep, clock=time.monotonic, cancel=None) -> BoardRuntime:
    """Connect to the board at ``url``; after one failed retry, launch a local board instead.

    Only an unreachable board (refused, timed out, DNS failure) triggers the fallback. An auth
    failure or a non-board reply raises, because something is answering at ``url``.
    """
    state_dir = Path(state_dir)
    _, port = _service_address(url)
    client = client_factory(url, token, timeout=probe_s)
    child = runtime = None
    try:
        if not _reachable_with_retry(client, probe_s, retry_s, sleep, cancel):
            client.close()
            launch = _Launch(bind, state_dir, spawn, wait_s)
            client, child = _spawn_local(
                launch, port, token, client_factory, (clock, sleep, cancel),
            )
        if _cancelled(cancel):
            raise BoardError("CANCELLED", "message board startup cancelled")
        runtime = register_runtime(client, state_dir, getattr(child, "pid", None))
        runtime.url = local_url(bind, port) if child is not None else url
        if child is not None and not is_loopback_url(url):
            runtime.central_url = url
        if child is not None:
            child.release()
            child = None
        return runtime
    except (OSError, ValueError) as error:
        raise BoardError("SPAWN_FAILED", "cannot start the message board service") from error
    finally:
        if child is not None:
            _cleanup_child(child)
        if runtime is None:
            client.close()


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
