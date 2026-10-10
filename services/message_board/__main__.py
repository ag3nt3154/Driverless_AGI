"""Run or stop the standalone board: python message_board.py [serve|stop] [options].

Defaults come from ``services.message_board`` in .dagi/config.yaml; flags override them.
"""
from __future__ import annotations

import argparse
import secrets
import socket
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import httpx
import uvicorn

from agent import DAGI_ROOT

from .app import create_app
from .lifecycle import ShutdownControl, check_bind, stop_local, validate_health_identity
from .lifecycle import is_loopback_host as is_loopback_host
from .runtime_records import RecordError, remove_record, write_record
from .settings import DEFAULT_TOKEN, ENV_PATH, BoardSettings, load_settings, resolve_token
from .store import BoardStore

DEFAULT_ROOT = DAGI_ROOT / ".dagi" / "board"


class RecordServer(uvicorn.Server):
    """Publish a protected capability only once uvicorn successfully binds."""

    def __init__(self, config, *, runtime_dir: Path, control: ShutdownControl):
        super().__init__(config)
        self.runtime_dir = runtime_dir
        self.control = control
        self.record_port = None

    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.should_exit:
            return
        address = self.servers[0].sockets[0].getsockname()
        port = address[1]
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(
            self.config.host, self.config.host,
        )
        url_host = f"[{host}]" if ":" in host else host
        record = {"url": f"http://{url_host}:{port}", "port": port,
                  "instance_id": self.control.instance_id, "capability": self.control.capability}
        try:
            write_record(self.runtime_dir, record)
        except Exception:
            for server in self.servers:
                server.close()
                await server.wait_closed()
            await self.lifespan.shutdown()
            raise RuntimeError("cannot establish protected message board runtime storage") from None
        self.record_port = port

    async def serve(self, sockets=None) -> None:
        try:
            await super().serve(sockets=sockets)
        finally:
            if self.record_port is not None:
                remove_record(self.runtime_dir, self.record_port, self.control.instance_id)


def parse_args(argv=None, settings: BoardSettings | None = None):
    settings = settings or load_settings()
    parser = argparse.ArgumentParser(description="Standalone message board HTTP service")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="run the board in the foreground (default)")
    serve.add_argument("--host", default=settings.bind)
    serve.add_argument("--port", type=int, default=settings.port)
    serve.add_argument("--db", type=Path, default=DEFAULT_ROOT / "board.sqlite3")
    token = serve.add_mutually_exclusive_group()
    token.add_argument("--token", default=None,
                       help='bearer token (default: env DAGI_BOARD_TOKEN, then .env, then "dagi")')
    token.add_argument("--no-token", action="store_true",
                       help="serve without a token; loopback only (the GUI's private temp board)")
    serve.add_argument("--runtime-dir", type=Path, default=DEFAULT_ROOT / "run")
    serve.add_argument("--exit-with-stdin", action="store_true",
                       help="stop when stdin reaches EOF (used by a parent that owns this board)")
    serve.add_argument("--no-browser", action="store_true",
                       help="do not open the board in a browser")
    stop = commands.add_parser("stop", help="stop a local board using its protected capability")
    stop.add_argument("--url", default=f"http://127.0.0.1:{settings.port}")
    stop.add_argument("--runtime-dir", type=Path, default=DEFAULT_ROOT / "run")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("--") and arguments[0] not in ("--help", "-h"):
        arguments.insert(0, "serve")
    return parser.parse_args(arguments)


def resolve_serve_token(host: str, explicit: str | None, *, no_token: bool = False,
                        env_path: Path = ENV_PATH) -> str | None:
    """The serve token: ``--token``, env DAGI_BOARD_TOKEN, .env, then ``"dagi"``.

    Every bind gets a token unless ``no_token`` asks for a tokenless loopback board.
    """
    if no_token:
        if not is_loopback_host(host):
            raise SystemExit("--no-token is only allowed on a loopback bind")
        return None
    token = resolve_token(explicit, env_path)
    if token == DEFAULT_TOKEN and not is_loopback_host(host):
        print(f'message board: using the default token "{DEFAULT_TOKEN}" — set '
              f"DAGI_BOARD_TOKEN in {env_path} to secure this board", file=sys.stderr)
    return token


def _probe_v1(url: str) -> str | None:
    """Return the instance id when ``url`` serves a valid v1 health response."""
    try:
        with httpx.Client(trust_env=False, timeout=1.0) as client:
            response = client.get(url.rstrip("/") + "/health", follow_redirects=False)
        if response.status_code != 200:
            return None
        body = response.json()
        validate_health_identity(body)
    except (httpx.HTTPError, ValueError, RecordError):
        return None
    return body["instance_id"]


def _loopback_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _open_when_ready(url: str, instance_id: str, opener, probe,
                     stopped: threading.Event) -> None:
    deadline = time.monotonic() + 10.0
    while not stopped.is_set():
        try:
            ready = probe(url) == instance_id
        except Exception:
            ready = False
        if ready and not stopped.is_set():
            opener(url.rstrip("/") + "/")
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        stopped.wait(min(0.25, remaining))


def serve_board(args, *, on_start=None) -> None:
    args.token = resolve_serve_token(args.host, args.token, no_token=args.no_token)
    check_bind(args.host, args.token)
    if not is_loopback_host(args.host):
        print(f"LAN: http://{socket.gethostname()}:{args.port}/ "
              f"(token: DAGI_BOARD_TOKEN in {ENV_PATH})")
    store = BoardStore(args.db)
    control = ShutdownControl(uuid.uuid4().hex, secrets.token_hex(32), lambda: None)
    config = uvicorn.Config(create_app(store, args.token, shutdown=control),
                            host=args.host, port=args.port, proxy_headers=False,
                            timeout_graceful_shutdown=1, log_level="warning")
    server = RecordServer(config, runtime_dir=args.runtime_dir, control=control)
    control.callback = lambda: setattr(server, "should_exit", True)
    if args.exit_with_stdin:
        def _watch_stdin() -> None:
            try:
                sys.stdin.buffer.read()
            finally:
                server.should_exit = True

        threading.Thread(target=_watch_stdin, daemon=True, name="stdin-watch").start()
    try:
        if on_start is not None:
            on_start(control.instance_id)
        server.run()
    finally:
        store.close()


def main(argv=None, *, open_browser: bool = False, opener=webbrowser.open,
         probe=_probe_v1, serve=None) -> int:
    args = parse_args(argv)
    if args.command == "stop":
        return stop_local(args.url, runtime_dir=args.runtime_dir)
    if serve is None:
        serve = serve_board
    should_open = open_browser and not args.no_browser
    local_url = _loopback_url(args.port)
    if should_open:
        try:
            already_running = probe(local_url)
        except Exception:
            already_running = False
        if already_running:
            browser_url = local_url + "/"
            print(f"message board already running at {browser_url}")
            opener(browser_url)
            return 0

    stopped = threading.Event()

    def on_start(instance_id: str) -> None:
        threading.Thread(target=_open_when_ready,
                         args=(local_url, instance_id, opener, probe, stopped),
                         daemon=True, name="board-browser-ready").start()

    try:
        if should_open:
            serve(args, on_start=on_start)
        else:
            serve(args)
    finally:
        stopped.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
