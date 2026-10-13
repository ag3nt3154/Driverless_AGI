# Board Admin Controls Implementation Plan

**Goal:** Make the web UI opened by `python message_board.py` the launcher's control point: shut
down the server, clear all history, and ban/unban members (optionally purging their history).

**Architecture:** The server mints a random admin key at startup, keeps it on the existing
`ShutdownControl` and in the protected runtime record, and the launcher opens the browser at
`/#admin=<key>`. Admin routes (`/admin/...`) require the bearer token, `X-Dagi-Admin-Key` and a
direct loopback peer. Bans and purges are stored in SQLite; every purge is a persisted, idempotent
`purges` row that `/stream` replays on connect and pushes live as `event: purge`, so the web UI
and the PySide feed drop removed posts.

**Tech Stack:** FastAPI + uvicorn, sqlite3, vanilla JS (inline in `static/index.html`, tested by
`viewer_harness.js` under node), PySide6 feed.

## Global Constraints

- Resolves `wiki/todo-board-moderation-launcher-only.md`: moderation only for the launching user;
  other users and agents cannot moderate.
- Admin request = valid bearer (existing middleware) AND `X-Dagi-Admin-Key` matching the running
  instance's key (constant-time compare) AND direct loopback peer (`is_loopback_host(peer,
  allow_localhost=False)`, like `_shutdown_check`).
- A board created without `shutdown` (tests, embedded) has no admin: admin routes return
  503 `ADMIN_UNAVAILABLE`.
- Ban = handle + that member's key hash. A banned handle or key cannot register, post or upload:
  403 `BANNED`. Admin can unban. No IP bans.
- Clear/purge deletes posts, `post_mentions`, attachment rows and blob files no longer referenced
  by any remaining attachment row. Post ids keep increasing (AUTOINCREMENT; never reset).
- Purge payloads: `{"id": n, "scope": "all", "through": N}` or
  `{"id": n, "scope": "author", "author": h, "through": N}` — remove posts with `id <= through`
  (and `author == h` for author scope). Idempotent, so replay on every stream connect is safe.
- Posts stay untrusted in the UI: render only via `textContent`/`createElement` (existing rule).
- The URL fragment never reaches the server; the page must strip it with
  `history.replaceState` and keep the key only in `sessionStorage` (memory fallback).
- Python: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt`.
  Qt tests run unsandboxed.

---

### Subtask 1: Store — bans, purges, enforcement ✅ Complete

**Goal:** `BoardStore` persists bans and purges and refuses banned members.
**Requirements:**
- Schema additions (`CREATE TABLE IF NOT EXISTS`, so existing boards migrate on open):
  - `bans (handle TEXT PRIMARY KEY, key_hash TEXT, created_at TEXT NOT NULL)`
  - `purges (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, author TEXT,
    through INTEGER NOT NULL, created_at TEXT NOT NULL)`
- `ban(handle, *, purge=False) -> dict`: 404 `UNKNOWN_AUTHOR` if not a member; insert/replace
  ban with the member's `key_hash`; if `purge`, also run the author purge in the same transaction.
  Returns `{"handle", "created_at", "purge": purge_record_or_None}`.
- `unban(handle) -> None`: 404 `UNKNOWN_BAN` if not banned.
- `list_bans() -> list[dict]` (`handle`, `created_at`; never the key hash).
- `clear_all() -> dict`: delete every post, mention and attachment; record a
  `scope="all"` purge with `through = MAX(id)` seen before deletion (sqlite_sequence value if
  posts are already empty, so `through` is never lower than an id clients may hold).
  Returns the purge record.
- `purge_author(handle) -> dict`: delete that author's posts, their mentions, attachments on
  those posts and that member's pending (unattached) uploads; record a `scope="author"` purge.
- Blob cleanup: after commit, unlink `blobs/<sha256>` for each deleted digest that no remaining
  attachment row references (`missing_ok=True`). Log, don't raise, on `OSError`.
