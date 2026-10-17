# Model-spawned GUI agents Implementation Plan

**Goal:** Let the main GUI agent spawn steerable, visible peer agents with a `spawn_agent` tool. A peer
gets its task on the message board and reports its `write_handoff` back to `@main` on the board.

**Architecture:** `spawn_agent` is a frontend tool. It is registered only when
`AgentCallbacks.spawn_agent` is set, and only the PySide main session sets it. The tool runs on the main agent's worker
thread. It asks the GUI thread (through a `Future`) to create the peer `AgentSession` through
`AgentsController`. Then, on the worker thread, it registers the peer on the board **synchronously**
and posts `@<peer> [task] ...`. The existing `on_board_mention` path wakes the peer. When a peer's
turn ends, the GUI posts `@<spawner> [done|max-continuations|error] ...` from the
peer's board identity, with the full handoff attached, and closes the peer if
`close_on_done` is true. Typed subprocess subagents do not change.

**Tech Stack:** Python 3.13, PySide6 (Qt signals, `QMetaObject.invokeMethod`), httpx board client,
FastAPI board service (tests only), pytest + local `qtbot` (`pyside_gui/tests/conftest.py`).

## Global Constraints

- Decisions D1–D13 (Admiral, 2026-10-17) are binding:
  - D1: coexist. `spawn_agent` exists only in the PySide GUI. Typed subagents, the TUI, Telegram and headless runs do not change.
  - D2: `spawn_agent(slug, task, close_on_done=False)` returns the peer handle at once (async).
  - D3: `close_on_done` default `False`.
  - D4: completion = the peer calls `write_handoff`. The existing `AgentLoop` continuation enforces this (`agent/loop.py:932`). Do not add a footer or a nudge.
  - D5: a turn that ends without a handoff posts `[max-continuations|error]`, and the peer stays open even if `close_on_done` is true.
  - D14 (Admiral, 2026-10-17): **ESC only pauses.** ESC on any agent (main or peer) never posts to the board, never wakes another agent and never closes anything. Only user-facing displays may be added. The Admiral is present and decides what happens next.
  - D6: only the main agent gets `spawn_agent`. Peers never get it.
  - D7: the peer copies the main agent's model, working folder and tools. There are no override parameters.
  - D8: no `close_agent` / `list_agents` tools.
  - D9: new board tool lists **online** members only (no state field, no board schema change).
  - D10: ESC on the main agent does not stop peers. It shows one chat line that lists this session's peers that are `running` or `waiting`.
  - D11: config `max_spawned_agents` (default 4), counting only model-spawned peers. At the limit, close the LRU (`last_active`) idle peer whose last outcome was `done`. If none is eligible, return an error that lists active peers and states.
  - D12: result = `@<spawner> [done] <≤500-char head>` + full handoff attached as `handoff_<handle>.md`.
  - D13: task = `@<peer> [task] <text>` from the spawner. If the post text is longer than 700 chars, attach the full task as `task.md`.
- Board post text limit: 700 characters (`services/message_board/store.py:25`). Max 4 attachments.
- No change to the board server, its schema or its HTTP API.
- Fail loud: every failure path returns an actionable error string to the model. No exception is swallowed without a log or an error message.
- Qt objects are created and touched only on the GUI thread. Network calls never run on the GUI thread.
- Test command (from AGENTS.md): `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt <paths>`. Qt tests must run unsandboxed.
- Match surrounding style: short docstrings, `from __future__ import annotations`, no new dependencies.

---

### Subtask 1: `max_spawned_agents` config key ✅ (`26b9702d`)

