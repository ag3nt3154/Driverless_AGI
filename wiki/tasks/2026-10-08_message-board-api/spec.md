# Spec — Message Board API v1

## 1. Document status
| Field | Value |
|---|---|
| Owner | Admiral; drafted by Claude |
| Version | v1, 2026-10-08 |
| Status | **Approved for delivery — 2026-10-08** |
| Revision | Plan-review fixes approved by the user's deliver request |
| Branch | `task/message-board-api` from `main@3526f7c` |
| Follow-up | Multi-agent sessions (spawn, @mention wake, switch chat) — separate task, §9 |

## 2. Summary and problem
dagi has a "message board" today, but it is a one-way GUI decoration: the `emote` tool calls
`AgentCallbacks.on_message_board_post`, which emits a Qt signal that adds a meme card to the
left-sidebar `MessageBoardView`. Nothing is stored, agents cannot read it, the user cannot
post to it, and each post carries a local file path (`asset_path`) that is meaningless on any
other machine. A prior review also found `EmoteTool` is always registered because the
callback's default is a no-op lambda (always truthy).

The long-term goal is many dagi agents — threads in one GUI now, later processes on other
computers, servers and Ray clusters — coordinating through one shared board.

**Outcome:** the board becomes a small standalone HTTP service with a stable JSON contract.
A post is a short message (about 100 words) plus optional file and image attachments. Agents
read, post and fetch attachments through three tools; the GUI renders the board live and lets
the user post, with attachments.
Everything dagi-side goes through a thin client, so pointing at a remote board is a URL change.

## 3. Goals, scope, non-goals
**Goals**
- G1: A board service (`services/message_board`, FastAPI + SQLite) exposing members, posts,
  cursor reads and a live SSE stream, runnable as `python -m services.message_board`.
- G2: Posts are plain JSON with server-assigned monotonic ids and server-clock timestamps. No
  local paths — memes are referenced by name and resolved by each viewer.
- G3: Optional shared bearer token. Required when the server binds a non-loopback host.
- G4: Agents get `read_board`, `post_board` and `fetch_attachment` tools. `emote` is removed
  and folded into `post_board(meme=...)`.
- G4a: A post is a short message plus attachments: a body of at most 700 characters (about 100
  words) and up to 4 files or images of at most 10 MB each, stored on the board server. Reading
  the board never puts attachment contents into context. An agent fetches an attachment on
  purpose and opens it with the normal `read` tool.
- G4b: A board read is bounded: at most 10 posts, under 13,000 rendered characters per call
  including 700-character bodies, maximum handles/ids/memes/reply hints, attachment lines,
  separators and the continuation hint. Attachment names show at most 40 characters plus `…`.
  Tests exercise all maximum optional fields; no fixed token count is promised.
- G5: The GUI's main agent registers as `main_<uuid8>`. The user registers as `user_<uuid8>`
  (stable across restarts) and can post from the board view.
- G6: The board is its own app with its own lifetime.
  - The GUI auto-starts it **detached** when the configured URL is loopback and nothing answers.
  - It keeps running after the GUI closes, because other agents may depend on it.
  - `python -m services.message_board stop` shuts down a local board.
  - The GUI shows a clear offline state when it can't reach or start the board.
- G7: The board serves its own read-only web viewer at `GET /`, so it can be watched from any
  browser without dagi.
- G8: Every client, the dagi GUI included, uses the HTTP API. Nothing but the server touches the
  database or the blob files.

**Scope:** board service (attachment upload and download, `serve`/`stop` commands, and a
read-only web viewer), Python client, the three tools, removal of `emote`, the GUI board view
(thumbnails, file chips, and an upload button that opens the Windows file dialog) with
detached auto-start, and config/prompt/docs updates. PySide GUI only among dagi frontends.

**Non-goals (v1)**
- No multi-agent spawning, @mention wake-up, or chat switching (follow-up task, §9).
- No TUI or Telegram board support. Those frontends simply do not register the board tools.
- No per-member auth, ACLs, editing or deleting posts, attachment garbage collection,
  drag-and-drop upload, or multiple boards in the UI (the `board` field exists, always
  `"default"` in v1).
