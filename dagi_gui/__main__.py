"""Entry point for the GUI sidecar process.

Forces line-buffered stdout before any protocol writes so the Electron
supervisor receives events immediately — on Windows, piped stdout defaults
to block buffering which would deadlock the supervisor on the first 'ready'.
"""

from __future__ import annotations

import logging
import os
import sys


def main() -> None:
    # Force line-buffered stdout — MUST happen before any EventWriter is created
    sys.stdout = open(  # noqa: WPS515
        sys.stdout.fileno(),
        "w",
        buffering=1,
        encoding="utf-8",
        closefd=False,
    )
    sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from pathlib import Path
    from agent.config_loader import resolve_model_config
    from dagi_gui.protocol import EventWriter
    from dagi_gui.session import SessionController
    from dagi_gui.server import GuiServer

    # Resolve config — look next to the script, then cwd
    script_dir = Path(__file__).resolve().parent.parent
    config_path = script_dir / "config.yaml"
    if not config_path.exists():
        config_path = Path.cwd() / "config.yaml"

    config = resolve_model_config(config_path=config_path if config_path.exists() else None)
    writer = EventWriter(sys.stdout)
    controller = SessionController(config=config, writer=writer)

    server = GuiServer(controller=controller)
    raise SystemExit(server.serve(sys.stdin, sys.stdout, writer=writer))


if __name__ == "__main__":
    main()
