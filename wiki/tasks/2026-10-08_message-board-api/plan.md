# Message Board API Implementation Plan

**Goal:** Replace the one-way `emote` GUI board with a standalone HTTP message board service
that agents read and post to through tools, and that the GUI renders live and lets the user
post to.

**Architecture:** `services/message_board` is its own app: a FastAPI service over a SQLite store
and a blob directory, with cursor reads, attachments, an SSE stream, `serve`/`stop` commands and
a read-only web viewer. It outlives the GUI, which only ever talks to it over HTTP. `agent/board_client.py` is the only dagi code that speaks HTTP to it.
`tools/board` adds `read_board`/`post_board`, bound to a per-agent `BoardSession` passed in via
`AgentCallbacks.board`. The GUI owns the service lifecycle (`pyside_gui/board_runtime.py`, no
Qt) and renders posts in `MessageBoardView`.

**Tech Stack:** Python 3.14, FastAPI + uvicorn (new), stdlib `sqlite3`, `httpx` (already in core),
PySide6.

Spec: [spec.md](spec.md) — the contract in spec §5 is authoritative for endpoint behaviour.

**Revision:** 2026-10-08 review incorporated; spec and plan approved by the user's deliver request.

## Global Constraints

- Python env `dagi`. The interpreter is `C:\Users\alexr\anaconda3\envs\dagi\python.exe`. The
  miniconda path in AGENTS.md does not exist on this machine.
- Test command: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt <paths>`
- Full suite: use the same command with `tests pyside_gui/tests` explicitly. The GUI conftest
  registers pytest-qt after the PySide DLL bootstrap; plain pytest skips that test directory.
- Functions ≤ 100 lines, cyclomatic complexity ≤ 8, ≤ 5 positional parameters, lines ≤ 100
  chars, files ≤ 500 lines.
- Handle format `<slug>_<uuid8>`: slug `[a-z0-9][a-z0-9-]{0,31}`, uuid8 = 8 lowercase hex.
- Post text 1..700 chars, rejected (never truncated) when longer. Meme name ≤ 64 chars.
- Attachments: ≤ 4 per post, ≤ 10 MB each (10 * 1024 * 1024 bytes), id `att_<12 hex>`, `kind`
  from magic bytes (PNG/JPEG/GIF/WebP → `image`, else `file`), name sanitised to ≤ 128 chars.
- `limit`: 1..200 on the API (default 50), 1..10 on `read_board` (default 10). A board read never
  includes attachment contents. Worst-case `read_board` output is < 13,000 characters,
  including headers, optional fields, attachment lines, separators and the continuation hint.
- Post and reply ids are positive signed 64-bit integers; `after` is 0..2**63-1. Rendering uses
  decimal ids, minute-resolution timestamps and fixed attachment-size units from B through MB.
- Downloads validate remote metadata and resolved containment under the permitted project
  cache root; server sanitisation is not a client trust boundary.
- Never terminate a process based on an HTTP-supplied PID. Local stop uses the instance's
  shutdown capability; failed startup cleanup uses only the child process handle we created.
- Default URL `http://127.0.0.1:8765`. Token env var `DAGI_BOARD_TOKEN`. Default DB
  `<DAGI_ROOT>/.dagi/board/board.sqlite3`.
- Post timestamps are server-clock UTC, ISO-8601 with a `Z` suffix, second precision.
- No local file paths in any post or member record.
- Tool registration order is a pinned contract (`tests/test_tool_registry_contract.py`):
  `read_board, post_board, fetch_attachment` take emote's slot, directly before `show_file`.
- Workers do not stage or commit. The main agent commits after each subtask passes review.

---

### Subtask 1: Board store (SQLite, no HTTP)

**Status:** Complete — independent PASS; 42 store tests passed.

**Goal:** A thread-safe SQLite store that implements every data rule in spec §5.
**Requirements:**
- `register_member`: idempotent for the same (handle, kind, host). Raises `HANDLE_TAKEN` (409)
  on a conflict. Raises `INVALID` (422) for a malformed handle or a kind outside agent/user.
- `create_post`: validates the author exists (`UNKNOWN_AUTHOR` 404), `reply_to` exists
  (`UNKNOWN_POST` 404), and text/meme limits (`INVALID` 422). Extracts mentions, stamps
  `created_at`, and updates the author's `last_seen`.
- `list_posts(after, limit, mention)` uses the after/latest semantics from spec §5, always
  ascending. Every post includes its `attachments` list (metadata only).
- Ids come from `AUTOINCREMENT` (never reused).
- Attachments:
  - `add_attachment(uploader, name, data: bytes) -> dict`:
    - checks: uploader exists (`UNKNOWN_AUTHOR`), data is non-empty (`INVALID`), and
      `len(data) <= MAX_ATTACHMENT` (`TOO_LARGE`, 413);
    - writes the blob to `<db dir>/blobs/<sha256>` (temp file plus `os.replace`, skipped if it
      already exists);
    - inserts the metadata with `post_id` NULL.
  - `get_attachment(id) -> (dict, Path)`, or `UNKNOWN_ATTACHMENT`.
  - `create_post(..., attachments=[ids])` checks there are ≤ 4, each exists, each was uploaded by
    the author (`INVALID`), and none is used yet (`ATTACHMENT_USED`, 409). In the same
    transaction it sets `post_id`.
- Helpers: `sniff_kind(head: bytes) -> "image"|"file"` (PNG `\x89PNG\r\n\x1a\n`, JPEG
  `\xff\xd8\xff`, GIF `GIF87a`/`GIF89a`, WebP `RIFF....WEBP`); `sniff_mime` (the image mimes
  above, else `mimetypes.guess_type(name)` or `application/octet-stream`); and
  `sanitize_name(name)` per spec §5 (basename, replace forbidden and control chars, ≤ 128, never
  empty → `file`). Strip trailing dots/spaces, map `.`/`..` to `file`, and prefix Windows
  device basenames (case-insensitive, including extensions, e.g. `CON.txt`) with `_`.
**Acceptance Criteria:**
- All tests in `tests/message_board/test_store.py` pass, and the store reopens an existing DB
  file with its data intact.

**Files:**
- Create: `services/message_board/__init__.py` (empty docstring module)
- Create: `services/message_board/store.py`
- Create: `services/message_board/blobs.py` (`sniff_kind`, `sniff_mime`, `sanitize_name`,
  `write_blob(blob_dir, data) -> sha256`), which keeps `store.py` well under 500 lines
- Test: `tests/message_board/__init__.py`, `tests/message_board/test_store.py`
- Modify: `.gitignore`, adding `.dagi/board/` after the `.dagi/attachments/` line (~197)

#### Tests
- `test_store.py` covers:
  - registration idempotency and conflicts, and handle validation;
  - post validation errors, including 700 vs 701 characters;
  - mention extraction (dedupe, order, malformed ignored);
  - after/latest/mention reads, monotonic ids across a reopen, and the `last_seen` update;
  - attachments: blob dedupe (two uploads of the same bytes → one blob file, two ids); `kind`
    sniffing per format; a `.png` name with text bytes is still `file`; `sanitize_name` table
    (`..\\..\\evil.exe` → `evil.exe`, `a:b*c` → `a_b_c`, empty → `file`); `TOO_LARGE` at
    `MAX_ATTACHMENT + 1`; posts with 5 attachments, someone else's attachment, and reuse
    (`ATTACHMENT_USED`); and post records listing attachment metadata.
  - name edge cases: `.`/`..`, trailing dots/spaces, `CON`, `NUL.txt`, `COM1` and `LPT9`;
    duplicate attachment ids in one post are rejected, and failed post transactions roll back.

- [x] **Step 1: Write the failing tests**

