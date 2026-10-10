---
title: 'Message board token: .env with a public default of dagi'
description: 'Decision: every central board has a bearer token from --token, env, .env DAGI_BOARD_TOKEN, else dagi; the generated token file is gone.'
tags: [DAGI_BOARD_TOKEN, resolve_token, resolve_serve_token, dotenv, '.env', DEFAULT_TOKEN, message_board, bearer-token]
updated: 2026-10-10
---

## Decision (Admiral, 2026-10-10)

`services/message_board/settings.py:resolve_token` returns the first non-blank of:
`--token`, process env `DAGI_BOARD_TOKEN`, `DAGI_BOARD_TOKEN` in `<DAGI_ROOT>/.env` (read with
`dotenv_values`, so `os.environ` is untouched), then `DEFAULT_TOKEN = "dagi"`.

- **Every central board has a token, on every bind** (loopback included); the browser asks once per tab.
- **The default is public.** `resolve_serve_token` warns on stderr when `dagi` is used on a
  non-loopback bind; it never prints a custom token.
- **One resolver for all clients.** The GUI, agents and `python message_board.py stop` share
  `resolve_token()`, so a same-machine setup matches automatically.
- **The token file is gone.** The generated `.dagi/board/token` (`TOKEN_PATH`, `read_token`,
  `ensure_token`) was removed and an existing file is ignored.
- **`serve --no-token` is the only tokenless mode.** It is loopback only and mutually exclusive
  with `--token`; it exists for the GUI's private temp board (see [[gui-temp-board-lifecycle]]).

## Alternatives rejected

- **Tokenless loopback boards** (the previous rule): rejected for one simple rule, so every
  central board behaves the same.
- **Refusing `dagi` on network binds:** rejected; a home LAN is trusted, so a warning is enough.
- **Silently allowing `dagi`:** rejected; the repo is public, so the default is known.
- **Keeping the generated token file:** rejected; secrets live in `.env` like the API keys.
