"""Run or stop the standalone board: python -m services.message_board."""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import uuid
from pathlib import Path

import uvicorn

from agent import DAGI_ROOT

from .app import create_app
from .lifecycle import DEFAULT_URL, ShutdownControl, check_bind, stop_local
from .lifecycle import is_loopback_host as is_loopback_host
from .runtime_records import remove_record, write_record
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


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Standalone message board HTTP service")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="run the board in the foreground (default)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--db", type=Path, default=DEFAULT_ROOT / "board.sqlite3")
    serve.add_argument("--token", default=os.environ.get("DAGI_BOARD_TOKEN"))
    serve.add_argument("--runtime-dir", type=Path, default=DEFAULT_ROOT / "run")
    stop = commands.add_parser("stop", help="stop a local board using its protected capability")
    stop.add_argument("--url", default=DEFAULT_URL)
    stop.add_argument("--runtime-dir", type=Path, default=DEFAULT_ROOT / "run")
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("--") and arguments[0] not in ("--help", "-h"):
        arguments.insert(0, "serve")
    return parser.parse_args(arguments)


def serve_board(args) -> None:
    check_bind(args.host, args.token)
    store = BoardStore(args.db)
    control = ShutdownControl(uuid.uuid4().hex, secrets.token_hex(32), lambda: None)
    config = uvicorn.Config(create_app(store, args.token, shutdown=control),
                            host=args.host, port=args.port, proxy_headers=False,
                            timeout_graceful_shutdown=1, log_level="warning")
    server = RecordServer(config, runtime_dir=args.runtime_dir, control=control)
    control.callback = lambda: setattr(server, "should_exit", True)
    try:
        server.run()
    finally:
        store.close()


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "stop":
        return stop_local(args.url, runtime_dir=args.runtime_dir)
    serve_board(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
