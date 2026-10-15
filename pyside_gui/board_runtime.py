"""Qt-free message board connection: probing, registration and startup with temp fallback.

Identity files live in ``board_identity``, the temporary board process in ``board_temp``
and the SSE stream listener in ``board_stream``.
"""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent.board_client import BoardClient, BoardError, BoardSession
from pyside_gui.board_identity import load_or_create_handle, load_or_create_key
from pyside_gui.board_temp import TempBoard, check_health, is_cancelled
from services.message_board.lifecycle import DEFAULT_URL
from services.message_board.settings import DEFAULT_BIND

DEFAULT_BOARD_URL = DEFAULT_URL


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


@dataclass
class BoardRuntime:
    client: BoardClient
    session: BoardSession
    url: str = DEFAULT_URL
    central_url: str | None = None
    temp: TempBoard | None = None


def register_runtime(client, state_dir: Path) -> BoardRuntime:
    """Register the persistent main-agent handle on ``client``'s board."""
    agent_handle = load_or_create_handle(state_dir / "main_handle", "main")
    key = load_or_create_key(state_dir / "main_key")
    host = socket.gethostname()
    client.register(agent_handle, "agent", host=host, key=key)
    return BoardRuntime(client, BoardSession(client, agent_handle, key))


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
        check_health(client, timeout_s)
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
    if is_cancelled(cancel):
        raise BoardError("CANCELLED", "message board startup cancelled")
    return probe(client, probe_s)


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
        if is_cancelled(cancel):
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