- `list_purges(after=0) -> list[dict]` ascending by id.
- Enforcement: `register_member` raises 403 `BANNED` when the handle is banned or the
  supplied key's hash matches any ban's `key_hash`; `authenticate` raises 403 `BANNED` when the
  handle is banned (checked before the key compare so the message is accurate).
- `_member_record` gains `"banned": bool`.
**Acceptance Criteria:**
- A banned member's re-register, post, and upload all fail with `BANNED`; a new handle reusing
  the banned key fails with `BANNED`; after `unban` all succeed again.
- `clear_all` leaves zero posts/attachments, keeps members and bans, removes unreferenced blob
  files and keeps a blob still used by another attachment; the next post id is greater than
  every pre-clear id.
- `purge_author` removes only that author's posts and uploads.
- An existing database without the new tables opens and gains them.

**Files:**
- Modify: `services/message_board/store.py` (schema, `_member_record`, `register_member`,
  `authenticate`, new methods)
- Test: `tests/message_board/test_store.py`

#### Tests
- `test_ban_blocks_register_post_upload_and_key_reuse` — all four refusals, then unban restores.
- `test_ban_unknown_member_and_unban_unknown_are_404`.
- `test_clear_all_deletes_history_keeps_members_and_ids_increase`.
- `test_clear_all_removes_only_unreferenced_blobs`.
- `test_purge_author_removes_only_their_posts_and_uploads`.
- `test_purges_are_recorded_in_order` — `list_purges(after=...)` payload shape.
- `test_members_report_banned_flag`.

- [ ] Step 1: Write the failing tests above.
- [ ] Step 2: Run `...python.exe -u -m pytest -q -p no:pytest-qt tests/message_board/test_store.py` — expect failures (missing methods).
- [ ] Step 3: Implement schema, methods and enforcement.
- [ ] Step 4: Re-run the file and `tests/message_board` — all pass.
- [ ] Step 5: Return changed files, test output and deviations for review.

### Subtask 2: App — admin routes and purge events ✅ Complete

**Goal:** Expose admin actions over HTTP and stream purges.
**Requirements:**
- `ShutdownControl` (in `lifecycle.py`) gains `admin_key: str = ""`.
- `_admin_check(request, shutdown)`: 503 `ADMIN_UNAVAILABLE` if `shutdown is None` or no
  `admin_key`; 403 `FORBIDDEN` for a non-loopback peer or wrong/missing `X-Dagi-Admin-Key`.
- Routes (all behind `_admin_check`; bearer is enforced by the existing middleware):
  - `GET /admin` → `{"admin": true}` (lets the UI verify its key)
  - `POST /admin/shutdown` → 202 `{"status": "stopping"}`, schedules `shutdown.callback`
  - `POST /admin/clear` → purge record; then `hub.notify()`
  - `GET /admin/bans` → `list_bans()`
  - `POST /admin/bans` body `{"handle": str, "purge": bool=false}` (`extra="forbid"`) → 201; notify
  - `DELETE /admin/bans/{handle}` → 204
- `post_events`: keep a purge cursor starting at 0; each loop iteration first emits
  `event: purge\ndata: <json>\n\n` for `list_purges(after=cursor)` (no `id:` line), then posts.
  Purges are emitted before the post backlog so clients never re-show purged posts.
- Existing `/shutdown` (CLI capability path) unchanged.
**Acceptance Criteria:**
- Admin routes refuse: no bearer (401), wrong key (403), non-loopback peer with the right key
  (403), board without control (503).
- With the right key from `127.0.0.1`: clear, ban(+purge), unban, list and shutdown work; the
  shutdown callback runs.
- A stream opened after a clear starts with the purge event; a stream open during a clear
  receives it live.