```python
"""tests/message_board/test_store.py — SQLite board store contract (spec §5)."""
from __future__ import annotations

import pytest

from services.message_board.store import BoardStore, StoreError, extract_mentions

A, B = "main_3f9a1c2e", "researcher_9b21c0de"


@pytest.fixture()
def store(tmp_path):
    s = BoardStore(tmp_path / "b.sqlite3")
    s.register_member(A, "agent", host="pc")
    s.register_member(B, "agent", host="pc")
    return s


def _code(exc_info) -> str:
    return exc_info.value.code


def test_register_is_idempotent_and_conflicts_on_kind(store):
    _, created = store.register_member(A, "agent", host="pc")
    assert created is False
    with pytest.raises(StoreError) as e:
        store.register_member(A, "user", host="pc")
    assert _code(e) == "HANDLE_TAKEN" and e.value.status == 409


@pytest.mark.parametrize("bad", ["Main_3f9a1c2e", "main_3f9a1c2", "main", "_3f9a1c2e", "x" * 33 + "_3f9a1c2e"])
def test_rejects_malformed_handles(store, bad):
    with pytest.raises(StoreError) as e:
        store.register_member(bad, "agent")
    assert _code(e) == "INVALID"


def test_post_validation(store):
    for kwargs, code in [
        (dict(author="ghost_00000000", text="hi"), "UNKNOWN_AUTHOR"),
        (dict(author=A, text=""), "INVALID"),
        (dict(author=A, text="x" * 701), "INVALID"),
        (dict(author=A, text="hi", meme="m" * 65), "INVALID"),
        (dict(author=A, text="hi", reply_to=999), "UNKNOWN_POST"),
    ]:
        with pytest.raises(StoreError) as e:
            store.create_post(**kwargs)
        assert _code(e) == code


def test_extract_mentions_dedupes_in_order_and_ignores_malformed():
    text = f"@{B} and @{A}, again @{B}; not @Bad_1234 or @main"
    assert extract_mentions(text) == [B, A]


def test_post_record_shape(store):
    post = store.create_post(author=A, text=f"ping @{B}", meme="eat_first")
    assert post["id"] == 1 and post["board"] == "default" and post["mentions"] == [B]
    assert post["meme"] == "eat_first" and post["reply_to"] is None
    assert post["created_at"].endswith("Z")


def test_reads_after_latest_and_mention(store):
    for i in range(5):
        store.create_post(author=A, text=f"p{i}" + (f" @{B}" if i % 2 else ""))
    assert [p["id"] for p in store.list_posts(after=3)] == [4, 5]
    assert [p["id"] for p in store.list_posts(limit=2)] == [4, 5]
    assert [p["id"] for p in store.list_posts(mention=B)] == [2, 4]
    assert store.latest_id() == 5


def test_ids_survive_reopen(tmp_path):
    s = BoardStore(tmp_path / "b.sqlite3")
    s.register_member(A, "agent")
    s.create_post(author=A, text="one")
    s.close()
    s2 = BoardStore(tmp_path / "b.sqlite3")
    assert s2.create_post(author=A, text="two")["id"] == 2


def test_post_updates_last_seen(store):
    before = {m["handle"]: m["last_seen"] for m in store.list_members()}[A]
    store.create_post(author=A, text="x")
    after = {m["handle"]: m["last_seen"] for m in store.list_members()}[A]
    assert after >= before
```

- [x] **Step 2: Run the tests and confirm they fail**

Run: `...python.exe -u -m pytest -q -p no:pytest-qt tests/message_board/test_store.py`
Expected: FAIL with `ModuleNotFoundError: services.message_board.store`

- [x] **Step 3: Implement `services/message_board/store.py`**

```python
"""SQLite storage for the message board service. No HTTP here (see app.py)."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

HANDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}_[0-9a-f]{8}$")
_MENTION_RE = re.compile(r"@([a-z0-9][a-z0-9-]{0,31}_[0-9a-f]{8})(?![0-9a-z_-])")
MAX_TEXT, MAX_MEME, MAX_LIMIT, MAX_ATTACHMENTS = 700, 64, 200, 4
MAX_ATTACHMENT = 10 * 1024 * 1024
_KINDS = ("agent", "user")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    handle TEXT PRIMARY KEY, display_name TEXT NOT NULL, kind TEXT NOT NULL,
    host TEXT NOT NULL, registered_at TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, board TEXT NOT NULL, author TEXT NOT NULL,
    text TEXT NOT NULL, mentions TEXT NOT NULL, meme TEXT, reply_to INTEGER,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS post_mentions (post_id INTEGER NOT NULL, handle TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL,
    kind TEXT NOT NULL, sha256 TEXT NOT NULL, uploader TEXT NOT NULL,
    created_at TEXT NOT NULL, post_id INTEGER);
CREATE INDEX IF NOT EXISTS idx_attachments_post ON attachments(post_id);
CREATE INDEX IF NOT EXISTS idx_post_mentions ON post_mentions(handle, post_id);
"""


class StoreError(Exception):
    """A request the store refuses; maps 1:1 onto the API's {error, code} body."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def extract_mentions(text: str) -> list[str]:
    """Well-formed @handles in first-seen order, without duplicates."""
    return list(dict.fromkeys(_MENTION_RE.findall(text)))


def _post_row(row: sqlite3.Row) -> dict:
    post = dict(row)
    post["mentions"] = json.loads(post["mentions"])
    return post


class BoardStore:
    """One SQLite file; every method is safe to call from any thread."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # implement: register_member(handle, kind, display_name=None, host="") -> (dict, bool)
    #   - validate HANDLE_RE / _KINDS -> StoreError("INVALID", ..., 422)
    #   - existing row: same kind+host -> touch last_seen, return (row, False);
    #     else StoreError("HANDLE_TAKEN", ..., 409)
    #   - display_name defaults to the handle
    # implement: list_members() -> list[dict] ordered by registered_at, handle
    # implement: add_attachment(uploader, name, data) -> dict; get_attachment(id) -> (dict, Path)
    # implement: create_post(author, text, meme=None, reply_to=None, attachments=()) -> dict
    #   - validation order: text/meme/count limits, author exists, reply_to exists,
    #     each attachment exists / owned by author / unused
    #   - one transaction (BEGIN IMMEDIATE ... COMMIT): insert post, insert post_mentions rows,
    #     set attachments.post_id, update author last_seen; return the row via _post_row
    #   - _post_row also loads attachment metadata (no sha-path, no post_id) ordered by rowid
    # implement: list_posts(after=None, limit=50, mention=None) -> list[dict]
    #   - clamp limit to 1..MAX_LIMIT
    #   - after given: WHERE id > after ORDER BY id ASC LIMIT ?
    #   - after None: newest `limit` (ORDER BY id DESC LIMIT ?) then reverse
    #   - mention: JOIN post_mentions ON post_id = id AND handle = ?
    # implement: latest_id() -> int (0 when empty)
```

Each method runs under `with self._lock:`. Keep every method under 40 lines.

- [x] **Step 4: Run the tests and confirm they pass** (same command). Expected: all PASS.

- [x] **Step 5: Return for review** with the changed files, test output, and any deviations.

---

### Subtask 2: HTTP API, auth, SSE, entry point

**Status:** Complete — independent PASS; 85 board tests passed, including 5 live CLI checks.

**Goal:** Expose the store over the spec §5 HTTP contract, runnable as `python -m services.message_board`.
**Requirements:**
- `create_app(store, token=None, *, shutdown=None) -> FastAPI`, no global app. `shutdown`
  provides the instance id, local stop capability and a callback to request server exit.
- Every error body is `{"error", "code"}`. Pydantic validation errors map to 422 `INVALID`.
- Auth middleware: when `token` is set, every path except `GET /` and `GET /health` requires
  `Authorization: Bearer <token>`. Otherwise 401 `UNAUTHORIZED`.
- `/health` → `{"status": "ok", "version": 1, "pid": os.getpid(), "instance_id": <uuid>}`.
  The PID is diagnostic only; shutdown never signals it.
- A middleware adds `X-Content-Type-Options: nosniff` to every response. The auth middleware
  exempts `/` and `/health`.
