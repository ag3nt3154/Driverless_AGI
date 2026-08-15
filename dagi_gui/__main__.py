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

    from dagi_gui.server import GuiServer
    server = GuiServer()
    raise SystemExit(server.serve(sys.stdin, sys.stdout))


if __name__ == "__main__":
    main()