**Files:**
- Modify: `services/message_board/lifecycle.py` (`ShutdownControl`)
- Modify: `services/message_board/app.py` (models, `_admin_check`, `_admin_routes`, `post_events`)
- Test: `tests/message_board/test_lifecycle.py` (auth matrix, using
  `TestClient(app, client=("127.0.0.1", 123))` and `("192.0.2.1", 123)` like the shutdown test)
- Test: `tests/message_board/test_api.py` (routes + stream)

#### Tests
- `test_admin_requires_bearer_key_and_loopback_peer`.
- `test_admin_unavailable_without_control`.
- `test_admin_shutdown_runs_callback`.
- `test_admin_clear_and_ban_routes` — ban → member post 403 `BANNED`; unban → 204; bans list.
- `test_stream_replays_purges_before_posts` — drive `post_events` directly (existing pattern in
  `test_api.py`) and assert the first event is `purge`.
- `test_stream_pushes_live_purge`.

- [ ] Step 1: Write the failing tests.
- [ ] Step 2: Run them — expect 404s / missing attribute failures.
- [ ] Step 3: Implement.
- [ ] Step 4: Run `tests/message_board` — all pass.
- [ ] Step 5: Return for review.

### Subtask 3: Launcher — mint the key and open the admin URL ✅ Complete

**Goal:** `python message_board.py` opens the UI already holding the admin key.
**Requirements:**
- `serve_board` creates `ShutdownControl(..., admin_key=secrets.token_urlsafe(32))`.
- `RecordServer.startup` writes `admin_key` into the runtime record.
- `on_start` receives the admin key; `_open_when_ready` opens `<url>/#admin=<key>`.
- Already-running path in `main`: read the protected record for the port
  (`read_record(args.runtime_dir, args.port)`); if its `instance_id` equals the probed id and it
  has an `admin_key`, open `/#admin=<key>`; otherwise open `/` and print
  `"admin controls unavailable: <reason>"` to stderr. Never print the key.
- `--no-browser` and the GUI-spawned temp board are unaffected (no browser → key unused).
**Acceptance Criteria:**
- Fresh start opens a URL with `#admin=` + the same key the app accepts.
- Already running with a matching record → admin URL; stale/missing record → plain URL + message.

**Files:**
- Modify: `services/message_board/__main__.py`
- Test: `tests/message_board/test_entry.py` (inject `opener`, `probe`, `serve`; for the
  already-running path write a record with `write_record` into `tmp_path`)

#### Tests
- `test_fresh_start_opens_admin_fragment`.
- `test_already_running_opens_admin_fragment_from_record`.
- `test_already_running_with_stale_record_opens_plain_url`.
- `test_runtime_record_contains_admin_key` (RecordServer startup, existing service-process
  test style in `test_service_process.py` if simpler).

- [ ] Steps 1–5 as above (failing tests → implement → `tests/message_board` passes → review).

### Subtask 4: Web UI — admin panel and purge handling ✅ Complete

**Goal:** The browser page shows admin controls only when it holds a valid admin key, and drops
purged posts for every viewer.
**Requirements:**
- On load: if `location.hash` matches `^#admin=([A-Za-z0-9_-]{32,128})$`, save it in
  `sessionStorage` (`dagiBoardAdmin`, memory fallback) and `history.replaceState` to drop the hash.
- After the stream connects, if a key is held, `GET /admin`; on success show `#admin` panel,
  on 403 drop the stored key and keep the panel hidden.
- Panel (a card under the header, hidden by default):
  - "Shut down board" — `confirm()` then `POST /admin/shutdown`; status shows "board stopped".
  - "Clear history" — `confirm()` then `POST /admin/clear`.
  - Member list from `state.members` (handle, kind, online, banned) with Ban / Unban buttons and
    a "also delete their posts" checkbox per ban (`POST /admin/bans`, `DELETE /admin/bans/h`),
    then `loadMembers()`.
  - Errors shown in an `#admin-error` element via `textContent`.
- `handleBlock` accepts `event: purge`: remove (`trimPost`) every rendered post with
  `id <= through` (and matching `author` for author scope). `renderPost` stores
  `post.dataset.author`.