- SSE: an async generator `post_events(store, hub, after)` yields fully formatted event strings.
  `PostHub` wakes waiters on every new post, uses a version counter so no post is missed between
  "list" and "wait", and yields `": ping\n\n"` after 15 s idle. Without `after`, start from
  `store.latest_id()`.
- `__main__.py` has argparse subcommands, with `serve` as the default when none is given:
  - `serve`: `--host` (127.0.0.1), `--port` (8765), `--db` (spec default), `--token` (default
    env `DAGI_BOARD_TOKEN`). `check_bind(host, token)` raises `SystemExit` with a clear message
    for a non-loopback host without a token. `--runtime-dir` defaults to
    `<DAGI_ROOT>/.dagi/board/run`. Run a `uvicorn.Server` with `proxy_headers=False` so shutdown
    checks the actual peer. Its callback sets `server.should_exit` after the response is sent.
    Write an atomic per-port runtime record only after a successful bind; include canonical
    URL, instance id and a random 256-bit stop capability. Restrict the file to the current
    OS user (Windows user ACL / POSIX 0600), never log its contents, and remove it on exit
    only if it still belongs to this instance. Fail startup if secure storage cannot be set.
  - `stop`: `--url` (default URL), `--runtime-dir` (same default as serve), bearer token from
    `DAGI_BOARD_TOKEN`. `stop_local(url, *, runtime_dir, client=None, wait_s=5.0) -> int`:
    - The entry point is synchronous; internally use cancellable async requests to enforce
      wall-clock deadlines even if a peer trickles bytes. An injected client uses the
      `httpx.AsyncClient` interface; production creates and closes its own async client.
    - Refuse non-loopback URLs and redirects (exit 1). Connection refused → already down (0);
      timeouts, foreign/malformed health and other errors → 1 with an actionable reason.
    - Read the protected local record and match its port and instance id to health. Host aliases
      may be loopback equivalents. Missing/stale records → 1, without sending a stop request.
    - Send `POST /shutdown`, body `{instance_id}`, header `X-Dagi-Stop-Token` from the record,
      plus the bearer token if configured. Never call `os.kill` or use the health PID.
    - Poll up to 5 s: connection refused or a different healthy board instance → original
      instance stopped (0); same instance still alive or inconclusive errors → 1.
  - `POST /shutdown` accepts only a direct loopback peer, matching instance id and constant-time
    capability comparison, plus normal bearer auth. Refusals use 403 `FORBIDDEN` for peer or
    capability, 409 `STALE_INSTANCE` for identity. Success is 202 `{status: "stopping"}`.
    An app without shutdown support returns 503 `STOP_UNAVAILABLE`.
  - `is_loopback_host(host)` lives here, and `pyside_gui/board_runtime.py` imports it (no
    duplicate).
- `POST /attachments` consumes `Request.stream()` through a bounded streaming multipart
  parser in `uploads.py`; do not declare `UploadFile`/`Form` parameters or call `request.form()`.
  Count file bytes in parser callbacks and abort at the first chunk exceeding 10 MB, with 413
  `TOO_LARGE` and no further receive calls. Allow exactly one file and one uploader field,
  uploader ≤ 128 bytes, headers ≤ 8 KB per part, and total body ≤ 10 MB + 64 KB overhead.
  Reject excessive declared Content-Length before parsing; enforce the same limits without
  Content-Length. Malformed/extra parts → 422 `INVALID`. Clean up on error/disconnect; only
  complete validated uploads reach `store.add_attachment`. Buffer at most the allowed file
  plus bounded parsing overhead. Offload synchronous store/blob work from async routes.
- `GET /attachments/{id}` returns `FileResponse(path, media_type=mime, filename=name)`, and
  `GET /attachments/{id}/meta` returns the Attachment JSON.
- `POST /posts` accepts `attachments: list[str] = []`.
- New `requirements-board.txt` (`fastapi==<installed>`, `uvicorn==<installed>`,
  `python-multipart==<installed>`), and `requirements-gui.txt` gains `-r requirements-board.txt`.
  Install into `dagi` first (`python.exe -m pip install fastapi uvicorn python-multipart`) and pin
  the versions pip installed.
- `pyproject.toml`: add a `board` extra with the three direct dependencies, include
  `driverless-agi[board]` in `gui`, discover `services.message_board` and its subpackages only
  (do not package doc_converter), and declare `static/*.html` as board package data.
**Acceptance Criteria:**
- `tests/message_board/test_api.py` passes, and `python -m services.message_board --help` works.

**Files:**
- Create: `services/message_board/app.py`, `services/message_board/__main__.py`,
  `services/message_board/uploads.py`, `services/message_board/lifecycle.py`,
  `requirements-board.txt`
- Modify: `pyproject.toml`, `requirements-gui.txt` (include `requirements-board.txt`)
- Test: `tests/message_board/test_api.py`

#### Tests
- `test_api.py`, using `fastapi.testclient.TestClient(create_app(BoardStore(tmp)))`:
  - every endpoint's success and error codes;
  - auth on (401 without and with a wrong token; `/health` stays open) and auth off;
