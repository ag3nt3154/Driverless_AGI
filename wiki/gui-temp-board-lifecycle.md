---
title: 'GUI temporary board ownership and lifecycle'
description: 'Decision: the GUI owns a private throwaway board and terminates it through stdin EOF; it never launches the central board.'
tags: [board_runtime, temporary-board, message_board, stdin-EOF, central-board, lifecycle]
updated: 2026-10-10
---

## Decision

As of 2026-10-10, the GUI connects to the configured central message board when it is reachable.
Otherwise it starts a private, loopback-only temporary board on an OS-assigned port. The temporary
board is GUI-owned and throwaway: its posts are not copied to the central board, and the GUI stops
and removes it when switching to central or closing.

The GUI never starts or stops the configured central board. That board is an independent app,
launched with `python message_board.py` and managed with `python message_board.py stop`.

## Lifecycle gotcha

The GUI keeps the temporary server's subprocess `stdin` pipe open and launches it with
`--exit-with-stdin`. Closing the pipe produces EOF, which tells the server to shut down. This also
handles abrupt GUI death because the operating system closes the parent-owned pipe. Do not replace
this with a detached process or PID-only ownership: descendants may inherit process relationships,
PIDs can be reused, and a detached server can outlive the GUI.

The parent pipe endpoint is non-inheritable so agent tool subprocesses cannot accidentally keep the
temporary board alive. Startup, stale-run sweeping, and run-folder locking are serialized under the
temporary root; the server binds port `0` and publishes its actual bound port in the protected
runtime record.

**Spawn the temp board with `serve --no-token`.** The GUI calls `load_dotenv()`, so its environment,
and therefore the temp board child's, contains `DAGI_BOARD_TOKEN` whenever `.env` sets it. Without
`--no-token`, `serve` resolves that token (or the `dagi` default; see
[[board-token-from-dotenv-default-dagi]]). The GUI's tokenless client then gets 401 on every
authenticated endpoint. `tests/test_board_runtime.py::test_temp_board_lifecycle_live` guards this.

## Alternatives rejected

- Launching a fallback on the configured central port: it confuses ownership and can block the real
  central board from returning.
- Letting the GUI launch the central board: it couples an independent shared service to one GUI
  process and makes stop/switch behavior ambiguous.
- Detaching the fallback and cleaning it up by PID: it is less reliable than the parent-owned stdin
  EOF capability and can leave orphaned services.