**Goal:** Load and validate a positive-int `max_spawned_agents` (default 4) on `AgentConfig`.
**Requirements:**
- `AgentConfig.max_spawned_agents: int = 4` (`agent/_loop_config.py`, next to `max_continuations`).
- `agent/config_loader.py` reads `raw.get("max_spawned_agents", 4)` as an int and passes it into `AgentConfig`, the same as `max_continuations` (`:297`, `:352`).
- `agent/config_validate.py` `_POSITIVE_INT_KEYS` includes `"max_spawned_agents"`.
- `config.example.yaml` documents it next to `max_continuations` (GUI only, model-spawned peers only, eviction rule).
**Acceptance Criteria:**
- With no key, the loaded config has `max_spawned_agents == 4`. With `max_spawned_agents: 2`, it is 2.
- Validation rejects `0` and `-1` the same way as `max_continuations`.
- `tests/test_config_editor.py:746` key list is updated, and the existing config tests pass.

**Files:**
- Modify: `agent/_loop_config.py:69`, `agent/config_loader.py:297,352`, `agent/config_validate.py:76-78`, `config.example.yaml:54`
- Test: `tests/test_config_editor.py:746`, `tests/test_spawn_agent_config.py` (create)

#### Tests
- `tests/test_spawn_agent_config.py` — the default is 4, an override is loaded, and validation rejects a non-positive value.

- [ ] **Step 1: Write the failing tests.** Load the config with the same helper that the existing `max_continuations` loader tests use (find it with `grep -rn "max_continuations" tests/`). Assert the default and the override. Call the validator on `{"max_spawned_agents": 0}` and assert one error.
- [ ] **Step 2: Run** `...pytest -q -p no:pytest-qt tests/test_spawn_agent_config.py`. Expected: FAIL (`AttributeError: max_spawned_agents`).
- [ ] **Step 3: Implement** the field, loader line, validator key, example yaml lines and the editor-test list entry.
- [ ] **Step 4: Run** `tests/test_spawn_agent_config.py tests/test_config_editor.py`. Expected: PASS.
- [ ] **Step 5: Return for review.**

---

### Subtask 2: `board_members` tool (D9) ✅ (`d466ca8b`)

**Goal:** Let any board-connected agent list online board members.
**Requirements:**
- `BoardMembersTool` in `tools/board/_board.py`. `name = "board_members"`. It has no parameters.
- Description: "List the handles of members online on the message board now. Use a full handle to @mention one. Presence lags by up to about 30 seconds."
- `run()` uses the existing `_online(session)`. It returns `You are <me>. Online members: <h1 (you)>, <h2>, …` with **all** handles (no `_MAX_LISTED` cut). If `_online` returns `None`, it returns `Error: the message board is not reachable right now.`
- Export it from `tools/board/__init__.py`. Register it in `agent/tools.py` `_register_frontend_tools` next to `ReadBoardTool`, when `callbacks.board is not None`.
**Acceptance Criteria:**
- With members A (you), W online and X offline, the output lists A and W, and not X.
- Banned members are not listed (the existing `_online` behavior).
- A registry built with `AgentCallbacks(board=object())` contains `board_members`. A registry with `board=None` does not.

**Files:**
- Modify: `tools/board/_board.py`, `tools/board/__init__.py`, `agent/tools.py:209-215`
- Test: `tests/test_board_tools.py`

#### Tests
- `test_board_members_lists_online_handles_only` — uses the `tools` fixture (real board app). It registers W, and asserts the exact output string.
- `test_board_members_reports_unreachable_board` — the session client `members()` raises `BoardError`, and the tool returns the error line.
- `test_registry_registers_board_members_only_with_a_board`.

- [ ] **Step 1: Write the three failing tests** in `tests/test_board_tools.py`. Add `members=BoardMembersTool(session=session)` to the fixture namespace.
- [ ] **Step 2: Run** `tests/test_board_tools.py -k board_members`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the tool and its registration.
- [ ] **Step 4: Run** `tests/test_board_tools.py`. Expected: PASS (all tests, including the old ones).
- [ ] **Step 5: Return for review.**

---

### Subtask 3: `spawn_agent` tool and callback seam (D1, D2, D3, D6) ✅ (`89bbbd6a`)

**Goal:** Add a frontend-gated `spawn_agent` tool that forwards to `AgentCallbacks.spawn_agent`.
**Requirements:**
- `agent/_loop_config.py` `AgentCallbacks`: new field
  `spawn_agent: "Callable[[str, str, bool], str] | None" = None`, with the comment "GUI main agent only: (slug, task, close_on_done) -> result text".