- `GET /posts` after/latest/mention;
  - 422 body shape;
  - attachments: upload, then download round-trips the exact bytes with the right `Content-Type`
    and filename; an 11 MB upload → 413 `TOO_LARGE`; an unknown id → 404; a post with an
    attachment → `GET /posts` lists its metadata;
  - `check_bind` refuses `0.0.0.0` without a token and allows `127.0.0.1`, `localhost` and
    `0.0.0.0`+token;
  - `/health` includes diagnostic `pid` and `instance_id`; `nosniff` is on every response; `/` and
    `/health` are open with a token set;
  - argparse: no subcommand → `serve`;
  - shutdown: remote peer, missing/wrong capability, stale instance, missing/wrong bearer,
    unavailable callback; only a valid request invokes exit, after its 202 response;
  - `stop_local` fakes: remote URL, foreign health (including PID 0, -1 and unrelated positive
    PIDs), missing/stale runtime record and redirect → 1 without shutdown; refused connection
    → 0; valid shutdown then down/replaced instance → 0; timeout/still alive → 1. No PID kill.
  - runtime-record permissions, atomic write, no record on bind failure, and old-instance
    cleanup cannot remove a replacement record;
  - streaming upload: instrument ASGI receive/parser consumption for oversized file, excessive
    headers/fields, missing Content-Length and disconnect. Assert early abort without draining
    remaining chunks or persisting metadata; test exactly 10 MB and overhead boundaries.
  - `post_events`: drive the generator with `asyncio.run`, assert backlog events after `after=0`
    come first in id order and in the exact `id:/event:/data:` format; then create a post plus
    `hub.notify()` from a task and assert the next event is that post. Patch the ping interval to
    0.05 s to assert a `: ping` comment.
  - Do **not** consume `/stream` through `TestClient` (it's an endless response). The generator
    test covers it, and Subtask 5 covers the real endpoint over a live server.

- [x] **Step 1: Write the failing tests** (the cases listed above, one test per behaviour).
- [x] **Step 2: Install the deps, then run the tests and confirm they fail** on the missing
  `services.message_board.app`.
- [x] **Step 3: Implement `app.py` and `__main__.py`**

Key shapes:

```python
class PostHub:
    """Version counter + condition: waiters never miss a post made between list and wait."""

    def __init__(self) -> None:
        self.version = 0
        self._cond: asyncio.Condition | None = None  # created lazily on the serving loop

    def _condition(self) -> asyncio.Condition: ...
    async def notify(self) -> None: ...          # version += 1; notify_all
    async def wait_past(self, version: int, timeout: float) -> bool: ...  # False on timeout


PING_SECONDS = 15.0


async def post_events(store, hub, after):
    cursor = await asyncio.to_thread(store.latest_id) if after is None else after
    while True:
        seen = hub.version
        posts = await asyncio.to_thread(store.list_posts, after=cursor, limit=200)
        for post in posts:
            cursor = post["id"]
            yield f"id: {post['id']}\nevent: post\ndata: {json.dumps(post)}\n\n"
        if posts:
            continue
        if not await hub.wait_past(seen, PING_SECONDS):
            yield ": ping\n\n"
```

The routes are `async def`. Offload synchronous SQLite/blob operations with a threadpool;
`POST /posts` awaits the store write and then `await hub.notify()` on the serving event loop.
`/stream` returns `StreamingResponse(post_events(...), media_type="text/event-stream",
headers={"Cache-Control": "no-cache"})`. A `StoreError` exception handler returns
`JSONResponse(status_code=e.status, content={"error": e.message, "code": e.code})`.

- [x] **Step 4: Run the tests and confirm they pass.**
- [x] **Step 5: Return for review**, including the pinned versions.

---

### Subtask 3: Python client and BoardSession

**Status:** Complete — independent PASS; 57 client/SSE tests passed.

**Goal:** The only dagi-side code that speaks the board's HTTP: typed calls, actionable errors,
and a per-agent cursor.
**Requirements:**
- `agent/board_client.py`:
  - `BoardError(code, message)`.
  - `BoardClient(base_url, token=None, http=None, timeout=10.0)` with methods `health`,
    `register(handle, kind, display_name=None, host=None)`, `members`,
    `post(author, text, meme=None, reply_to=None, attachments=None)`,
    `posts(after=None, limit=50, mention=None)`, `upload(uploader, path: Path) -> dict`
    (multipart, 120 s timeout), `attachment_meta(att_id)`, and
    `fetch_attachment(att_id, *, project_root, cancel=None, deadline_s=120.0) -> (dict, Path)`.
    Fetch verifies metadata, streams to a unique exclusive temporary file in the safe cache
    directory, verifies declared size (≤ 10 MB) and sha256, then uses `os.replace`. On any
    failure or cancellation remove only this call's temp file. Reuse verified cached bytes.
    Use a monotonic total deadline plus bounded read timeouts; expose cancellation checks
    between chunks. The GUI uses a 10 s total deadline and 1 s read timeout. Disable redirects.
    Keep the public call synchronous, with cancellable async HTTP internally for downloads:
    the total deadline covers metadata, headers and body even when a peer trickles bytes.
    An optional async client/factory test seam supports ASGI/MockTransport injection; normal
    methods retain the synchronous `http` injection. Own production async clients per fetch
    so concurrent calls and separate event loops never share a pooled client.
  - `stream(after) -> contextmanager yielding str lines` (httpx `stream("GET", "/stream")`
    with `timeout=httpx.Timeout(10.0, read=45.0)`).
    Yield a closable line iterator so listener shutdown can interrupt a blocked read. SSE
    requests use `Connection: close`, preventing a finished stream's socket from entering
    the shared pool while another thread closes the iterator.
  - All HTTP paths are relative. When `http` is None it builds `httpx.Client(base_url=base_url)`, and
    the bearer header is added per request when a token is set.
  - Connection errors become `BoardError("UNREACHABLE", f"message board unreachable at
    {base_url}")`, timeouts become `"TIMEOUT"`, and a non-2xx response uses the body's code and
    error (falling back to `HTTP_<status>`).
- `agent/_board_files.py` owns pure cache validation and hashing helpers, with no HTTP:
  - Require attachment id `att_<12 lowercase hex>`, metadata id equal to the requested id,
    size 1..10 MB, and a 64-character lowercase hex sha256.
  - Names must be single basenames ≤ 128 characters, with no separators, absolute/drive/UNC
    paths, forbidden/control characters, dot names, trailing dot/space or Windows devices.
    Helpers raise ValueError; BoardClient maps it to `BoardError("INVALID_ATTACHMENT", ...)`
    to avoid a circular import. Do not silently rename unsafe metadata.
  - `attachment_cache_path(project_root, att)` verifies the resolved cache root, attachment
    directory, destination and temp-file directory stay under `project_root/.dagi/board/attachments`.
    Reject symlink/junction components, including a redirected `.dagi`, before directory creation
    or writing. Tools also enforce their allowed roots via `validate_path`; GUI uses DAGI_ROOT.
    Existing local links must never turn a download into an outside-root write.
  - Use unique temp files for concurrent downloads; repeat containment checks before replace.
    Cache size and hash must match before reuse. A hostile concurrent local filesystem mutator
    is outside v1's threat model; metadata traversal and existing links are covered.
- `new_handle(slug) -> str` validates the slug and returns `f"{slug}_{uuid4().hex[:8]}"`.
- `BoardSession(client, handle)`:
  - `read(limit=20, mentions_only=False) -> list[dict]` keeps **two cursors**, one for all posts
    and one for mentions, so a mentions-only read never skips unread non-mention posts. The first
    read in each mode returns the latest `limit`, and each cursor advances to the max id returned.
  - `post(text, meme=None, reply_to=None, files=()) -> dict` uploads each path in order, then
    creates the post with the returned ids. It does no path or size checks; the tool does those
    first.
  - `fetch(att_id, project_root: Path) -> (dict, Path)` delegates to the shared
    `client.fetch_attachment` method. Do not duplicate cache/download logic in BoardSession.
  - All of these run under a `threading.Lock` (around the cursors only, not network I/O, for
    `fetch` and `post`).
**Acceptance Criteria:**
- `tests/test_board_client.py` passes against the real app through `TestClient` (injected as
  `http`).

**Files:**
- Create: `agent/board_client.py`
- Create: `agent/_board_files.py`
- Test: `tests/test_board_client.py`, `tests/test_board_stream.py`

#### Tests
- Round trip: register, post, posts.
- Errors map to `BoardError` codes (`UNKNOWN_AUTHOR`, `UNAUTHORIZED` with a token-protected app,
  `UNREACHABLE` using `BoardClient("http://127.0.0.1:9")`).
- `new_handle` format and slug rejection.
- Session: first read returns the latest N; the second returns only new posts; a mentions-only
  read doesn't advance the all-posts cursor; concurrent `read` calls from 2 threads never return
  the same post twice.
- Upload and download round trip with byte equality. `fetch` reuses a file whose sha matches
  (assert no second GET by counting requests through an httpx event hook) and re-downloads one
  whose sha doesn't match. No temporary file is left after success, error or cancellation.
- Metadata traversal/absolute/drive/UNC names, dot names, reserved Windows names, trailing
  dots/spaces, malformed or mismatched ids, invalid size/hash and symlink/junction cache escapes
  are rejected before writes. Exercise both BoardSession and the session-free client entry.
- Two concurrent fetches of the same attachment use distinct temp files and leave correct
  verified bytes; bad download size/hash never replaces a valid cached file. Cover deadline,
  cancellation and redirect rejection with injected transports.

- [x] Step 1 write failing tests · Step 2 run (FAIL: module missing) · Step 3 implement ·
  Step 4 run (PASS) · Step 5 return for review.

---

### Subtask 4: `read_board`/`post_board`/`fetch_attachment` tools, replacing `emote`

**Status:** Complete — independent PASS; 114 targeted tests and 28 final board-tool tests passed.

**Goal:** Agents read, post and fetch attachments through three tools bound to a `BoardSession`.
Remove the obsolete `emote` tool and its callback/config/prompt references. Existing affect
expression assets and identifiers are outside this migration.
**Requirements:**
- `tools/board/__init__.py` exports `ReadBoardTool`, `PostBoardTool` and `FetchAttachmentTool`.
  `tools/board/_board.py`
  implements them as in spec §6, including the exact line format, the `(you)` marker, the
  `limit` hint and `(no new posts)`. `_scan_memes` and `_build_description` move here from
  `tools/emote/_emote.py`, with the description rewritten for posting.
  - `read_board` params: `mentions_only` (bool), `limit` (int 1..10, default 10; clamp values
    outside the range).
  - `post_board` params: `text` (required), `attachments` (optional array of path strings, at
    most 4), `meme` (optional), `reply_to` (optional int).
    - Built with `cwd` and `allowed_roots`.
    - Before any network call it checks: text ≤ 700 (with the "put details in an attachment"
      message), ≤ 4 paths, and each path resolves under the roots via
      `tools._path_guard.validate_path`, exists, is a file, and is ≤ 10 MB.
    - Only then does it call `session.post(..., files=paths)`.
  - `fetch_attachment` params: `attachment_id` (required, must match `^att_[0-9a-f]{12}$`). It
    validates the project cache against allowed_roots, calls `session.fetch(id, cwd)` and
    returns the spec §6 message. On first save it creates `<cwd>/.dagi/board/.gitignore`
    containing `*` if missing, after validating its parent is within the project.
  - The attachment line format is shared by a `format_post(post, me) -> str` helper. The GUI will
    reuse it, and the follow-up task will reuse it for wake-up messages.
- `AgentCallbacks` (`agent/_loop_config.py:205-208`): remove `on_message_board_post` and add
  `board: "BoardSession | None" = None` (`TYPE_CHECKING` import from `agent.board_client`).
- `agent/tools.py:_register_frontend_tools`: replace the emote block. If `callbacks.board` is
  not None, register `ReadBoardTool(session=board)`, then `PostBoardTool(session=board,
  memes_root=_DAGI_ROOT / ".dagi" / "emotes" / "memes", cwd=cwd, allowed_roots=roots)`, then
  `FetchAttachmentTool(session=board, cwd=cwd, allowed_roots=roots)`.
  This fixes the always-registered bug.
  - `_register_frontend_tools` needs `cwd` and `roots`. Pass them from `create_tool_registry`
    (compute `roots = _sandbox_roots(...)` once there) through `_register_session_tools`
    (new keyword `roots`).
- Delete `tools/emote/` and `tests/test_emote_tool.py`. Port their meme scanning and validation
  cases to `tests/test_board_tools.py`.
- `pyside_gui/tool_labels.py:30`: replace `"emote"` with `"post_board": ("Posted", ("text",))`,
  `"read_board": ("Read board", ())` and `"fetch_attachment": ("Fetched", ("attachment_id",))`
  (match the existing tuple shape).
- `.dagi/config.yaml:58-59` and `config.example.yaml:149-150`: replace the `emote` lines with a
  `# ── Board tools` header plus `read_board`, `post_board` and `fetch_attachment` lines.
- `.dagi/prompts/main/main_system.md` "## Emote" section: rename it to "## Message board" and
  rewrite it. Use `post_board` with a meme for the existing "express how you feel" guidance (same
  trigger list), add when to `read_board` (start of a task, when told someone posted), and
  explain that `@handle` mentions address a member.
- Update `tests/test_tool_registry_contract.py`:
  - drop `"emote"` from `test_full_interactive_config_order` and
    `test_extra_bash_and_partial_frontend_callbacks`;
  - add `test_board_tools_take_emote_slot_before_show_file` with
    `AgentCallbacks(board=<fake session>)`, asserting `..., "reload_skills", "read_board",
    "post_board", "fetch_attachment", "show_file", "read_notepad", ...`.
- Update `tests/test_tool_filter.py:71,84` (they construct `AgentCallbacks(on_message_board_post=...)`)
  and `tests/test_agent_loop.py:873-888` (the emote allowlist test). Re-express both with
  `board=` and `read_board`/`post_board`, keeping what each test is checking.
**Acceptance Criteria:**
- `grep -rn "emote\b\|EmoteTool\|on_message_board_post" --include=*.py --include=*.yaml
  --include=*.md agent tools tests pyside_gui tui tg .dagi config.example.yaml` finds no tool or
  callback references. VAD `emote_id` and the `emotes/` asset folders are unrelated and stay.
- The registry contract, filter, agent loop and board tool tests pass.
- `pyside_gui` still imports. It may not have a board yet, so the bridge just stops passing
  `on_message_board_post`. Subtask 6 adds the rest.

**Files:**
- Create: `tools/board/__init__.py`, `tools/board/_board.py`, `tests/test_board_tools.py`
- Delete: `tools/emote/__init__.py`, `tools/emote/_emote.py`, `tests/test_emote_tool.py`
- Modify: `agent/_loop_config.py:205-208`, `agent/tools.py:162-175`,
  `pyside_gui/tool_labels.py:30`, `pyside_gui/bridge.py:55,207-208,239` (remove the
  `on_message_board_post` plumbing and leave the `message_board_post` signal until Subtask 6),
  `pyside_gui/app.py:244-249` (temporarily drop the two `message_board_post` connects),
  `.dagi/config.yaml`, `config.example.yaml`, `.dagi/prompts/main/main_system.md`,
  `tests/test_tool_registry_contract.py`, `tests/test_tool_filter.py`, `tests/test_agent_loop.py`

#### Tests
- `test_board_tools.py`, with a `BoardSession` over `TestClient`, covers:
  - the output line format, `(you)`, `(re #n)`, `[meme: x]`, the limit hint and
    `(no new posts)`;
  - attachment lines (`📎`/`🖼`, human size, id) with the file bytes never in the output;
  - a **worst case** of 10 posts × 700 characters × 4 attachments with 128-character names,
    41-character authors, `(you)`, 64-character memes, maximum signed-64-bit post/reply ids,
    timestamps and the continuation hint. Assert output is < 13,000 characters. Attachment
    names show at most 40 characters plus `…`; full names are retained for saving. Bound the
    size formatter to fixed B/KB/MB units and document the renderer's maximum-field calculation;
  - a `limit` of 50 clamped to 10;
  - `post_board`: text of 701 characters is rejected with the attachment hint; a path outside
    the roots, a missing file, an oversized file (sparse 10 MB + 1) and a fifth path are each
    rejected **with no upload made** (count requests); success returns `Posted #<id>.` with the
    attachments listed by a subsequent read;
  - an unknown meme error that lists the available memes, a description that lists memes, and
    the "No memes" fallback;
  - `fetch_attachment`: saves under `cwd/.dagi/board/attachments/<id>/<name>`, the message
    tells the agent to open it with `read`, and a malformed id is rejected;
  - a `BoardError` from the client surfaces as an `Error: …` result through
    `ToolRegistry.dispatch`.

- [x] Step 1 write failing tests · Step 2 run (FAIL) · Step 3 implement and edit callers ·
  Step 4 run the touched test files plus the full suite (PASS) · Step 5 return for review.

---

### Subtask 5: GUI board runtime (no Qt)

**Status:** Complete — independent PASS; 108 combined runtime/client/service tests passed.

**Goal:** Service lifecycle, identity and the SSE listener as plain Python, so they're
unit-testable without Qt.
**Requirements:**
- `pyside_gui/board_runtime.py`:
  - `DEFAULT_BOARD_URL`.
  - `is_loopback_url(url) -> bool`: `localhost` or a loopback IP.
  - `load_or_create_user_handle(path) -> str`: reads a valid handle, otherwise writes a new
    `user_<uuid8>`.
  - `BoardRuntime` (dataclass: `client`, `session`, `user_handle`, `spawned_pid: int | None`).
  - `start_board(url, token, *, state_dir, client_factory=BoardClient,
    spawn=spawn_service, wait_s=10.0, sleep=time.sleep, clock=time.monotonic, cancel=None)`
    returns `BoardRuntime`:
    - The health check counts only if `version == 1`.
    - Spawn only after connection refusal on loopback. Foreign/malformed health, auth failure
      or incompatible version → `NOT_A_BOARD`/actionable error without spawn. Poll health every
      0.25 s until a monotonic deadline; each request is bounded by remaining time.
    - Register `main_<uuid8>` (kind agent, host `socket.gethostname()`) and the user handle
      (kind user).
    - Otherwise raise `BoardError` with a reason the view can show (`OFFLINE`, `SPAWN_FAILED`,
      `NOT_A_BOARD`).
  - `spawn_service(host, port, log_path, *, db_path=None, runtime_dir=None) -> SpawnedService`:
    runs `sys.executable -m services.message_board serve --host --port [--db --runtime-dir]`
    **detached**. The injectable SpawnedService wrapper owns the Popen handle, pid and
    terminate/wait methods during startup; tests use a fake wrapper.
    - `cwd=DAGI_ROOT`, `stdin=DEVNULL`, output appended to `log_path`, `close_fds=True`.
    - On Windows, `creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`;
      elsewhere, `start_new_session=True`.
    - The token is inherited through the environment.
    - On failed startup/cancellation, clean up only this still-owned child through its process
      handle and reap it. After successful readiness, release the startup wrapper without
      terminating it; BoardRuntime retains only spawned_pid for diagnostics. Never kill an
      HTTP-supplied PID or an unverified replacement process.
  - No `stop_board`: the GUI never stops the board (spec G6).
  - `parse_sse(lines) -> Iterator[dict]`: yields `data` JSON for `event: post` blocks and ignores
    comments and blank lines.
  - `StreamListener(threading.Thread, daemon)`: arguments `client`, `after`, `on_post(dict)`,
    `on_status(str)`. Loops `client.stream(after)` → `parse_sse`, tracks the max id, drops ids
    ≤ max id, reconnects with backoff 1, 2, 4 … 30 s, and calls `on_status("connected" |
    "reconnecting: <reason>")`. `stop()` sets an event and closes the active response.
**Acceptance Criteria:**
- `tests/test_board_runtime.py` passes, including one **live** test that runs the real service.

**Files:**
- Create: `pyside_gui/board_runtime.py`
- Test: `tests/test_board_runtime.py`

#### Tests
- `is_loopback_url` table.
- User-handle persistence: created once, reused, and a corrupt file is replaced.
- `start_board` with injected client factory, fake SpawnedService and clock/sleep:
  - already healthy → no spawn;
  - refused loopback connection → spawn, then health succeeds;
  - unhealthy remote → `OFFLINE` with no spawn;
  - foreign server (`version` missing) → `NOT_A_BOARD`;
  - spawn never healthy/cancelled → `SPAWN_FAILED`/cancellation and only the owned child
    wrapper is terminated/reaped; foreign health never spawns or terminates anything;
  - close/start cancellation with an already running service leaves that service running.
- `parse_sse` on canned text: two posts, a ping and a split block.
- Listener dedupe and reconnect using a fake client whose `stream` raises once and then replays
  overlapping ids.
- **Live:** pick a free port and a tmp `--db` (pass it through an env var such as
  `DAGI_BOARD_DB` or a `db_path` parameter on `spawn_service`, so the test never touches the real
  board DB; also pass a tmp runtime_dir). Then `spawn_service`, wait for health, register,
  post, and read one event through
  `StreamListener` (with a 10 s timeout). Finally,
  `stop_local(url, runtime_dir=tmp_runtime_dir)` returns 0 and health is
  down. A `finally` block cleans up only the owned child handle if the test failed early.
  This also covers `__main__`
  `serve`/`stop`, detached spawn and `/stream` end to end.

- [x] Step 1 write failing tests · Step 2 run (FAIL) · Step 3 implement · Step 4 run (PASS) ·
  Step 5 return for review.

---

### Subtask 6: GUI wiring — live board view, user posting, agent binding

**Goal:** The GUI starts the board, binds the main agent's `BoardSession` into every turn,
renders posts live, and lets the user post.
**Requirements:**
- `pyside_gui/bridge.py`: replace `message_board_post` with `board_post = Signal(object)` (a Post
  dict), `board_status = Signal(str)` and `board_ready = Signal(object)` (a `BoardRuntime` or a
  `BoardError`). `build_callbacks(loop_ref=None, board=None)` passes `board=board` to
  `AgentCallbacks`.
- `pyside_gui/_dispatch.py:157`: `win._bridge.build_callbacks(win._current_loop_ref,
  board=win._board_session)`. Grep for any other `build_callbacks(` callers and give them the
  same argument.
- `pyside_gui/app.py`:
  - In `__init__`, set `self._board_runtime = None`, `self._board_session = None` and
    `self._board_listener = None`, a closing flag and a cancellation event; start a daemon
    thread running `start_board(url, token, cancel=<event>,
    state_dir=DAGI_ROOT/".dagi"/"board")` that emits `board_ready`. Take `url` from
    `self._config.services.get("message_board", DEFAULT_BOARD_URL)` and the token from env
    `DAGI_BOARD_TOKEN`.
  - The `_on_board_ready` slot (main thread):
    - if closing, ignore the result and do not create a listener, poster or download work;
    - on an error, `board_view.set_status(f"Board offline — {err.message}")`;
    - otherwise store the runtime and session and call `board_view.set_poster(...)`. Load
      `client.posts(limit=50)` on the worker, emit the snapshot through Qt signals, then stream
      after its maximum id (0 if empty). Posts between snapshot and connection are replayed.
  - The user poster runs on a daemon thread: `client.upload(user_handle, p)` for each path, then
    `client.post(user_handle, text, attachments=ids)`. Errors are routed to `board_status`.
    Reuse the size and count checks in a pure `validate_user_files(paths) -> (ok, errors)`
    helper in `board_runtime.py`.
  - Connect `board_post` to `board_view.add_post`, plus a lambda that calls `cv.append_emote(meme,
    local_path, text, created_at)` when `post["author"] == main handle` and the meme resolves.
  - In `closeEvent`, mark closing and cancel startup, stop the listener, cancel queued downloads
    and signal active downloads before the existing pet close. Never wait on network I/O in
    the Qt thread. Drop all late board/download signals after closing. **Don't** stop a ready
    board service. Close owned HTTP clients from worker cleanup after active work unwinds.
- `pyside_gui/sidebars/message_board.py`:
  - `BoardPost` gains `id`, `mentions` and `reply_to`. `asset_path` becomes `Path | None`,
    resolved from the meme name through the moved `_scan_memes` helper (import it from
    `tools.board._board`; no duplicate).
  - `add_post(post: dict)` dedupes by id and inserts newest-first.
  - `set_status(text)` shows a small status line under the header.
  - `set_poster(callable(text, paths) | None)` enables the composer at the bottom:
    - a `QLineEdit` plus a `n/700` counter label that turns red, with Send disabled, over 700;
    - an **Attach** `QToolButton` that calls `QFileDialog.getOpenFileNames(self, "Attach
      files")` (the native Windows dialog);
    - chosen files appear as removable chips; adding more than 4, or a file over 10 MB, shows a
      status message and skips that file;
    - Enter or Send calls the poster with `(text, paths)`, then clears the text and chips.
  - Attachments on cards:
    - The view gets a `fetch(att_id) -> Future[Path]`-style callable from the window, using
      session-free `client.fetch_attachment(project_root=DAGI_ROOT, cancel=<event>,
      deadline_s=10.0)` and the shared cache validator. No duplicate download/cache path logic.
    - `image`: a placeholder label that becomes a thumbnail (`_IMG_MAX`) once downloaded.
    - `file`: a chip `📎 name (size)`.
    - Clicking either emits `open_file_requested(str)`, which the window connects to
      `self._left_sidebar.open_file(path, None)`.
    - The existing file viewer reads non-Markdown files as text. Add a bounded image preview
      branch in `pyside_gui/sidebars/file_viewer.py` so clicking PNG/JPEG/GIF/WebP attachments
      displays an image, not decoded binary text. Use QImageReader with dimension/allocation
      limits and scaled decode; retain existing text/Markdown behavior and text-size limits.
    - Downloads are triggered when a card is created, with at most 2 daemon workers in a
      window-owned `DownloadPool` (`pyside_gui/board_downloads.py`, plain Python, queue/Future).
      `stop()` cancels queued futures, sets active cancellation and returns without joining
      network work. Workers check cancellation before each job and throughout streaming.
      Do not use ThreadPoolExecutor: its pending futures delay interpreter shutdown.
    - Future callbacks emit Qt signals only. Thumbnail creation/widget mutation happens in
      main-thread slots, guarded by closing/card-lifetime checks (QPointer or weak references).
  - If the file passes 500 lines, split the card and composer widgets into
    `pyside_gui/sidebars/board_widgets.py`.
  - Card header: author, then `↩ #id` when there's a reply, then the timestamp converted to local
    time. A missing meme shows `[name]`, and no meme shows no image row.
  - Render remote post text, member names, filenames and status errors as plain text in Qt
    labels (`Qt.PlainText`), so untrusted strings cannot become QLabel rich-text markup.
  - Keep the file ≤ 500 lines.
**Acceptance Criteria:**
- The app starts with the board up (auto-spawned) or down (offline status), and the full test
  suite still passes.
- The manual checks A5 in the spec all pass. Record what was observed in the review report.

**Files:**
- Modify: `pyside_gui/bridge.py`, `pyside_gui/_dispatch.py:~157`, `pyside_gui/app.py`
  (`__init__`, `_wire_bridge` ~244, `closeEvent` ~286), `pyside_gui/sidebars/message_board.py`
- Modify: `pyside_gui/sidebars/file_viewer.py` (image attachment preview)
- Create: `pyside_gui/board_downloads.py`
- Test: `tests/test_board_runtime.py`, `tests/test_board_downloads.py`,
  `pyside_gui/tests/test_message_board.py` using qtbot and the existing GUI conftest.
  Cover empty/overlong composer text, attachment count/size refusal, post dedupe, queued
  main-thread thumbnail completion, late completion after destruction, and image attachment
  opening without changing text/Markdown rendering. Pool tests cover
  two-worker concurrency, queued cancellation and active cancellation; a subprocess test
  with a stalled fake download proves workers do not prevent interpreter exit. Startup/close
  race tests prove late readiness cannot recreate the listener. Keep native-dialog/live checks
  manual; fake network and service startup in widget tests.

- [ ] Step 1: Move every non-trivial decision into pure helpers in `board_runtime.py`, each with
  a failing test: `should_render_inline(post, main_handle, meme_map)`,
  `validate_user_files(paths)`; reuse `attachment_cache_path` from `agent/_board_files.py`, and
  `human_size(n)` (shared with `format_post`; define it in `tools/board/_board.py` and import it).
- [ ] Step 2: Run it (FAIL) · Step 3: implement the helper and the Qt wiring · Step 4: run the full
  suite (PASS).
- [ ] Step 5: Launch the GUI (`python pyside_gui.py`) and run A5. Before the first launch, check
  that `services.message_board` is absent from `.dagi/config.yaml` so the default URL is used.
- [ ] Step 6: Return for review with the A5 observations.

---

### Subtask 7: Read-only web viewer

**Goal:** `GET /` serves one static page that shows the board live in any browser.
**Requirements:**
- `services/message_board/static/index.html` is self-contained: inline CSS and JS, no CDN, no
  build step. It's served by `GET /` as `FileResponse(..., media_type="text/html")` and isn't
  behind auth. Resolve it via the installed package (importlib.resources); never depend on
  the caller's cwd. Include it as package data in pyproject.toml.
- Behaviour per spec §5 "Web viewer":
  - `fetch('/posts?limit=50')`, then stream `/stream?after=<max id>` with `fetch` +
    `ReadableStream`, parsing `id:/event:/data:` blocks;
  - reconnect after 1, 2, 4 … 30 s, resuming from the last id and dropping duplicate ids;
  - newest first;
  - images through `fetch('/attachments/<id>')` → `URL.createObjectURL` into `<img>`, files as
    links that download the blob with the original name;
  - a 401 on any call shows a token prompt; the token is saved in `sessionStorage` and sent as
    `Authorization: Bearer`;
  - a status line shows connected / reconnecting / offline.
- Untrusted text goes through `textContent` and `document.createElement` only. **No
  `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`** anywhere in the file.
- Light and dark styles via `prefers-color-scheme`, and readable at phone width.
- ≤ 400 lines.
**Acceptance Criteria:**
- `tests/message_board/test_viewer.py` passes, and the manual browser check in spec A5 passes.

**Files:**
- Create: `services/message_board/static/index.html`
- Modify: `services/message_board/app.py` (the `/` route), `pyproject.toml` (HTML package data)
- Test: `tests/message_board/test_viewer.py`

#### Tests
- `GET /` → 200 `text/html` with `nosniff`, and still 200 with a token set and no header.
- The file contains none of `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` or
  `eval(` (a static grep test, which is the guard against XSS from post content).
- The page references only same-origin paths: no `http://` or `https://` URLs except inside
  comments.
- Build a wheel into a temporary directory and install `[board]` in a clean temporary env.
  Outside the checkout, run `python -m services.message_board --help`, launch on an isolated
  port with tmp DB/runtime directories, and assert GET / returns the packaged HTML. Check
  wheel metadata includes the board dependencies and the GUI extra requires the board extra.
  Cleanly stop through the instance shutdown protocol. Also smoke-test the editable `[gui]`
  installation path. Do not modify the working environment to perform clean-install checks.

- [ ] Step 1 write failing tests · Step 2 run (FAIL) · Step 3 implement the page + route ·
  Step 4 run (PASS) · Step 5 open it in the browser pane against a live board, post through the
  API, and check that it appears live · Step 6 return for review.

---

### Subtask 8: Docs

**Goal:** README, TODO, AGENTS and config docs match reality.
**Requirements:**
- `README.md`:
  - replace the emote message-board paragraph (~line 240) with the board service, covering:
    - that it's its own app that keeps running after the GUI closes;
    - detached auto-start;
    - `python -m services.message_board [serve] [--host --port --db --token]` and
      `python -m services.message_board stop`;
    - the web viewer at `http://127.0.0.1:8765/`;
    - the `DAGI_BOARD_TOKEN` rule;
    - the three tools and the attachment limits;
  - add a "Message board API" section with the spec §5 endpoint table, linking to
    [spec.md](spec.md);
  - document `requirements-board.txt`, editable `[board]`/`[gui]` installs and runtime-dir
    override for isolated service instances. Explain that local stop needs its protected
    runtime record and, when enabled, DAGI_BOARD_TOKEN; health PID is never used to kill.
- `config.example.yaml` `services:` block: add `message_board: "http://127.0.0.1:8765"`, with a
  comment that the token comes from env `DAGI_BOARD_TOKEN`.
- `TODO.md`: mark this task done, and add the follow-up "Multi-agent sessions (spec §9)" as next.
- `AGENTS.md`:
  - fix the test interpreter path (`anaconda3`, not `miniconda3`);
  - add one rule: "Board HTTP lives only in `agent/board_client.py`; posts never carry local
    paths."
**Acceptance Criteria:**
- The docs mention no `emote` tool, and every command shown in them runs.

**Files:** `README.md`, `TODO.md`, `AGENTS.md`, `config.example.yaml`

- [ ] Step 1 edit · Step 2 run the documented commands (`--help`, the test command) · Step 3 return for review.

---

## Workspace
- **Branch:** `task/message-board-api`
- **Parent:** `main`
- **Starting commit:** `3526f7c`
- **Task folder:** `wiki/tasks/2026-10-08_message-board-api/`

## Overall Status
In Progress — approved for delivery on 2026-10-08. Subtasks 1–8 complete and verified. The manual A5 GUI checklist is pending, and so is the
merge decision.

## Notes
- `AgentLoop` is **rebuilt every turn** (`pyside_gui/_dispatch.py:181`), so the handle and
  cursors must live in a window-owned `BoardSession` passed through `AgentCallbacks`. Don't put
  them on the loop or the tools' module state.
- `AgentCallbacks.on_message_board_post` defaults to a truthy no-op lambda, which is why `emote`
  was always registered (central wiki, 2026-09-08 review I1). `board: … | None = None` fixes it.
- `ToolRegistry.dispatch` converts any exception into `Error: <msg>`, so tools raise `BoardError`
  rather than formatting their own errors.
- `TestClient` can't consume an endless SSE response. Test the generator directly (Subtask 2)
  and the live endpoint over a real server (Subtask 5).
- Board dependencies installed in `dagi`: FastAPI 0.142.4, uvicorn 0.54.0 and python-multipart 0.0.32.
- `services/doc_converter` uses FastAPI with its own env. The board deliberately uses the
  `dagi` env so the GUI can auto-start it with `sys.executable`.

## Open Issues
- The main handle is new each time the GUI launches, so mentions of an earlier `main_*` aren't
  read by the new one. That's acceptable for v1. The multi-agent follow-up decides whether
  handles persist with sessions.

- `fetch_attachment` saves under `<cwd>/.dagi/board/attachments/`. The dagi repo gitignores
  `.dagi/board/`, but other projects may not, so fetched files could appear as untracked there.
  For v1, make the tool create `<cwd>/.dagi/board/.gitignore` containing `*` on first save.
- There's no garbage collection of uploads that are never used in a post, or of old blobs.
  That's tracked for a later task.

## Attempts and Resolutions
- **Planning review, 2026-10-08:** replaced HTTP-PID termination with instance-capability
  shutdown; added streaming multipart bounds, shared safe cache writes, complete 13,000-char
  renderer tests, cancellable daemon downloads, package metadata/install checks and GUI tests.
  Spec contracts were updated alongside the plan; delivery is now in progress.

## Verification
Expected outcomes below are final delivery gates. Completed subtask evidence is recorded first.

Delivery evidence so far:
- Subtask 1: 42 tests passed; independent review PASS; committed as `30d45d0`.
- Subtask 2: independent PASS; 85 board tests passed, including 5 real CLI checks; commit `05f4270`.
  Shutdown deadline, Windows async refusal, wildcard bind and open-SSE shutdown regressions pass.
  Runtime records use a separate helper module and cross-process publication/cleanup lock.
  FastAPI sync read routes use its threadpool; async writes explicitly offload store/blob work.
- Subtask 3: independent PASS; combined client/SSE/service run 141 passed, focused client/SSE
  57 passed after stream cleanup guard, and final SSE header/lifecycle run 4 passed.
  Per-fetch async clients enforce total deadlines and Event cancellation. Cache reads and
  publication share a short filesystem-only lock for Windows; network transfers remain parallel.
  Actual directory junctions tested; file-symlink lstat simulation used because this account
  cannot create symlinks (WinError 1314). Existing affect/emote asset identifiers are preserved.
- Subtask 4: independent PASS; 114 targeted tool/registry/filter/loop/config tests, 28 final
  board-tool tests and 37 focused GUI bridge/label tests passed. The full suite reported 2,048
  passed, 4 failed and 3 skipped: three known removed-template failures and one unrelated GUI
  timer teardown race that passed immediately in isolation. The earlier clipboard baseline
  failure passed in this run. Obsolete emote tool/callback references are gone; affect emote
  identifiers remain. Cache `.gitignore` link rejection is covered before any HTTP request.
- Subtask 5: independent PASS; 108 combined runtime/client/service tests passed, including a
  live detached service, SSE delivery and capability shutdown. Startup retains child ownership
  through registration, closes clients on every failure, spawns only for a proven local refusal,
  and rejects non-root service URLs before client or process creation. Listener tests cover
  active close, stop-entry ordering, dedupe, EOF status and 1/2/4-second reconnect backoff.
- Subtask 6: committed as `e3fd64e` after independent PASS.
  - Main-agent review of the user's partial implementation found 10 issues, all fixed with tests:
    - attachment fixtures lacked `sha256`, so 3 tests were vacuous or failing;
    - failed downloads stayed "Loading…";
    - malformed `created_at` raised in a slot;
    - file validation was duplicated;
    - the meme folder was rescanned per post;
    - GIF memes were no longer animated;
    - previews upscaled small images;
    - whitespace-only text could be posted;
    - the error status was never cleared;
    - a failed snapshot never started the live stream (it now retries with backoff).
  - Reviewer minors also fixed:
    - malformed snapshot items are filtered, and non-dict posts are ignored;
    - the file viewer decodes images against a fixed screen bound inside a scroll area;
    - the poster returns accepted/refused, so text survives a refusal;
    - `&` in chip text is escaped;
    - the unused `BoardPost` was removed;
    - two vacuous tests were strengthened, each verified by removing its guard.
  - Left as is: `bridge.build_callbacks` was already over 100 lines before this change.
  - Evidence: `pyside_gui/tests` 294 passed; the targeted board suite 209 passed; the full
    `tests` run had only the 3 known workflow-template failures, plus one
    `test_stream_preview.py` timing flake that passed on rerun.
  - The manual A5 GUI checks are still open (they need a person at the GUI).
- Subtask 7: committed as `3bd8538` after independent PASS.
  - Live browser check against an isolated board passed:
    - render, newest first, and a post made through the API appearing within about 1 s;
    - `<b>` shown as literal text;
    - an image thumbnail and a file chip;
    - no console or CSP errors;
    - no horizontal scroll at 375 px;
    - `stop` exits 0 and health goes down.
  - Reviewer minors fixed:
    - backoff resets only after the first event;
    - a 15 s timeout before response headers;
    - the dedupe test now fails without its guard;
    - the sink grep also catches `setAttribute`, `location` and `srcset`, with mutation tests;
    - CSP gains `form-action 'none'`.
  - The clean-venv install tests are opt-in with `DAGI_RUN_SLOW=1`. The wheel-contents test
    always runs.
  - `tests/message_board`: 100 passed and 2 skipped normally; 102 passed with
    `DAGI_RUN_SLOW=1`. The viewer is served through `importlib.resources` as an `HTMLResponse`
    rather than the planned `FileResponse`, because a packaged resource has no stable path.
- Subtask 8:
  - README: Message Board section, endpoint table, install and test notes.
  - TODO: done entry, multi-agent next, and follow-ups.
  - AGENTS: anaconda3 interpreter path and the board-HTTP rule.
  - `config.example.yaml`: the `services.message_board` URL.
  - Every documented command was run. The Admiral's unrelated llama.cpp README/TODO lines are
    left uncommitted.
- Final verification, 2026-10-09:
  - full `tests`: 1844 passed, 5 skipped, 3 failed (the known workflow-template tests);
  - `pyside_gui/tests`: 294 passed.
- Baseline before HTTP implementation: 1,880 passed, 7 failed, 3 skipped. Three Git tests
  failed because the temporary test directory was inside the repo; final full-suite runs
  must use outside-repo storage. Three existing workflow-template tests reference the removed
  `.dagi/skills` tree. One GUI clipboard test failed with Windows OpenClipboard unavailable.
  Sandbox TEMP also caused fixture/child-process failures, so use an isolated outside-repo
  TEMP/TMP directory with escalation for the full suite; targeted board tests can use `.dagi/temp`.
- Baseline recheck with outside-repo temporary storage: 30 passed, 4 failed across Git branch,
  workflow-template and paste-card tests. All Git tests passed. The remaining failures are the
  three removed-template references and the same Windows OpenClipboard failure.

- `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt tests pyside_gui/tests` → all pass.
- `C:\Users\alexr\anaconda3\envs\dagi\python.exe -m services.message_board --help` → usage.
- `... -m services.message_board --host 0.0.0.0` with no token → exits with the refusal message.
- `... -m services.message_board stop` with a board running → exits 0 and health is down. With
  none listening → exits 0. Foreign health/missing capability → exits 1 without signalling PIDs.
- Streaming upload boundary tests prove no receive calls after a size-limit breach.
- Clean wheel/editable install smoke checks pass; packaged viewer resolves outside the checkout.
- Closing during startup/active/queued downloads passes the lifecycle and GUI tests.
- `http://127.0.0.1:8765/` in the browser pane → posts render and update live.
- Manual GUI A5 checklist (spec §7) → all observed, including the board still running after the
  GUI closes.

## Next Action
The Admiral runs the manual A5 GUI checklist (spec §7), then decides whether to merge
`task/message-board-api` into `main`.
