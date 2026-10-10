# Board App Split Implementation Plan

**Goal:** Make the message board its own app (server + web UI where people post), and reduce
the GUI's board to a read-only view that falls back to a private, throwaway temp board when no
central board is reachable.

**Architecture:** `python message_board.py` runs the central board in the foreground and opens
the browser; the web UI gains a composer and per-browser user identity. The GUI never launches
the central board: on startup it connects to the configured URL, else spawns a GUI-owned temp
board (loopback, random port, no token, wiped on exit) and auto-switches every agent to central
as soon as it answers. All clients keep talking HTTP, so agent tools and `BoardSession` do not
change.

**Tech Stack:** Python 3.14, FastAPI + uvicorn + SQLite (board), PySide6 (GUI), vanilla JS in
one static page (web UI), pytest + qtbot, Node for the viewer harness.

## Decisions (user, 2026-10-10)

| # | Decision |
|---|---|
| S1 | Temp board: a GUI-owned private server on `127.0.0.1`, random free port, no token. Stopped when the GUI closes; never takes the central port. |
| S2 | While on temp, the GUI probes central every 30 s and auto-switches all agents when it answers, with a status note. Temp posts are not copied. |
| S3 | The GUI board tab is a read-only feed (attachment Open / Save as… kept) with a URL + `central`/`temp` badge and a Connect menu: "Switch to central" (enabled while central answers) and "Connect to another board…" (URL, then token on 401). Auto-switch still applies. The GUI composer and @ autocomplete are removed. |
| S4 | `python message_board.py` serves in the foreground and opens the default browser once `/health` answers; if a board already answers on that port it only opens the browser and exits 0; `--no-browser` disables it. |
| S5 | Web identity: a per-browser name becomes `<slug>_<uuid8>` (kind `user`, host `web`), kept in localStorage. The agent-wake cap resets on any post whose author is a `user` member. |
| S6 | Web composer: 700-char counter, Attach (≤ 4 files, ≤ 10 MB each), @ autocomplete, paste and drag-drop, and a Reply button per post. |
| S7 | Web attachment display stays as is (thumbnails, full-size overlay, Download, text preview). |
| S8 | No new clients: document the HTTP API in the README; MCP server and TUI board tools go to TODO. |
| S9 | Each GUI run gets a fresh temp folder that is deleted on exit; stale folders from crashed runs are swept on the next start. |

Assumptions accepted with the decisions: the GUI never launches the central board, so GUI-side
token generation and the GUI `user_handle` file go away; the central app keeps the v1.1 default
bind `0.0.0.0` with a required token.

## Global Constraints

- Python env `dagi`; tests: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt <paths>`
  (if that interpreter is missing use `C:\Users\alexr\anaconda3\envs\dagi\python.exe`; never `conda run`).
- Qt tests and probes must run unsandboxed; ad-hoc scripts `import pyside_gui` before any `PySide6` import.
- Post text 1..700 characters; at most 4 attachments per post, each 1 byte..10 MB.
- Handles are `<slug>_<uuid8>`, slug `[a-z0-9][a-z0-9-]{0,31}`, uuid8 = 8 lowercase hex.
- Web UI: post text, names and handles only via `textContent`/`createElement`; `src`/`href` only
  ever get blob URLs created by the page; no `innerHTML`, `outerHTML`, `insertAdjacentHTML`,
  `document.write` (the existing sink-guard test enforces this). CSP stays unchanged.
- The server still refuses a non-loopback bind without a token.
- The HTTP contract stays version 1; changes are additive only.
- Known pre-existing failures: 3 in `tests/test_workflow_plan_template.py`. No other failures allowed.
- No new runtime dependencies.

---

### Subtask 1: Server — `author_kind` on posts and `--exit-with-stdin`

**Goal:** Give clients the author's member kind on every post, and let a parent process own a
board's lifetime through a stdin pipe.

**Requirements:**
- Every post returned by `POST /posts`, `GET /posts` and `GET /stream` carries
  `author_kind: "agent" | "user"`, read from `members.kind` (join or lookup in `_post_row`).
- `serve --exit-with-stdin` starts a daemon thread that blocks on `sys.stdin.buffer.read()`;
  on EOF it sets `server.should_exit = True`. Without the flag nothing reads stdin.

**Acceptance Criteria:**
- A user member's post and an agent member's post report the right `author_kind` over REST and SSE.
- A `serve --exit-with-stdin` subprocess on port 0 exits within 5 s of its stdin being closed.

**Files:**
- Modify: `services/message_board/store.py:207-213` (`_post_row`)
- Modify: `services/message_board/__main__.py` (`parse_args`, `serve_board`)
- Test: `tests/message_board/test_store.py`, `tests/message_board/test_api.py`,
  `tests/message_board/test_service_process.py`

#### Tests
- `test_store.py::test_post_carries_author_kind` — a user and an agent post; kinds match.
- `test_api.py::test_posts_and_stream_include_author_kind` — REST list and SSE backlog include it.
- `test_service_process.py::test_exit_with_stdin_stops_on_eof` — spawn with `stdin=PIPE`, wait for
  `/health` (read the port from the runtime record), close stdin, process exits ≤ 5 s.

- [x] **Step 1:** Write the three failing tests.
- [x] **Step 2:** Run them; expect KeyError `author_kind` and a timeout on exit.
- [x] **Step 3:** Implement:

```python
# store.py, inside _post_row
kind = self._conn.execute("SELECT kind FROM members WHERE handle=?",
                          (post["author"],)).fetchone()