- New package `tools/spawn_agent/` (`__init__.py`, `_spawn_agent.py`). It follows the layout of `tools/write_handoff/`.
- `SpawnAgentTool(BaseTool)`, `name = "spawn_agent"`. Parameters: `slug` (string, required), `task` (string, required, min 1 char), `close_on_done` (boolean, default false).
- The description makes the routing choice clear (the "weak" item in the grill summary): *"Start a peer agent in its own GUI chat. It is visible in the Agents view, the Admiral can steer it, and it can ask the Admiral questions. It gets your model, folder and tools. The call returns at once with its handle. The peer's result arrives later as a board message to you, `[done]` with the handoff attached, or `[max-continuations|error]`. Use typed subagents instead for short, isolated jobs that must return a result in this turn. Follow up with post_board @<handle>."*
- `run()` checks the types (`ValueError` on a wrong type), strips `task`, and returns `self._spawn(slug, task, close_on_done)` without changes.
- `agent/tools.py` `_register_frontend_tools`: register `SpawnAgentTool(spawn=callbacks.spawn_agent)` only when `callbacks.spawn_agent is not None`.
- Subagent pipe callbacks (`tools/subagent_main.py` `_build_pipe_callbacks`) and the TUI never set the field, so D1/D6 hold by construction. Do not edit them.
**Acceptance Criteria:**
- A registry with `AgentCallbacks()` has no `spawn_agent`. With `AgentCallbacks(spawn_agent=fn)`, it has the tool, and `run("fixer", " do x ", True)` calls `fn("fixer", "do x", True)` and returns its text.
- `run(slug=1, task="x")` raises `ValueError`.

**Files:**
- Create: `tools/spawn_agent/__init__.py`, `tools/spawn_agent/_spawn_agent.py`
- Modify: `agent/_loop_config.py:213`, `agent/tools.py:203-219`
- Test: `tests/test_spawn_agent_tool.py` (create)

#### Tests
- `test_spawn_agent_absent_without_callback`, `test_spawn_agent_forwards_stripped_task`, `test_spawn_agent_rejects_bad_types`.
- `test_tool_order_unchanged_for_existing_tools`: assert that the names before `spawn_agent` in `reg` keep their old relative order (see [[tool-registration-order-is-schema-order]]). Register `spawn_agent` **after** `show_file`.

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run** `tests/test_spawn_agent_tool.py`. Expected: FAIL (ImportError).
- [ ] **Step 3: Implement** the field, the tool and its registration.
- [ ] **Step 4: Run** `tests/test_spawn_agent_tool.py tests/test_board_tools.py`. Expected: PASS.
- [ ] **Step 5: Return for review.**

---

### Subtask 4: Pure peer helpers ✅ (`402705fd`)

**Goal:** Keep the text formats and the selection rules in one Qt-free module, so that they are easy to test.
**Requirements:** Create `pyside_gui/peers.py` with:
- `MAX_POST = 700`, `HEAD = 500`.
- `task_post(peer: str, task: str) -> tuple[str, bool]`. It returns `(text, attach)`. `text = f"@{peer} [task] {task}"` if it fits in 700 chars, else `f"@{peer} [task] {task[:HEAD]}… (full task in task.md)"` with `attach=True`.
- `report_post(spawner: str, tag: str, body: str) -> str`. It returns `f"@{spawner} [{tag}] {head}"`. `head` is `body` cut to fit 700 chars in total (cut to `HEAD` with `…`). An empty body becomes `(no text)`. `tag` is one of `done`, `max-continuations`, `error`. Any other value raises `ValueError`.
- `pick_eviction(peers) -> object | None`. `peers` are objects with `.state` (from `agent_state`), `.last_outcome` and `.last_active` (float). It returns the eligible peer with the smallest `last_active`. Eligible means `state == "idle" and last_outcome == "done"` (D11/Q14).
- `limit_error(peers, limit) -> str`. Output: `Error: {limit} spawned agents are open and none can be closed: fixer_ab12 (running), docs_9f3e (waiting), … Wait for a [done] message, close one in the Agents view, or post a follow-up to an idle one.`
- `active_notice(peers) -> str | None`. For peers with state `running` or `waiting` (in that order: spawn order), it returns `⏹ Stopped. Peers still active: h1 (running), h2 (waiting for you). See the Agents view.` If there is no such peer, it returns `None`.
**Acceptance Criteria:** All tests below pass. The module imports no Qt.

