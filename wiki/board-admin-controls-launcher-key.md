---
title: 'Board admin controls: per-instance launcher key, key bans, replayed purges'
description: 'Central board moderation (shutdown, clear history, ban/unban) is gated by a per-instance admin key opened as /#admin=<key>, plus bearer and a direct loopback peer.'
tags: [message_board, admin_key, X-Dagi-Admin-Key, ban, purge, 'event: purge', ShutdownControl, runtime record, moderation]
updated: 2026-10-13
---
Decided 2026-10-13 (task `task/board-admin-controls`, plan in `wiki/tasks/2026-10-13_board-admin-controls/plan.md`).

## Choice
- `serve_board` mints `ShutdownControl.admin_key` (`secrets.token_urlsafe(32)`) per instance and writes it into the protected runtime record. `python message_board.py` opens `/#admin=<key>`; if a board is already running it reads the key from the record whose `instance_id` matches the live `/health`. The key is never printed.
- `/admin*` routes need bearer (middleware) + `X-Dagi-Admin-Key` + a direct loopback peer (`allow_localhost=False`). A board without a control/admin key answers 503 `ADMIN_UNAVAILABLE`.
- The page strips the fragment with `history.replaceState` and keeps the key in `sessionStorage` only.
- Ban = handle + that member's key hash (`bans` table). Banned handle or key → 403 `BANNED` on register, post, upload and `authenticate`. A NULL key hash (pre-key member) bans only the handle.
- Clear/purge rows live in `purges`; `/stream` replays every purge on connect, then pushes new ones live as `event: purge` (no `id:` line). Payloads are idempotent: remove posts with `id <= through` (and `author` match for scope `author`). Post ids are AUTOINCREMENT and never reused. Unreferenced blobs are unlinked after commit while the store lock is held.
- PySide `StreamListener` forwards purges via `bridge.board_purge` and does not count them as delivered (replays would otherwise reset reconnect backoff).

## Rejected
- Loopback-only admin: local agents could moderate.
- Admin password in `.env`: one more secret; LAN admin not needed.
- IP bans: on a LAN, banning a local agent would ban 127.0.0.1 (the admin).
- Server-only deletion without a stream event: connected viewers kept stale posts.

## Follow-ups
- Purges don't remove inline meme copies already shown in agent chat panes.
- Admin member rows re-render on every 30 s heartbeat (keyboard focus lost).
- The `purges` table is replayed in full per connect; compact if it ever grows large.