- Composer: a `BANNED` error shows "You are banned from this board." (existing
  `composerError` path already shows the server message; no extra code if the message reads well).
**Acceptance Criteria:**
- Harness scenario `admin`: page loaded with `#admin=<key>` strips the hash, stores the key,
  calls `/admin` with `X-Dagi-Admin-Key`, shows the panel, issues clear/ban/shutdown requests
  with the header; a streamed purge removes matching posts.
- Without a key (existing scenarios) the panel stays hidden and no `/admin` request is made.

**Files:**
- Modify: `services/message_board/static/index.html`
- Modify: `tests/message_board/viewer_harness.js` (add `location.hash`, `history.replaceState`,
  `confirm` stubs; `admin` scenario; serve purge events)
- Test: `tests/message_board/test_viewer.py` (`test_admin_panel_and_purge`,
  `test_no_admin_panel_without_key`)

- [ ] Steps 1–5 as above. Run `tests/message_board/test_viewer.py` (needs `node` on PATH).

### Subtask 5: Desktop GUI feed — honour purges ✅ Complete

**Goal:** The PySide board feed drops purged posts.
**Requirements:**
- `board_runtime.py`: add `parse_sse_events(lines)` yielding `(event, dict)` for `post` and
  `purge`; keep `parse_sse` as the post-only wrapper (existing callers/tests unchanged).
- `StreamListener(..., on_purge=None)`: purge events call `on_purge(payload)`; post handling as
  today.
- `bridge.py`: `board_purge = Signal(object)`; `BoardController` passes
  `lambda p: current() and bridge.board_purge.emit(p)` and connects it to
  `board_view.remove_purged`.
- `MessageBoardView.remove_purged(purge)`: remove cards with `id <= through` (and author match);
  track `post_id -> author` when adding cards; drop from `_seen`/`_cards`.
**Acceptance Criteria:**
- `parse_sse_events` yields both event types; `parse_sse` still yields only posts.
- A listener receiving a purge calls `on_purge` and does not advance `after`.
- `remove_purged` removes exactly the matching cards.

**Files:**
- Modify: `pyside_gui/board_runtime.py`, `pyside_gui/bridge.py`, `pyside_gui/board_controller.py`,
  `pyside_gui/sidebars/message_board.py`
- Test: `tests/test_board_stream.py`, `pyside_gui/tests/test_message_board.py`

- [ ] Steps 1–5 as above (Qt tests unsandboxed).

### Subtask 6: Docs ✅ Complete

**Goal:** Record the design and close the todo.
**Requirements:**
- Mark `wiki/todo-board-moderation-launcher-only.md` done (or replace with a decision entry via
  `wiki-add`): admin key + loopback model, ban semantics, purge replay.
- Wiki gotcha: purge events carry no SSE `id:` and are replayed on every connect; clients must
  treat them as idempotent.
- `AGENTS.md`: fix the test interpreter path (`anaconda3`, not `miniconda3`).
**Acceptance Criteria:** wiki entries exist; AGENTS.md path is correct.

### Subtask 7: Server — reserved `@board-admin` identity

*Added 2026-10-13 after demo feedback (plan amendment).*

**Goal:** The admin tab posts as the reserved member `board-admin`, and anyone can `@board-admin`.
**Requirements:**
- `store.py`: `ADMIN_HANDLE = "board-admin"`. `BoardStore.__init__` ensures a member row
  (`handle="board-admin"`, `kind="user"`, `display_name="board-admin"`, `host=""`,
  `key_hash=NULL`) with `INSERT OR IGNORE`.
  - It stays unregistrable: `HANDLE_RE` already rejects it on `POST /members`, so the keyless
    claim path can never take it. `authenticate("board-admin", any)` stays `FORBIDDEN`
    (NULL key hash), so normal `/posts` and `/attachments` can't use it.
  - `ban(ADMIN_HANDLE)` and `purge_author(ADMIN_HANDLE)` raise 422 `RESERVED`.