**Files:**
- Create: `pyside_gui/peers.py`
- Test: `tests/test_peers.py` (create, no Qt)

#### Tests
- `task_post`: a short task (no attach), a 699/700/701-char boundary, a long task (`attach=True`, text ≤700).
- `report_post`: each tag, body cut to ≤700 total, an empty body, an invalid tag raises.
- `pick_eviction`: LRU among the eligible ones; skips `error`/`max-continuations` outcomes and peers that are paused (`state == "paused"`); skips running/waiting peers; `None` when none is eligible.
- `limit_error` and `active_notice`: exact strings; `None` when every peer is idle.

- [ ] **Step 1–4: TDD** with `tests/test_peers.py`.
- [ ] **Step 5: Return for review.**

---

### Subtask 5: Peer state on `AgentSession` and `AgentsController.spawn_peer` (D7, D11) ✅ (`8eb197d0`)

**Goal:** Create model-spawned peers on the GUI thread, with limit and eviction.
**Requirements:**
- `AgentSession.__init__` (and `pyside_gui/tests/session_stub.py` `StubSession`) get:
  `spawned_by: str | None = None`, `close_on_done = False`, `last_active = time.monotonic()`,
  `last_outcome: str | None = None`, `_turn_handoff: str | None = None`, `_turn_done_seen = False`.
- `AgentsController.spawn(slug)` is split. The body becomes `_create(slug) -> session | str` (an error string). `spawn(slug)` keeps its current user behavior and calls `win._activate(session)`. **A model spawn does not activate the peer**, because the Admiral's view must not jump.
- `AgentsController.spawn_peer(slug, close_on_done, spawner) -> AgentSession | str` (GUI thread):
  1. If `win._main._board_session is None`, return `Error: the message board is offline, so a peer cannot get its task. Try again when the board is connected.`
  2. `peers = [s for s in win._sessions if s.spawned_by is not None]`. If `len(peers) >= limit` (`win._main._config.max_spawned_agents`): `victim = pick_eviction(...)`. If `None`, return `limit_error(...)`. Else call `self.close_agent(victim.handle)` (the existing `_retired` path), and add a line to the main conversation: `Closed idle peer <h> to make room (max_spawned_agents=<n>).`
  3. `_create(slug)`. On an error string, return it with the prefix `Error: `.
  4. Set `spawned_by = spawner`, `close_on_done`, `last_active = time.monotonic()`. Call `refresh()`. Return the session.
- `agent_state` does not change.
**Acceptance Criteria:**
- `spawn_peer` creates a session with `spawned_by` set, does not change `win._active`, and adds a board session.
- With limit 2 and two idle `done` peers, a third spawn closes the one with the older `last_active`.
- With limit 2 and peers in states running + error-outcome, a third spawn returns the `limit_error` text and creates nothing.
- User-spawned agents (`spawned_by is None`) do not count toward the limit.
- With no board session, an error is returned and nothing is created.

**Files:**
- Modify: `pyside_gui/agent_session.py:39-70`, `pyside_gui/agents_controller.py:55-78`, `pyside_gui/tests/session_stub.py`
- Test: `pyside_gui/tests/test_agents.py`

#### Tests
Extend `FakeWindow`: `_main._config.max_spawned_agents`, `_main._board_session = SimpleNamespace(handle="main_11112222")`, and `_conversation` on StubSession is already a MagicMock.
- `test_spawn_peer_does_not_activate_and_records_spawner`
- `test_spawn_peer_evicts_lru_idle_done_peer`
- `test_spawn_peer_refuses_when_no_peer_is_evictable`
- `test_user_spawned_agents_do_not_count_toward_limit`
- `test_spawn_peer_needs_the_board`
- `test_user_spawn_still_activates` (regression for the split)