post["author_kind"] = kind["kind"] if kind else "agent"

# __main__.py
serve.add_argument("--exit-with-stdin", action="store_true",
                   help="stop when stdin reaches EOF (used by a parent that owns this board)")
...
if args.exit_with_stdin:
    def _watch() -> None:
        try:
            sys.stdin.buffer.read()
        finally:
            server.should_exit = True
    threading.Thread(target=_watch, daemon=True, name="stdin-watch").start()
```

- [x] **Step 4:** Run `tests/message_board`; focused store/API tests and the live EOF test pass.
- [x] **Step 5:** Return for review.

---

### Subtask 2: Board app launcher (S4)

**Goal:** `python message_board.py` is the central board app: serve in the foreground and open
the web UI.

**Requirements:**
- `main(argv=None, *, open_browser=False, opener=webbrowser.open, probe=<health check>)`;
  `message_board.py` calls `main(open_browser=True)`. `python -m services.message_board` keeps
  `open_browser=False`, so the GUI's temp spawn never opens a browser.
- `serve --no-browser` overrides `open_browser`.
- With `open_browser`, before binding: if `GET http://127.0.0.1:<port>/health` (the
  `local_url` of `--host`) answers as a v1 board, print `message board already running at <url>`,
  open the browser and return 0 without serving.
- Otherwise serve; a daemon thread polls `/health` (≤ 10 s, 0.25 s steps) and opens the browser
  once it answers. The browser URL is the loopback URL of the bind.
- Print the LAN hint once on a non-loopback bind: `LAN: http://<hostname>:<port>/ (token in <path>)`.
  Never print the token.
- Ctrl+C or closing the console stops the board (existing uvicorn behaviour).

**Acceptance Criteria:**
- With a fake healthy probe, `main(["--port", "9"], open_browser=True, opener=f)` calls `f` once
  with `http://127.0.0.1:9/` and returns 0 without creating a store.
- With `--no-browser`, `opener` is never called.
- `python -m services.message_board` (no `open_browser`) never calls `opener`.

**Files:**
- Modify: `services/message_board/__main__.py`, `message_board.py`
- Test: `tests/message_board/test_entry.py`

#### Tests
- `test_entry.py::test_running_board_only_opens_browser`
- `test_entry.py::test_no_browser_flag_skips_opener`
- `test_entry.py::test_module_entry_never_opens_browser`
- `test_entry.py::test_browser_opens_after_health_answers` — fake serve + probe that answers on
  the 2nd poll; opener called once with the loopback URL.

- [x] **Step 1:** Write the failing tests (inject `serve` and `probe` so no real server runs).
- [x] **Step 2:** Run; expect TypeError on the new keyword arguments.
- [x] **Step 3:** Implement the flags, the pre-check and the opener thread.
- [x] **Step 4:** Run `tests/message_board/test_entry.py`; all pass.
- [x] **Step 5:** Return for review.

---

### Subtask 3: Qt-free temp board runtime (S1, S9)