- `_MENTION_RE` also matches `@board-admin` (same `(?![\w-])` boundary), so
  `extract_mentions` and `GET /posts?mention=board-admin` work.
- `app.py`:
  - `POST /admin/posts` (admin check), body `AdminPostInput`
    `{text: str, reply_to: StrictInt|None (1..MAX_ID), meme: str|None}`, `extra="forbid"`,
    so attachments are rejected with 422.
  - It calls `store.create_post(author=ADMIN_HANDLE, ...)` → 201, then `hub.notify()`.
  - `GET /admin` also refreshes `board-admin`'s `last_seen` (new `store.touch(handle)`), so the
    admin tab's 30 s heartbeat keeps `@board-admin` online for autocomplete.
**Acceptance Criteria:**
- `board-admin` is listed in `/members` on a fresh and an existing DB, and is never `banned`.
- `POST /members` with `board-admin`: 422. `/posts` as `board-admin` with any key: 403.
- `POST /admin/posts` with the key: 201, `author == "board-admin"`, mentions extracted.
  Without the key: 403. With `attachments`: 422.
- `"hi @board-admin"` yields mention `board-admin`; `"@board-admins"` and `"@board-admin-x"` don't.
- Banning or purging `board-admin`: 422 `RESERVED`. `GET /admin` marks `board-admin` online.

**Files:** `services/message_board/store.py`, `services/message_board/app.py`,
`tests/message_board/test_store.py`, `tests/message_board/test_api.py`

- [ ] Steps 1–5: failing tests → implement → `tests/message_board` passes → review.

### Subtask 8: Web UI — collapsed panel, admin tab posts as `@board-admin`

**Goal:** The admin tab is a separate identity from the user's tabs, and the panel starts collapsed.
**Requirements:**
- Panel collapsed by default. `.admin-bar` gets a toggle button (`aria-expanded`,
  "Admin ▸"/"Admin ▾") that shows or hides the members list and the Clear/Shut down buttons.
  The open state is kept per tab in `sessionStorage` (`dagiBoardAdminOpen`, try/catch).
- Admin mode (`state.adminOk`):
  - The identity area shows "posting as @board-admin" with no Set name/change button; the
    identity form stays hidden.
  - `sendPost` posts `{text, reply_to}` via `adminApi("/admin/posts")`, with no member
    registration and no uploads.
  - Attach, paste and drop of files are disabled in admin mode.
  - `heartbeat` calls `adminApi("/admin")` instead of `registerUser`, so the admin tab never
    keeps the user's saved identity online.
  - The admin member list omits `board-admin`.
- While a stored admin key is unverified, Send is disabled ("checking admin…").
  - If `/admin` returns 403, the key is dropped and the tab falls back to normal user mode.
- The saved user identity (localStorage) is never read for posting or written in admin mode.
  - Other tabs at the plain URL (no key in their sessionStorage) keep working as that user.
- `@board-admin` appears in mention autocomplete when online (existing filter on `state.members`).
**Acceptance Criteria (harness):**
- Admin scenario: the panel starts collapsed (members list hidden) and the toggle expands it.
- A post from the admin tab hits `/admin/posts` with the key header and no `/members` POST.
- Attach is disabled, the identity text reads "posting as @board-admin", and no `dagiBoardUser`
  is written.
- Existing non-admin scenarios are unchanged (they still register and post via `/posts`).

**Files:** `services/message_board/static/index.html`, `tests/message_board/viewer_harness.js`,
`tests/message_board/test_viewer.py`

- [ ] Steps 1–5 as above.

### Subtask 9: Docs

- Update `wiki/board-admin-controls-launcher-key.md` with the reserved `board-admin` identity,
  the separate admin tab vs user tabs, and the "Duplicate tab copies sessionStorage" caveat.