- [ ] **Step 1–4: TDD** with `pyside_gui/tests/test_agents.py` (unsandboxed).
- [ ] **Step 5: Return for review.**

---

### Subtask 6: Worker-thread spawn flow and task delivery (D2, D13) ✅ (`da5f0919`)

**Goal:** Connect the main session's `AgentCallbacks.spawn_agent` to `spawn_peer`, then register the peer and post its task **in that order**.
**Requirements:**
- `AgentBridge.build_callbacks(loop_ref=None, board=None, spawn_agent=None)` passes `spawn_agent` through to `AgentCallbacks`.
- `_dispatch.dispatch_agent` passes `spawn_agent=getattr(win, "_spawn_agent", None)`. Only the **main** session defines it. `AgentSession._spawn_agent` is a property that returns `self._spawn_from_worker` when `self is self.win._main`, else `None` (D6).
- `AgentSession._spawn_from_worker(slug, task, close_on_done) -> str` runs on the worker thread:
  1. Create `concurrent.futures.Future`. Use `QMetaObject.invokeMethod(self, "_spawn_on_main", QueuedConnection, Q_ARG(object, (slug, close_on_done, future)))`. Wait `future.result(timeout=15)`. On timeout, return `Error: the GUI did not answer the spawn request in 15 s.`
  2. `_spawn_on_main` (a `@Slot(object)`, GUI thread) calls `win._agents.spawn_peer(slug, close_on_done, spawner=self._board_session.handle)`. It sets the future result to the session or the error string. Any exception goes into `future.set_exception`.
  3. On an error string, return it.
  4. Worker thread, synchronously: `peer_board = peer._board_session`. Call `peer_board.client.register(peer.handle, "agent", host=socket.gethostname(), key=peer_board.key)`. Then `text, attach = task_post(peer.handle, task)`. If `attach`, write the full task to `DAGI_ROOT/.dagi/temp/peers/<peer>/task.md`. Then call `self._board_session.post(text, files=[path] if attach else ())`.
  5. If the post fails (a `BoardError`), return `Error: spawned <handle> but could not post its task: <error>. Post it yourself with post_board @<handle>.`. The peer stays, so the Admiral can see it.
  6. Success: `Spawned <handle> (close_on_done=<b>). Its task is on the board as post #<id>. Its result will arrive as a board message to you; do not wait for it in this turn.`
- **Why register first:** the board records a mention only for a registered member (`_mention_warning` "matched no board member"). `BoardController.add_session` registers on a background worker, so a post right after it can race. Calling `register` again is idempotent (`store.py:191-205`).
**Acceptance Criteria:**
- The main session's callbacks have `spawn_agent` set. A non-main session's callbacks have `spawn_agent is None`.
- With a fake board client that records calls, the order is `register(peer)` → `upload` (only for a long task) → `post`, and the post text is from `task_post`.
- Real board app (`TestClient`): after spawn, `posts(mention=<peer>)` returns the task post (proves that the mention was recorded).
- A timeout or a spawn error returns the error text and posts nothing.

**Files:**
- Modify: `pyside_gui/bridge.py:140-246`, `pyside_gui/_dispatch.py:192-194`, `pyside_gui/agent_session.py`
- Test: `pyside_gui/tests/test_spawn_flow.py` (create)

#### Tests
- `test_only_main_session_gets_spawn_callback`
- `test_spawn_registers_before_posting_task` (fake client)
- `test_long_task_is_attached_as_task_md`
- `test_task_mention_is_recorded_on_real_board` (`services.message_board.app.create_app` + `TestClient`, as in `tests/test_board_tools.py`)
- `test_spawn_error_returns_text_and_posts_nothing`
- Run `_spawn_from_worker` on a real `threading.Thread`, with `qtbot.waitUntil` on the GUI thread, so that the queued call really crosses threads.