**Goal:** Replace the detached fallback with a GUI-owned temp board in `pyside_gui/board_runtime.py`.

**Requirements:**
- New `TempBoard`:
  - `TempBoard.start(root=STATE_DIR / "temp", *, spawn=..., wait_s=10.0, cancel=None)` takes an
    exclusive root lifecycle lock, sweeps stale runs, creates `<root>/<uuid8>/`, opens
    `owner.lock` in it and takes an exclusive non-blocking lock, then releases the root lock.
    Promote or extend `services.message_board.runtime_records._lock_file` rather than adding a
    second platform-lock implementation. The root lock makes sweep + create atomic with respect
    to another GUI start, so a sweeper cannot delete a new run before its owner lock is held.
  - Spawn the service on an OS-assigned port with
    `[sys.executable, "-m", "services.message_board", "serve", "--host", "127.0.0.1",
    "--port", "0", "--db", <run>/board.sqlite3, "--runtime-dir", <run>/run,
    "--exit-with-stdin"]`
    with `stdin=PIPE`, `cwd=DAGI_ROOT`, output to `<run>/board.log`, `CREATE_NO_WINDOW` on
    Windows (not `DETACHED_PROCESS`).
  - Poll the run's unique runtime directory for the existing protected `board-<port>.json`
    record, validate/read it through `runtime_records`, then wait for health at its recorded URL.
    This reuses `RecordServer`'s actual bound port and has no reserve-port race or retry path.
    If the child exits or readiness times out, raise `BoardError("SPAWN_FAILED", ...)` after
    cleanup.
  - `url` property returns `http://127.0.0.1:<P>`.
  - `close()` is idempotent: close stdin, wait ≤ 5 s, else `terminate()` then `kill()`; release
    and close the lock; `shutil.rmtree(run, ignore_errors=True)`.
- `sweep_stale(root)`: for each subfolder, try to lock its `owner.lock`. If the lock is acquired
  (owner gone), unlock and `rmtree`. If it is locked, leave it (another GUI is running).
  `TempBoard.start` calls it while holding the root lifecycle lock. Missing/incomplete run state
  is removed only while that same root lock proves no other start is constructing it.
- `start_board(url, token, *, state_dir, temp_factory=TempBoard.start, ...)`:
  - reachable (with the existing one retry) → runtime on `url`, `temp=None`, `central_url=None`;
  - unreachable twice → `temp_factory(...)`, client on `temp.url` with **no token**,
    `runtime.temp = temp`, `runtime.url = temp.url`, `runtime.central_url = url`, **always**
    (including loopback central URLs);
  - auth failure / NOT_A_BOARD → raise, no temp;
  - on any failure after the temp started, `temp.close()`.
- `register_runtime` registers only the main agent handle (`main_handle` file kept). Remove
  `user_handle` and `spawned_pid` from `BoardRuntime`, plus `load_or_create_user_handle`,
  `SpawnedService`, `spawn_service`, `_Launch`, `_spawn_local` and the `ensure_token` import.
  `BoardRuntime` gains `temp: TempBoard | None = None`.
- Remove `check_user_file` / `validate_user_files` (only the GUI composer used them; done in
  Subtask 5 together with their tests if the controller still imports them).

**Acceptance Criteria:**
- Unit (fakes): reachable; unreachable then reachable on retry; unreachable twice → temp started,
  client built with `token=None` and the temp URL, `central_url == url` for both a loopback and
  a LAN URL; 401 → raises, temp factory never called; cancelled → no temp.
- Live process: `TempBoard.start` serves `/health`; after `close()` the process has exited and
  its URL uses the OS-assigned port from the protected runtime record; after `close()` the
  process has exited and the run folder is gone.
- Orphan safety: closing the parent's stdin end (simulated GUI crash) stops the child ≤ 5 s.
- `sweep_stale` removes an unlocked folder and keeps a folder whose lock is held.

**Files:**
- Modify: `pyside_gui/board_runtime.py`
- Modify: `services/message_board/runtime_records.py` (public/non-blocking lock support and
  protected runtime-record discovery for the unique temp run directory)
- Test: `tests/test_board_runtime.py` (rewrite the spawn/detach tests at lines 168-335 and
  492-560; keep the SSE/listener tests)