## Workspace
- **Branch:** `task/board-admin-controls`
- **Parent:** `main`
- **Starting commit:** `9be403b`
- **Task folder:** `wiki/tasks/2026-10-13_board-admin-controls/`

## Overall Status
In Progress — Subtasks 1-6 complete; 7-9 added after demo feedback

## Notes
- `TestClient` peer is `testclient` unless `client=("127.0.0.1", port)` is passed — admin tests
  must pass it explicitly.
- Blobs are content-addressed and shared between attachments with identical bytes; only delete a
  blob when no remaining row references its digest.
- `webbrowser.open` passes the URL (with the fragment) on the local command line; acceptable for a
  loopback-only, per-instance key. The page strips it from history immediately.
- Agents read history through `/posts`, so server-side deletion is sufficient for them; their
  stream parsers ignore unknown event types.
- The admin's own web identity is an ordinary member; banning it is allowed (admin routes don't
  depend on membership).

## Open Issues
None.

## Attempts and Resolutions
- **Subtask 1, attempt 1:** review PASS with a gap: `authenticate` ignored key bans for other handles sharing a banned key -> added key-ban check + test; added NULL-key-hash ban test. Deviations accepted: `create_post`/`add_attachment` also refuse banned authors; blob unlink after commit under the store lock (`_transaction` split into `_transaction` + `_begin`); purge record omits `author` for scope `all`.
- **Subtask 2, attempt 1:** review PASS; applied `StrictBool` for `BanInput.purge` and 404 status asserts. Known: purge table replays in full on every stream connect (fine at expected volumes). Subtask 3 must keep the tokenless GUI temp board from exposing an admin key.
- **Subtask 3, attempt 1:** review PASS, no changes. stdout deliberately prints the plain URL (key must never be printed). GUI temp boards also carry an admin key in their protected record; harmless (never opened).
- **Subtask 4, attempt 1:** review PASS; strengthened malformed-purge harness cases (non-integer `through`, string `through` with author, non-string author). Accepted deviations: page line cap 820->980; confirm only for clear, shutdown and ban-with-purge; returned purge applied locally at once; page stops reconnecting after a successful admin shutdown. Cosmetic: member rows re-render every heartbeat (focus lost); admin panel not dimmed while offline.
- **Subtask 5, attempt 1:** review PASS, no changes. Purges are not counted as `delivered` (replay on every connect would otherwise reset backoff). Follow-up: inline meme copies in agent chats are not removed by purges.
- **Environment:** RAM ~85-87% trips `tests/conftest.py` RAM watchdog; suite verified with `--noconftest` (163 passed, 2 skipped). Re-run normally when RAM is lower.

## Verification
- `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt tests/message_board tests/test_board_stream.py tests/test_board_client.py`
- `... -m pytest -q -p no:pytest-qt pyside_gui/tests/test_message_board.py pyside_gui/tests/test_board_controller.py` (unsandboxed)
- Manual: `python message_board.py --port 8799 --db <scratch>/b.sqlite3 --runtime-dir <scratch>/run`
  → browser shows admin panel; post from a second (non-admin) browser profile shows no panel;
  ban it → its posts fail with BANNED; clear history → both pages empty; shut down → process exits.

## Verification Results (2026-10-13)
- `tests/message_board` + board client/runtime/stream/tools/downloads suites (`--noconftest`, RAM high): 303 passed, 2 skipped.
- `pyside_gui/tests` (unsandboxed, conftest on): 375 passed.
- Live smoke (scratch port 8799): admin 403 without/with wrong key; ban+purge -> member `BANNED`, posts gone; unban 204; clear -> 0 posts; stream starts with `event: purge`; `/admin/shutdown` -> process exit 0.
- Browser pane: `#admin=` stripped from URL, panel shown, ban+purge via UI removed the post, Shut down -> "board stopped".

## Next Action
Get the amendment (Subtasks 7-9) approved, commit it, then deliver Subtask 7.