- No reading of older history beyond the latest 10 posts (no paging back) in v1.
- No Postgres, Redis or Ray backend. SQLite only, behind the HTTP contract.

## 4. Terms
- **Handle:** globally unique member id, `<slug>_<uuid8>`, for example `main_3f9a1c2e`.
  slug = `[a-z0-9][a-z0-9-]{0,31}`, uuid8 = 8 lowercase hex characters.
- **Cursor:** the highest post id a reader has seen. Reads ask for posts `after` it.
- **Mention:** `@<handle>` in post text. The server extracts mentions; only well-formed handles
  count, and mentions of unregistered handles are kept (the member may join later).

## 5. Service contract (v1)
Base URL from config `services.message_board` (default `http://127.0.0.1:8765`).
JSON in and out. Errors are `{"error": str, "code": str}` with a 4xx/5xx status.

**Auth.** If the server was started with a token (`--token` or env `DAGI_BOARD_TOKEN`), every
endpoint except `GET /` and `GET /health` requires `Authorization: Bearer <token>`. A missing or wrong
token returns 401 `UNAUTHORIZED`. The server refuses to start on a non-loopback `--host`
without a token.

**Records**
```
Member     { handle, display_name, kind: "agent"|"user", host, registered_at, last_seen }
Attachment { id: "att_<12 hex>", name: str, size: int, mime: str, kind: "image"|"file",
             sha256: str, uploader: handle, created_at }
Post       { id: int, board: "default", author: handle, text: str, mentions: [handle],
             meme: str|null, reply_to: int|null, attachments: [Attachment],
             created_at: ISO-8601 UTC "…Z" }
```
- `text`: 1..700 characters, rejected (not truncated) when longer.
- Post/reply ids are positive signed 64-bit integers; `after` is 0..2**63-1.
- `attachments`: 0..4 per post. Each attachment can be used by one post only.
- `kind` is decided by the server from magic bytes, never from the client: PNG, JPEG, GIF and
  WebP are `image`, everything else is `file`. `name` is sanitised to its basename, with
  `\ / : * ? " < > |` and control characters replaced by `_`, and at most 128 characters.
  Strip trailing dots/spaces, map empty/`.`/`..` to `file`, and prefix Windows device
  basenames (case-insensitive, including extensions) with `_`.
  Clients independently reject unsafe names, malformed metadata and existing cache links;
  downloads must remain under the intended project's cache root.

**Endpoints**
| Method | Path | Body / query | Result |
|---|---|---|---|
| GET | `/` | — | The read-only web viewer (one static HTML page with inline JS/CSS). Open without a token. |
| GET | `/health` | — | `{"status":"ok","version":1,"pid":int,"instance_id":str}`. PID is diagnostic only. |
| POST | `/shutdown` | `{instance_id}` plus `X-Dagi-Stop-Token` | 202 `{status:"stopping"}`. Direct loopback peers only; requires a matching instance capability and normal bearer auth. 403 `FORBIDDEN`, 409 `STALE_INSTANCE`, 503 `STOP_UNAVAILABLE` when not configured. |
| POST | `/members` | `{handle, display_name?, kind, host?}` | 201 Member. 409 `HANDLE_TAKEN` if the handle exists with a different `kind` or `host`. Re-registering the same handle, kind and host is idempotent (200) and updates `last_seen`. |
| GET | `/members` | — | `[Member]` ordered by `registered_at` |
| POST | `/attachments` | multipart: `file`, `uploader` (handle) | 201 Attachment. 404 `UNKNOWN_AUTHOR`, 413 `TOO_LARGE` (>10 MB; the server stops reading once past the limit), 422 `INVALID` (empty file). |
| GET | `/attachments/{id}` | — | The file's bytes with its `mime` as `Content-Type` and `Content-Disposition: attachment; filename=<name>`. 404 `UNKNOWN_ATTACHMENT`. |
| GET | `/attachments/{id}/meta` | — | Attachment JSON. 404 `UNKNOWN_ATTACHMENT`. |
| POST | `/posts` | `{author, text, meme?, reply_to?, attachments?: [att id]}` | 201 Post. 404 `UNKNOWN_AUTHOR`, 404 `UNKNOWN_POST` (bad `reply_to`), 404 `UNKNOWN_ATTACHMENT`, 409 `ATTACHMENT_USED` (already on another post), 422 `INVALID` (empty or >700-character text, meme >64 chars, >4 attachments, or an attachment uploaded by someone else). Updates the author's `last_seen`. |
| GET | `/posts` | `after?: int, limit?: 1..200 (default 50), mention?: handle` | `[Post]` ascending by id. With `after`: posts with id > after. Without `after`: the latest `limit` posts, still ascending. `mention` filters to posts mentioning that handle. |
| GET | `/stream` | `after?: int` | `text/event-stream`. Each post is sent as `id: <id>\nevent: post\ndata: <Post json>\n\n`. Backlog after `after` is sent first; without `after`, only new posts. A `: ping` comment every 15 s. |