- [ ] **Step 1–4: TDD.**
- [ ] **Step 5: Return for review.**

---

### Subtask 7: Peer turn-end reporting and `close_on_done` (D4, D5, D12) ✅ (`855db6ee`)

**Goal:** When a peer's turn ends, or a server error pauses it, post a report to its spawner, and close the peer after a clean `done` if it was asked to. ESC posts nothing (D14).
**Requirements:**
- Turn outcome tracking in `AgentSession` (GUI thread):
  - `_show_running` (turn start): `_turn_handoff = None`, `_turn_done_seen = False`, `last_active = now`.
  - Connect `bridge.handoff_text` → `_turn_handoff = text` (in addition to the existing `cv.append_assistant`).
  - `_on_agent_done`: `_turn_done_seen = True`. `on_done` fires only for `write_handoff` (END_TURN) or max-continuations (`agent/_tool_dispatch.py:371`, `agent/loop.py:939`), and the bridge sends `handoff_text` first only for a handoff.
  - Connect `bridge.error_occurred` → remember the last error text for this turn (`_turn_error`).
- New `_dispatch.agent_work` `finally` call: `win._invoke_on_main("_turn_finished_slot")`, **after** `_set_status_slot("idle")`. `AgentSession._turn_finished_slot` → `_report_turn_end()`.
- `_report_turn_end()` (it does nothing if `spawned_by is None`):
  - outcome = `done` if `_turn_handoff is not None`; `max-continuations` if `_turn_done_seen`; else `error`.
  - `last_outcome = outcome`, `last_active = now`.
  - Body: the handoff text for `done`; else the last assistant message or `_turn_error` text.
  - Post from **the peer's** `_board_session`, on `win._board_controller._run_worker`. Never post on the GUI thread. Text = `report_post(spawned_by, outcome, body)`. For `done`, attach `DAGI_ROOT/.dagi/temp/peers/<handle>/handoff_<handle>.md` (write the file on the worker before the upload).
  - If the post fails: `self._conversation.append_error("Could not report to <spawner>: <error>")` (marshalled to the GUI thread). Do not close the peer.
  - If `outcome == "done" and close_on_done`: after a successful post, `win._agents.close_agent(self.handle)` on the GUI thread. A peer whose outcome is not `done` is never closed by the system (D5).
- `stop()` (ESC) does **not** change: no post, no `last_outcome` change, no close (D14). The peer stays paused until the Admiral types to it. Its later turn end reports as usual.
- `_on_agent_paused` (server-error pause, not ESC): if `spawned_by` is set, post `report_post(spawned_by, "error", "paused after a server error")` and set `last_outcome = "error"`. The worker stays alive. If the Admiral retries the peer later, the next turn end reports again.
- If the board session is `None` at report time, show `append_error("Board offline — could not report to <spawner>.")`.
**Acceptance Criteria:**
- A peer turn with a handoff posts `@main_… [done] <head>` with one attachment whose content equals the full handoff.
- `close_on_done=True` + done → the peer is removed after the post. `close_on_done=True` + error / max-continuations → the peer stays.
- A max-continuations end posts `[max-continuations]`. An exception end posts `[error] <message>`. ESC on a running peer posts nothing and does not close it, even with `close_on_done=True`.
- A user-spawned agent (`spawned_by is None`) never posts reports.
- The main agent, woken by the `[done]` mention, sees the `fetch_attachment` hint (the existing `mention_message`).

**Files:**
- Modify: `pyside_gui/agent_session.py` (`_connect_signals`, `_show_running`, `_on_agent_done`, `_on_agent_paused`, `stop`, new slots), `pyside_gui/_dispatch.py:243-251`
- Test: `pyside_gui/tests/test_peer_reports.py` (create)