#### Tests
- `test_unreachable_twice_starts_temp_board_without_token` (parametrized loopback / LAN URL)
- `test_retry_success_does_not_start_temp`
- `test_auth_failure_never_starts_temp`
- `test_failure_after_temp_start_closes_temp`
- `test_temp_board_lifecycle_live` — start, health, close, folder removed, process gone
- `test_temp_board_uses_runtime_record_port` — the child receives port 0 and the returned URL
  uses the actual port securely published by `RecordServer`
- `test_temp_board_exits_when_parent_pipe_closes`
- `test_sweep_stale_removes_only_unlocked_runs`
- `test_concurrent_start_cannot_sweep_new_owned_run`

- [x] **Step 1:** Write the failing tests; delete the obsolete detached-spawn and user-handle tests.
- [x] **Step 2:** Run `tests/test_board_runtime.py`; expect failures on the missing `TempBoard` and `temp`.
- [x] **Step 3:** Implement `TempBoard`, `sweep_stale` and the new `start_board`; delete the dead code.
- [x] **Step 4:** Run `tests/test_board_runtime.py tests/message_board`; all pass.
- [x] **Step 5:** Return for review.

---

### Subtask 4: BoardController — auto-switch, temp ownership, kind-based wake (S2, S5)

**Goal:** The controller treats temp as a stopgap: it probes central, switches automatically,
stops the temp board when it leaves it, and wakes agents based on `author_kind`.

**Requirements:**
- `_central_timer` runs whenever `runtime.temp` is set. `_on_central_state(url, reachable)`:
  - updates the view's "Switch to central" menu action (enabled iff reachable);
  - if reachable and no switch is in flight, calls `switch(url)` with the resolved token
    (`resolve_token()`; the central board may need one). On UNAUTHORIZED it asks for the token
    once (existing `ask_token`), stops auto-switching for that URL until the user connects
    manually, and keeps the temp board.
- `_on_switched` success: after retiring the old listener and client, if the old runtime had a
  `temp`, call `temp.close()` in the retire thread (after `listener.join()`). Status:
  `Switched to central board <url>; temp board posts were discarded.`
- A manual "Connect to another board…" while on temp behaves the same (temp retired on success).
- `close()` → `_cleanup` closes `runtime.temp` after the listener joins and workers are idle.
  Late readiness after close closes the result's temp too (`_close_result`).
- Remove the user-posting path: `post`, `_post_result`, `_on_post_result`, `_on_status_error`,
  the `_error_shown` flag, the `validate_user_files` import and `view.set_poster`.
- Remove GUI autocomplete plumbing: `_members_loaded`, `_on_members`, `refresh_mentions`,
  `_known_handles`, the members fetch in `_load_snapshot`; drop the `refresh_mentions` call in
  `AgentsController.refresh` and `add_session`/`remove_session`.
- Mention wake: `BoardController._on_post` calls `window._on_board_mention(post)`;
  `AgentsController.on_board_mention(post)` uses `from_user = post.get("author_kind") == "user"`
  (missing → agent, so the cap still applies). Update `app.py:_on_board_mention`'s signature.

**Acceptance Criteria:**
- On temp, a reachable probe switches every `BoardSession` to central without user action, and
  the temp's `close()` is called exactly once, after the old listener stops.
- An UNAUTHORIZED probe → token prompt once, no switch loop, temp kept.
- Closing the window while on temp closes the temp board.
- A live mention from an `author_kind: "user"` post resets `agent_wakes` and wakes the agent; five
  `agent` mentions in a row cap it; a sixth from a user is delivered.
- No reference to `user_handle`, `post(`, `set_poster` or `refresh_mentions` remains in
  `pyside_gui/` (outside `archive/`).

**Files:**
- Modify: `pyside_gui/board_controller.py`, `pyside_gui/agents_controller.py:106-150`,
  `pyside_gui/app.py:246-250`
- Test: `pyside_gui/tests/test_board_controller.py`, `pyside_gui/tests/test_board_mentions.py`,
  `pyside_gui/tests/test_agents.py`

#### Tests
- `test_central_back_auto_switches_and_closes_temp`
- `test_central_auth_failure_asks_token_once_and_keeps_temp`
- `test_close_on_temp_closes_temp_board`
- `test_user_kind_mention_resets_wake_cap` (replace the `user_handle=` based test)
- Delete: the `test_post_*` tests and `test_central_probe_offers_switch_only_when_reachable`
  (replaced by the auto-switch test).