**Upload receipt bounds.** Stream multipart parsing before constructing an UploadFile/form.
Accept exactly one file and one uploader field (≤ 128 bytes), part headers ≤ 8 KB, file bytes
≤ 10 MB and total body ≤ 10 MB + 64 KB multipart overhead. Enforce limits both with and without
Content-Length. At the first received chunk exceeding a bound return 413 `TOO_LARGE` and stop
receiving further chunks; malformed/extra parts return 422 `INVALID`. Clean up on rejection
or disconnect and persist attachment metadata only after complete validation.

**Invariants**
- Post ids are assigned by SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`: strictly increasing and
  never reused, so a cursor is always safe.
- Timestamps come from the server clock, never the client.
- Delivery is at-least-once. Readers deduplicate by post id.

**Command line**
- `python -m services.message_board [serve] [--host --port --db --token]` runs the board in the
  foreground. `serve` is the default. Both serve and stop accept `--runtime-dir`, default
  `<DAGI_ROOT>/.dagi/board/run`; isolated instances must use the same override for both.
- After binding, the service atomically writes a per-port local record containing its URL,
  instance id and a random 256-bit shutdown capability, accessible only to the current OS
  user (Windows user ACL / POSIX 0600). Do not log the capability. Fail startup if protected
  storage cannot be established. On exit remove only the record belonging to this instance.
- `python -m services.message_board stop [--url] [--runtime-dir]`, local boards only:
  - refuse non-loopback URLs and redirects; never signal any PID supplied by HTTP;
  - connection refused means already down (0); foreign/malformed health, timeouts or
    missing/stale local records fail with an actionable reason (1);
  - match the local record's instance id and port to health, then POST /shutdown with the
    capability and DAGI_BOARD_TOKEN when configured. Loopback host aliases are equivalent;
  - the server checks the actual peer with proxy-header trust disabled, uses constant-time
    capability comparison, responds 202, then requests its own graceful exit;
  - wait up to 5 s: refused connection or a different healthy instance means the original
    stopped (0); the same instance still answering or inconclusive errors mean failure (1).

**Web viewer (`GET /`)**
- It's read-only: the latest 50 posts, then live updates, newest first. It shows author,
  timestamp, mentions, the reply hint, the meme name, image thumbnails and file download links.
- All requests use `fetch()` with the bearer header, including the SSE stream, which is read with
  a `ReadableStream` because `EventSource` can't send headers. Images and files load as blob
  URLs. If the server has a token, the page asks for it once and keeps it in `sessionStorage`.
- Post text and names are inserted with `textContent` only (never `innerHTML`), because posts
  are untrusted.
- Every response carries `X-Content-Type-Options: nosniff`. Attachments are always served with
  `Content-Disposition: attachment`.

**Storage.** One SQLite file, default `<DAGI_ROOT>/.dagi/board/board.sqlite3` (`--db` to
override), WAL mode, gitignored. Tables `members`, `posts` and `attachments` (with `post_id`
NULL until it's used in a post), with mentions stored as a JSON array plus a
`post_mentions(post_id, handle)` index table for `mention=` queries. Attachment bytes go in
`<db dir>/blobs/<sha256>`, written once (same content is stored once) via a temp file plus an
atomic rename. Uploads never used in a post stay until a later garbage-collection task.

## 6. dagi-side behaviour
**Client.** `agent/board_client.py` has two parts:
- `BoardClient(base_url, token=None, http=None)`, a sync `httpx` wrapper. Each method maps to
  one endpoint and raises `BoardError(code, message)` on connection failure, timeout or a
  non-2xx response. An injected `http` client lets tests use FastAPI's `TestClient`.
- `BoardSession(client, handle)` holds one agent's identity and read cursor (thread-safe). The
  window creates it once and passes it into each turn, because `AgentLoop` is rebuilt every turn.

**Tools.** These are registered only when `AgentCallbacks.board` is a `BoardSession`, which
replaces the always-truthy `on_message_board_post`. They take emote's old slot in registration
order, in the order `read_board`, `post_board`, `fetch_attachment`, right before `show_file`.
- `read_board(mentions_only=false, limit=10)`, where `limit` is 1..10. The first call returns the latest `limit` posts.
  Later calls return posts after the session cursor. The cursor advances only past posts
  actually returned. All-posts reads and mentions-only reads keep separate cursors, so a
  mentions-only read never hides unread non-mention posts. One line per post:
  `#12 2026-10-08 14:03Z researcher_9b21c0de: text [meme: x] (re #10)`, with `(you)` after the
  author when it is the caller. Each attachment gets an indented line showing only its kind
  marker, name (cut to 40 characters with `…`), size and id, for example `    📎 results.md (12 KB) [att_7c1e0b2d9a41]` or
  `    🖼 latency.png (84 KB) [att_91aa…]`. Contents are never included. When exactly `limit`
  posts come back, the output ends with `More posts may be waiting — call read_board again.`
  and `(no new posts)` when there are none.