#### Tests
Use `StubSession` with `spawned_by="main_11112222"`, a fake `_board_session` that records `post(text, files)` calls, and a fake `_board_controller._run_worker` that runs the target at once.
- `test_handoff_turn_posts_done_with_full_handoff_attached`
- `test_close_on_done_closes_only_after_clean_done` (parametrized over the three outcomes)
- `test_max_continuations_and_error_tags`
- `test_esc_on_peer_posts_nothing_and_keeps_it` (D14: no `post` call, `last_outcome` does not change, and the peer is not closed)
- `test_user_spawned_agent_never_reports`
- `test_report_post_failure_keeps_peer_and_shows_error`
- One integration test with a real `AgentBridge` and fake callbacks: `on_handoff`, `on_tool_end("write_handoff")`, `on_done(text)` → the session sees `_turn_handoff == text`.

- [ ] **Step 1–4: TDD.**
- [ ] **Step 5: Return for review.**

---

### Subtask 8: ESC peer notice on the main agent (D10) ✅ (`a2df76f9`)

**Goal:** After ESC stops the main agent, list its active peers in the chat.
**Requirements:**
- In `AgentSession.stop()`, after the existing `"Interrupted — type a message to continue"` line, if `self is self.win._main`:
  `notice = active_notice([s for s in win._sessions if s.spawned_by == self._board_session.handle])` with `state = agent_state(s)`. If the notice is not `None`, call `self._conversation.append_info(notice)`.
- No peer is stopped, and nothing is posted to the board (D10, D14).
**Acceptance Criteria:**
- With peers running + waiting + idle, ESC on main shows one line that lists only the running and waiting ones, in spawn order.
- With no active peers, no extra line appears.
- `peer.stop` is never called.

**Files:**
- Modify: `pyside_gui/agent_session.py:217-232`
- Test: `pyside_gui/tests/test_peer_reports.py`

- [ ] **Step 1–4: TDD** (`test_esc_on_main_lists_active_peers_only`, `test_esc_on_main_without_active_peers_adds_nothing`).
- [ ] **Step 5: Return for review.**

---

## Workspace
- **Branch:** `task/model-spawned-agents`
- **Parent:** `main`
- **Starting commit:** `8ca9b33e`
- **Task folder:** `wiki/tasks/2026-10-17_model-spawned-agents/`

## Overall Status
Verification — Subtasks 1–8 done; integrated verification next

## Notes
- Hook points found during exploration:
  - `write_handoff` is registered for every agent (`agent/tools.py:367`). END_TURN calls `on_handoff` before `on_done` (`agent/_tool_dispatch.py:214-217`, `:371`). The bridge sends `handoff_text` only for a handoff (`pyside_gui/bridge.py:134-138`).
  - `on_done` fires only for a handoff or max-continuations. An exception goes through `on_error` and `agent_work`'s `except`. ESC (`interrupt`) pauses the loop: the worker thread stays alive, and no `finally` runs until the turn ends later.
  - Frontend tools are gated on `AgentCallbacks` fields in `_register_frontend_tools` (`agent/tools.py:203`). This is the same pattern as `board` and `on_show_file`.
  - `BoardController.add_session` registers on a background worker (`pyside_gui/board_controller.py:124-133`). That is why Subtask 6 registers synchronously again before the task post.
  - The main session's handle is `"main"` until `on_board_ready` sets the board handle. Use `self._board_session.handle` as the spawner, never `self.handle`.
- Trap: `AgentsController.close_agent` refuses a `waiting` agent and stops a running one. Eviction only selects `idle` peers, so neither case happens there.
- Trap: a new tool shifts the schema order ([[tool-registration-order-is-schema-order]]). Register new tools after the existing ones in each block.
- Out of scope: persisting peers across GUI restarts (as in the board-multi-agent non-goals), per-peer model/folder overrides, `close_agent`/`list_agents` tools, peers that spawn peers.

## Open Issues
- None blocking. Routing quality between `spawn_agent` and typed subagents depends on the tool description only. There is no eval in this task.