- [x] **Step 1:** Write and adjust the failing tests (fake runtime with a `temp` that records `close` calls).
- [x] **Step 2:** Run them (unsandboxed); expect failures.
- [x] **Step 3:** Implement the controller, agents-controller and app changes.
- [x] **Step 4:** Run `pyside_gui/tests/test_board_controller.py test_board_mentions.py test_agents.py`; all pass.
- [x] **Step 5:** Return for review.

---

### Subtask 5: Read-only GUI board view with Connect menu (S3)

**Goal:** `MessageBoardView` becomes a read-only feed with a `central`/`temp` badge and a
Connect menu.

**Requirements:**
- Remove `_build_composer`, the chips, `_choose_files`, `_send`, `_update_count`,
  `set_poster`, `set_mention_candidates`, and the `_central_back` banner. Delete
  `pyside_gui/sidebars/board_composer.py` and its tests in `test_board_mentions.py` (keep that
  file's wake tests). Remove `check_user_file`/`validate_user_files` and
  `tests/test_board_gui_helpers.py`'s tests for them (keep `should_render_inline` tests).
- `set_connection(url, central_url)`: the badge reads `temp` (amber, tooltip
  `Temporary board — <central_url> is unreachable; posts here are discarded when DAGI closes`)
  when `central_url` is set, else `central` (neutral).
- The Connect `QToolButton` uses `InstantPopup` with a `QMenu`:
  - `Switch to central (<url>)`, visible while on temp and enabled only when
    `set_central_available(url, True)`; emits `connect_requested(url, None)`;
  - `Connect to another board…`, the existing URL dialog → `connect_requested(url, None)`;
    401 → existing `ask_token`.
- Attachment cards keep Open and Save as….
- The panel width rule from v1.1 (80 px wider than the right sidebar) is unchanged.

**Acceptance Criteria:**
- The view has no editable input or Send button (`findChildren(QPlainTextEdit)` empty, no "Send" button).
- On temp, the menu's switch action is disabled until `set_central_available(url, True)`;
  triggering it emits `connect_requested(url, None)`.
- The badge text is `temp` with a central URL and `central` without one.
- Existing card, download and Save as… tests still pass.

**Files:**
- Modify: `pyside_gui/sidebars/message_board.py`, `pyside_gui/board_runtime.py` (remove the file validators)
- Delete: `pyside_gui/sidebars/board_composer.py`
- Test: `pyside_gui/tests/test_message_board.py`, `pyside_gui/tests/test_board_mentions.py`,
  `pyside_gui/tests/test_board_controller.py:446-470`, `tests/test_board_gui_helpers.py`

#### Tests
- `test_board_view_is_read_only`
- `test_connect_menu_switch_action_follows_central_availability`
- `test_badge_shows_temp_or_central`

- [ ] **Step 1:** Write the failing tests; delete the composer tests.
- [ ] **Step 2:** Run them (unsandboxed); expect failures.
- [ ] **Step 3:** Implement the view changes and wire `BoardController._on_central_state` to `set_central_available`.
- [ ] **Step 4:** Run the four test files plus `pyside_gui/tests/test_left_sidebar.py`; all pass.
- [ ] **Step 5:** Return for review.

---

### Subtask 6: Web UI composer and identity (S5, S6, S7)

**Goal:** People post to the central board from the web UI with attachments, mentions and replies.

**Requirements:**
- `api(path, signal, init)` accepts method and body and keeps the bearer header. Add a structured
  `ApiError` carrying HTTP `status`, server `code` and the server's safe `error` message;
  specialize or branch on 401 for the existing token prompt. This is the single error path used
  by identity registration, uploads, posts and reads, and makes `HANDLE_TAKEN` detectable.
- Identity: on the first send (or a "Set name" link), prompt for a name with an inline form (not
  `window.prompt`). Normalize it to a slug (lowercase, `[^a-z0-9-]` → `-`, trim leading `-`, ≤ 32,
  must match the slug rule), form `<slug>_<8 hex from crypto.getRandomValues>`, then
  `POST /members {handle, kind: "user", host: "web"}`. Store it in localStorage `dagiBoardUser`
  inside try/catch, with an in-memory fallback. Show `posting as <handle>` with a "change"
  link. On 409 HANDLE_TAKEN, generate a new uuid8 and retry once.
- Composer below the status bar: a `<textarea>` with a live `n/700` counter (Send disabled over
  700 or when `text.trim()` is empty, regardless of attachments, matching the server's required
  1..700 text contract); Enter sends, Shift+Enter inserts a newline.
- Attach: hidden `<input type=file multiple>` behind an Attach button. Files appear as chips
  with a remove ×. Refuse a 5th file or a file of 0 bytes or over 10 MB with an inline message.
- Paste: `paste` on the textarea adds `clipboardData.files`. Drag-drop: `dragover`/`drop` on the
  page add `dataTransfer.files`, with the same limits and a drop highlight.
- @ autocomplete: typing `@` + prefix shows a list of handles from `GET /members` (fetched on
  connect and refreshed when a post from an unknown author arrives), filtered by prefix and
  capped at 8; arrow keys, Enter/Tab accept, Esc closes.
- Reply: each post gets a Reply button that sets `reply_to` (shown as `↩ #id ×` above the
  textarea) and inserts `@<author> ` if it is not already there.
- Send: require non-whitespace text, upload each file (`FormData` with `file` and `uploader`) to `POST /attachments`, then
  `POST /posts {author, text, attachments, reply_to}`. On success, clear the composer; the post
  arrives through the stream (no optimistic insert). On error, keep the input and show the
  structured `ApiError`'s server message. The composer is disabled while the page is not live
  (`body[data-live="0"]`) and during a send.
- Update the header comment ("Read-only viewer" → viewer and composer; same sink rules).
- Attachment rendering is unchanged (S7).

**Acceptance Criteria:**
- Harness `compose` mode: first send registers a `user` member with host `web`, uploads 2 files
  (one pasted), then posts with both ids and `reply_to`; a 701-char text and a 5th file are
  refused without requests; whitespace-only text with attachments is also refused without
  requests; @ autocomplete inserts a handle; `HANDLE_TAKEN` regenerates the suffix and retries
  once; the composer is disabled during an outage.
- `test_page_has_no_html_injection_sinks` still passes; the page stays under the size cap in
  `test_page_is_self_contained_and_small` (raise the cap only if needed, and say so in review).
- API test: a `user`-kind uploader can upload and post; an agent's `fetch_attachment` can fetch
  a user-uploaded file.

**Files:**
- Modify: `services/message_board/static/index.html`
- Modify: `tests/message_board/viewer_harness.js` (POST/FormData fakes, clipboard and drop events, `compose` mode)
- Test: `tests/message_board/test_viewer.py`, `tests/message_board/test_api.py`

#### Tests
- `test_viewer.py::test_compose_registers_uploads_and_posts`
- `test_viewer.py::test_compose_limits_refuse_without_requests`
- `test_viewer.py::test_identity_collision_retries_with_new_suffix`
- `test_viewer.py::test_mention_autocomplete_and_reply`
- `test_api.py::test_user_member_attachment_is_fetchable_by_agent`

- [ ] **Step 1:** Extend the harness and write the failing tests.
- [ ] **Step 2:** Run `tests/message_board/test_viewer.py`; expect failures.
- [ ] **Step 3:** Implement the composer, identity, paste/drop, autocomplete and reply.
- [ ] **Step 4:** Run `tests/message_board`; all pass.
- [ ] **Step 5:** Return for review.

---

### Subtask 7: Docs and config

**Goal:** Docs match the split.

**Requirements:**
- README: a "Message board app" section (launch, browser, `--no-browser`, `stop`, token and LAN,
  firewall prompt); a GUI section (temp board, auto-switch, Connect menu, read-only view); an
  "HTTP API for other harnesses" section (endpoints, auth header, post/attachment records
  including `author_kind`, SSE format, handle rules, `after` cursor and dedupe by id).
- `config.example.yaml` and `.dagi/config.yaml` comments: `url` is the central board; `bind`
  is used only by `python message_board.py`; the GUI falls back to a private temp board.
- TODO: add the MCP board server and TUI/headless board tools; remove items made obsolete
  (posts on a fallback board are not copied → "temp posts are discarded by design"); keep the
  others.
- AGENTS.md: only if a per-turn fact changed (likely none).
- `wiki-add`: the decision (temp board is GUI-owned and throwaway; the GUI never launches
  central) and the gotcha (stdin-EOF ownership instead of a detached process).

**Acceptance Criteria:** `rg -n "fallback|user_handle|Central board is back" README.md config.example.yaml pyside_gui`
shows no stale statements.

**Files:** `README.md`, `config.example.yaml`, `.dagi/config.yaml`, `TODO.md`, `wiki/`

- [ ] **Step 1:** Edit the docs.
- [ ] **Step 2:** Return for review.

---

## Workspace
- **Branch:** `task/board-app-split`
- **Parent:** `main`
- **Starting commit:** `d2599843`
- **Task folder:** `wiki/tasks/2026-10-10_board-app-split/`

## Overall Status
In Progress — Subtasks 1-4 passed review; Subtask 5 is next.

## Notes
- Subtask 1 review: PASS. `test_store.py` + `test_api.py`: 49 passed; live
  `test_exit_with_stdin_stops_on_eof`: 1 passed in 1.01 s. The `dagi` environment on this host
  lacks `sqlite3.dll`; the live test used a temporary, uncommitted DLL-search bootstrap pointing
  at the existing `ai2` environment's DLL, then removed it. No runtime workaround was added.
- Subtask 2 review: PASS after keying browser readiness to this server's validated instance ID,
  disabling proxy inheritance for loopback probes, and covering LAN hint secrecy. Entry +
  lifecycle suites: 46 passed (one existing Starlette deprecation warning) in 2.74 s.
- Subtask 3 review: PASS after hardening partial-start cleanup and UUID-collision ownership.
  Runtime + message-board suites: 157 passed, 2 skipped (one existing warning) in 26.24 s,
  including all three unsandboxed live ownership/concurrency tests.
- Subtask 4 review: PASS after serializing and tagging switch attempts so overlapping manual and
  automatic completions cannot double-prompt or replace newer state. Planned Qt suites: 37 passed
  unsandboxed in 3.09 s.
- Today the fallback launches **detached on the central port** and binds `0.0.0.0`
  (`board_runtime.py:292-341`). For a loopback central URL it also leaves `central_url=None`, so
  the GUI never probes for central. Both go away in Subtask 3.
- `BoardSession.rebind` already resets the read cursors, so temp → central needs no cursor work.
- Mentions are only "live" above `_live_after`, which is set after each snapshot, so a switch
  never replays old mentions as wakes.
- Parent-owned lifetime uses the stdin pipe: Python creates the parent end non-inheritable, so
  agent tool subprocesses cannot keep the temp board alive.
- Temp boards pass port 0 to uvicorn and learn the actual bound port from `RecordServer`'s
  protected runtime record; do not reintroduce a bind-close-respawn port reservation race.
- The temp root lifecycle lock must cover both stale sweeping and creation/locking of the new
  run folder so concurrent GUI starts cannot sweep one another's partially created state.
- `psutil` is dev-only, so stale-run detection uses the lock file, not a PID check.
- Agents' attachment caches (`<cwd>/.dagi/board/attachments/<id>/`) are unaffected by the temp
  wipe; ids differ between boards, so there are no collisions.

## Open Issues
None.

## Attempts and Resolutions
(none yet)

## Verification
- Full suite: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt tests pyside_gui/tests`
  (unsandboxed); only the 3 known plan-template failures.
- Sink guard: `rg -n "innerHTML|outerHTML|insertAdjacentHTML|document\.write" services/message_board/static/index.html` → nothing.
- Manual (Admiral):
  1. `python message_board.py` → the browser opens; set a name, post text, paste an image,
     attach a file, reply, @mention `main_…`; the GUI's main agent wakes.
  2. Run it again while it is up → only the browser opens.
  3. Stop the board, start the GUI → `temp` badge; an agent posts; restart the board →
     the GUI auto-switches within 30 s and the temp folder is gone after the GUI closes.
  4. Kill the GUI from Task Manager while on temp → the temp board process exits; the next
     GUI start sweeps the folder.

## Next Action
Implement and review Subtask 5: the read-only GUI board view and Connect menu.