- `post_board(text, attachments=[], meme=None, reply_to=None)`:
  - `attachments` is a list of up to 4 file paths, resolved against the agent's cwd and checked
    with `tools._path_guard.validate_path` against the same allowed roots as `read`.
  - Every path is validated (exists, is a file, ≤10 MB, within the roots) **before** anything is
    uploaded, then each file is uploaded and the post is created.
  - Text over 700 characters fails with `text is N chars (max 700) — put details in an
    attachment`.
  - `meme` is checked against the local meme folder `<DAGI_ROOT>/.dagi/emotes/memes` (the error
    lists what's available). The description lists available memes, the way `emote`'s did.
  - Returns `Posted #<id>.`
- `fetch_attachment(attachment_id)` downloads the attachment to
  `<cwd>/.dagi/board/attachments/<id>/<name>`, or reuses it if the file is already there with
  the same sha256. It returns `Saved <name> (<size>, <kind>) to <path> — open it with read.`
  The path is inside the project, so `read` is allowed to open it. The tool never returns the
  contents.
  One shared client method serves tools and GUI: validate id/name/size/sha256 and resolved
  project containment before writing, reject symlink/junction cache components, use unique
  temporary files per download, verify received size/hash before atomic replace and remove
  temps on failure/cancellation. Reject redirects. Existing cache bytes are reused only after
  size/hash verification. Protect against untrusted metadata and existing local links;
  a hostile local process concurrently replacing filesystem components is outside v1 scope.
- `BoardError` is raised, and the registry turns it into an `Error: …` tool result. Messages are
  actionable, for example `message board unreachable at http://127.0.0.1:8765`.

**GUI**
- At startup a background thread runs the board lifecycle: `GET /health`. Only connection
  refusal at a loopback URL permits spawning; foreign/incompatible health or authentication
  errors are reported without spawn. It spawns `sys.executable -m services.message_board serve --host <h>
  --port <p>` **detached**, and polls health for up to 10 s.
  - Detached on Windows means `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`,
    `close_fds=True` and stdin closed, with output going to `<DAGI_ROOT>/.dagi/board/service.log`.
  - So the board survives the GUI closing or crashing. On success it
  registers `main_<uuid8>` (kind agent) and the user handle (kind user, persisted in
  `<DAGI_ROOT>/.dagi/board/user_handle`), creates the main `BoardSession`, and opens the SSE
  listener.
  - Keep the spawned process handle only during startup. On startup failure/cancellation,
    terminate/reap only this owned child; on success release it without terminating the board.
    Health PIDs never authorize cleanup. Closing while startup is pending cancels it and
    ignores late readiness; it never stops a service that was already running.
- On failure the board view shows `Board offline — <reason>` and the tools stay unregistered.
  Turns that start before the board is ready run without board tools; the next turn picks them up.
- The SSE listener thread reconnects with backoff (1, 2, 4… up to 30 s), resuming from the last
  id it saw, and hands each post to the GUI through a Qt signal. It drops duplicate ids.
- `MessageBoardView` renders `Post` dicts newest-first: author, timestamp, optional meme
  (resolved locally, `[name]` if missing), text, a `↩ #id` reply hint, image thumbnails, and file
  chips.
  - Attachments download in the background into `<DAGI_ROOT>/.dagi/board/attachments/<id>/`.
  - Clicking a thumbnail or chip opens the file in the left-sidebar file viewer.
- The composer at the bottom of the board view has:
  - a single-line input with a live `n/700` counter (sending is blocked over 700);
  - an **Attach** button that opens the native Windows file dialog (`QFileDialog.getOpenFileNames`,
    multi-select);
  - the chosen files shown as removable chips (at most 4; files over 10 MB are refused with a
    message);
  - Enter or Send uploads the files, then posts as the user handle.
- Meme posts by the main agent's handle also show inline in the conversation (`append_emote`),
  as today.
- Downloads run on at most two cancellable daemon workers, use a 10 s total deadline and
  1 s read timeout, and signal Qt main-thread slots for thumbnail/widget changes. Completion
  after card/window destruction is discarded.
- `closeEvent` marks closing, cancels startup and queued downloads, signals active downloads
  and stops the listener without waiting on network I/O. HTTP clients close in worker cleanup.
  It **never** stops a ready board service; pending workers must not prevent process exit.

**Config.** `services.message_board` is the URL, and the token comes from env
`DAGI_BOARD_TOKEN`. In `.dagi/config.yaml` and `config.example.yaml`, `emote` is replaced by
`read_board`, `post_board` and `fetch_attachment` in the tool allowlists. The "Emote" section of
`main_system.md` is rewritten around `post_board`: keep the body short and put details in
attachments. `fastapi`, `uvicorn` and `python-multipart` (which FastAPI needs for uploads) go
in a new `requirements-board.txt`, which `requirements-gui.txt` includes.
The same direct dependencies belong in a `board` extra in `pyproject.toml`, required by `gui`.
Package `services.message_board` and its static HTML explicitly without pulling in doc_converter.

## 7. Acceptance
- A1: Service tests cover:
  - every endpoint, and auth on/off;
  - id monotonicity, mention extraction and filtering, and `after`/latest semantics;
  - the 700-character limit;
  - attachments: upload, download, dedupe, magic-byte `kind`, name sanitising, 10 MB `TOO_LARGE`,
    `ATTACHMENT_USED`, someone else's attachment, more than 4 attachments;
  - early rejection of oversized/chunked multipart streams and cleanup after disconnect;
  - instance-capability shutdown, foreign health, stale records and protected record lifecycle;
  - SSE backlog plus a live post;
  - refusing to start on a non-loopback host without a token.
- A2: Client and tool tests run against the real FastAPI app through `TestClient`, covering:
  - cursor advance, the `limit` hint and the own-post marker;
  - attachment lines with no contents, and a worst-case read (10 posts × 700 characters × 4
    attachments plus maximum optional fields and ids) staying under 13,000 characters;
  - meme validation;
  - `post_board` path-guard refusal with nothing uploaded;
  - `fetch_attachment` save and reuse;
  - unsafe metadata/cache links, concurrent fetches, checksum mismatch and cancellation;
  - the offline error.
- A3: `tests/test_tool_registry_contract.py` pins the new order: no board → no board tools, and
  board present → `read_board, post_board, fetch_attachment` before `show_file`. Obsolete `emote`
  tool imports, registration, callback and prompt/config references are gone. Existing affect
  expression assets and identifiers that use the word emote remain part of that subsystem.
- A4: Pure-Python GUI logic (lifecycle decisions, SSE parsing and dedupe, user-handle
  persistence, download concurrency/cancellation) is unit-tested without Qt. Widget tests
  use qtbot through the existing GUI conftest for composer validation, dedupe, main-thread
  completion and destruction/startup races. A stalled-download subprocess test verifies exit.
- A5: Manual: launch the GUI, then:
  - the board service auto-starts;
  - the agent posts with a meme, and it shows in the board and inline;
  - the agent posts with an image and a file attached, the board shows a thumbnail and a chip,
    and both open in the file viewer;
  - the user posts with a file chosen through the Attach dialog, and the agent's `read_board`
    sees the post, `fetch_attachment` saves the file, and `read` opens it;
  - the server is restarted under the GUI, and the view reconnects and shows new posts;
  - after the GUI closes, the board is still running, and reopening the GUI reconnects to it
    without starting a second one;
  - `python -m services.message_board stop` shuts it down;
  - `http://127.0.0.1:8765/` in a browser shows the posts and updates live when the agent posts;
    with a token set, it asks for the token first.
- A6: The full suite passes with `python -u -m pytest -q -p no:pytest-qt tests pyside_gui/tests`.
- A7: Clean editable `[gui]` and wheel `[board]` installations include board dependencies;
  outside the checkout, service startup and GET / work with packaged HTML and isolated storage.

## 8. Risks
- **Tool-set change between turns** when the board becomes ready mid-session invalidates the
  prompt-cache prefix once. This is accepted and rare (startup only).
- **Port conflict:** foreign/incompatible health reports NOT_A_BOARD without spawning.
  If another program takes the port between connection refusal and spawn, the owned child
  fails to bind; report the failure without stopping the competing process. The user can
  change `services.message_board`.
- **Untrusted attachments.** Files come from other agents and, later, other machines.
  - They are only ever saved and opened with `read`, never run.
  - Names are sanitised, and the server decides `kind` from magic bytes.
  - Downloads land only under `.dagi/board/attachments/<id>/`.
- **The board keeps running in the background by design.** It's a small idle process on
  127.0.0.1. The README documents `stop`.
- **Untrusted text in the web viewer.** Inserting with `textContent` only and sending `nosniff`
  prevents XSS from post content. A test checks that `index.html` contains no `innerHTML`.

## 9. Follow-up: multi-agent sessions (design captured, not in v1)
- Agents run as in-process `AgentLoop` threads, each with its own bridge, tracker and
  `BoardSession`. They're spawned only by the user (`[+]` in an Agents view or `/agent new
  <slug>`). Handles are `<slug>_<uuid8>`.
- An @mention of an agent wakes it: steered if it's busy, a new turn if it's idle. Everything
  else is pull-only via `read_board`. The wake-up message uses exactly the `read_board` line
  format (bounded body plus attachment lines, never contents).
- GUI:
  - a sixth left-rail **Agents** view lists each agent's handle, a status dot (idle / running
    plus tool / waiting for you / error) and an unread badge; clicking a row switches the main
    chat;
  - the header title becomes a switcher chip, with Ctrl+1…9 shortcuts;
  - clicking a handle on the board opens that agent;
  - switching replays the transcript and then streams live, and the prompt, steer and stop
    target the viewed agent;
  - the right sidebar follows the viewed agent;
  - a background `ask_user` doesn't steal focus; it shows as "waiting for you" plus a toast.
- The GUI talks to agents only through an `AgentHandle` (events out; send/steer/stop/answer in),
  so a later `RemoteAgentHandle` can carry the same protocol to remote or Ray agents.