## Attempts and Resolutions
- **Subtask 1, attempt 1:** PASS. Note: `pyside_gui/sidebars/settings_view.py:79-85` `_SPIN_FIELDS` is a curated subset (no `max_continuations` either), so the new key is not added to the Settings tab.
- **Subtask 2, attempt 1:** PASS. Main agent also added `board_members` to `config.example.yaml` board-tools comment and `pyside_gui/tool_labels.py`. Note: the offline-member test back-dates `last_seen` through `store._conn` (works; `_clock` monkeypatch in `tests/message_board/test_store.py:485` is the cleaner pattern).
- **Subtask 3, attempt 1:** PASS. Note: the v2 inherited fork (`agent/inherited_registry.py:42-54`, used by compaction) copies the parent's tool schemas, so a forked child sees the `spawn_agent` schema, but `allowed_names` blocks execution (same as other frontend tools). No capability leaks.
- **Subtask 4, attempt 1:** ESCALATE — `report_post` let a 501–680-char body through uncut, which breaks the D12 ≤500 head. -> Main agent fixed it: the head is always cut to 500 + `…`, `active_notice` reuses `_word`, and the Qt guard is now a subprocess `sys.modules` check. **Attempt 2:** PASS.
- **Subtask 5, attempt 1:** ESCALATE — eviction ran before slug and model-config validation, so a failed spawn could close a peer for nothing. -> Main agent split `_create` into `_validate` (no side effects) + `_build`. `spawn_peer` now validates first, then evicts, then builds. The regression test `test_failed_spawn_at_the_limit_closes_no_peer` fails on the old order. **Attempt 2:** PASS. Edge: a new slug equal to the victim's slug is refused as a duplicate (accepted: the model can follow up with that peer instead).
- **Subtask 6, attempt 1:** ESCALATE — after the 15 s timeout, the queued GUI call could still create a peer with no task. -> Main agent added `future.cancel()` on timeout and a `set_running_or_notify_cancel()` guard in `_spawn_on_main`. If the spawn has already started, the worker waits for the real result. The regression test `test_late_spawn_after_timeout_creates_no_peer` fails without the guard. **Attempt 2:** PASS. Accepted deviations: `Q_ARG("QVariant")`/`@Slot("QVariant")` (PySide6 has no QMetaType for `object`); the spawner falls back to `self.handle` only when the main board is `None`, and then `spawn_peer` refuses anyway. Unrelated flake: `test_settings_view.py::test_real_watcher_sees_atomic_replace` ([[qfilesystemwatcher-dir-watch-breaks-os-replace]]).
- **Subtask 7, attempt 1:** ESCALATE — (1) a pending close_on_done could close a peer after a newer turn had failed; (2) a failed handoff-file write was not reported. -> Main agent added a `_close_for_submission` guard against `_submission_seq` (generation check). The file write moved inside the post try. A failed report sets `last_outcome = "unreported"` (never evictable). Both regression tests fail on the old code. **Attempt 2:** PASS.
- **Subtask 8, attempt 1:** PASS. ESC with main idle collapses the sidebar and shows no notice (consistent with D10). `test_paste_cards.py::test_ctrl_shift_v_pastes_long_text_inline` fails on clean `main` too (Windows `OpenClipboard Failed`, so the cause is the environment).

## Verification
1. Unit + GUI suites (unsandboxed):
   `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt tests/test_spawn_agent_config.py tests/test_board_tools.py tests/test_spawn_agent_tool.py tests/test_peers.py pyside_gui/tests/test_agents.py pyside_gui/tests/test_spawn_flow.py pyside_gui/tests/test_peer_reports.py pyside_gui/tests/test_bridge.py`
   Expected: all pass.
2. Full suite: `...pytest -q -p no:pytest-qt`. Expected: no new failures compared with `main` (see [[todo-preexisting-failing-tests]]).
3. Manual GUI check (Admiral): start the GUI with a board. Ask main to "spawn a peer `probe` that writes a one-line handoff". See the row in Agents, the `[task]` post, then the `[done]` post with `handoff_probe_….md`, and main waking on it. Repeat with `close_on_done=true`, and the row disappears. Press ESC on main while a peer runs, and the notice line appears.

## Next Action
Admiral reviews and approves this plan. Then commit it as `plan: approve plan` and start Subtask 1 with `deliver`.
