---
title: 'Model-spawned GUI peers (spawn_agent): design and gotchas'
description: 'Main GUI agent spawns visible, steerable peer AgentSessions; task and result travel on the board. Register before the [task] post, cancel timed-out spawns, generation-guard close_on_done.'
tags: [spawn_agent, spawn_peer, AgentsController, AgentSession, board_members, close_on_done, max_spawned_agents, QVariant, Q_ARG, peers.py]
updated: 2026-10-19
---
## Decision (Admiral, 2026-10-17)

Typed subprocess subagents and GUI peers **coexist**. `spawn_agent(slug, task, close_on_done=False)`
exists only for the PySide **main** session (`AgentCallbacks.spawn_agent` is set only there), so
the TUI, Telegram, subagents and peers never see it. Peers copy main's model, folder and tools.
The call is async: it returns the handle at once.

- Task: `@<peer> [task] <text>` from main (`task.md` attached if > 700 chars).
- Result: when a peer's turn ends, the peer posts `@<spawner> [done] <≤500 head>` with
  `handoff_<handle>.md` attached, or `[max-continuations]` / `[error]` (server-error pause too).
  Completion = `write_handoff`; the loop's continuation prompt already enforces it.
- ESC posts nothing ([[esc-pause-only-pauses]]). ESC on main lists active peers (display only).
- `max_spawned_agents` (default 4, model-spawned only): at the limit, close the LRU idle peer
  whose `last_outcome == "done"`; otherwise `spawn_agent` returns an error that lists peers.
- `board_members` lists online board handles (no busy state; presence lags ~30 s).
- Plan and decisions D1–D14: `wiki/tasks/2026-10-17_model-spawned-agents/plan.md`.

Code: `tools/spawn_agent/`, `pyside_gui/peers.py` (pure formats + eviction rule),
`AgentsController._validate/_build/spawn_peer`, `AgentSession._spawn_from_worker`,
`_report_turn_end`, `_post_report`.

## Gotchas

- **The `tools:` allow-list in `.dagi/config.yaml` removes new tools without a message.** `filter_to`
  drops any registered tool that is not listed, so `spawn_agent` and `board_members` must be in
  the list (fixed 2026-10-17). Any new tool needs the same entry.

- **Register the peer before the `[task]` post.** The board records a mention only for a
  registered member, and `BoardController.add_session` registers on a background worker, so the
  post can race it. `_spawn_from_worker` calls `client.register` synchronously first (it is
  idempotent).
- **PySide6 has no QMetaType for `object`.** `Q_ARG(object, …)` raises
  `qArgDataFromPyType: Unable to find a QMetaType for "object"`. Use `Q_ARG("QVariant", …)`
  with `@Slot("QVariant")` to pass a Python tuple across threads.
- **Cancel a timed-out cross-thread request.** The worker waits on a `Future` for 15 s. On
  timeout it calls `future.cancel()`, and the GUI slot begins with
  `if not future.set_running_or_notify_cancel(): return`. Without this, a late GUI call creates
  a peer that has no task.
- **Validate before evicting.** `spawn_peer` runs `_validate` (slug + model config, with no side
  effects) before it closes a victim. Otherwise a bad slug closes a peer and spawns nothing.
- **Generation-guard deferred actions.** `close_on_done` is queued after the async post. It runs only
  if `_close_for_submission == _submission_seq and last_outcome == "done"`, so a newer turn
  cancels it. A failed report sets `last_outcome = "unreported"` (never evicted).
- **A courtesy @mention re-wakes an idle peer, which ends that turn with another `[done]`.** Agent-
  to-agent mentions are never capped (`test_agent_mentions_always_wake`), so a main↔peer ack
  ping-pong is bounded only by the models' judgment. Observed 2026-10-17 on the manual check: an
  "@probe nice work" reply woke the idle probe, which posted a second `[done]` (and read the ack as
  praise from the Admiral). In total that one trivial task produced 7 posts and 5 turns (the minimum
  is 2 posts). The peer also posted its result by hand before `write_handoff` posted it again.
  **Fix (Admiral: prompt only, no code guard):** `on_board_mention` picks a wake footer by
  role. Spawner→peer posts get `peers.peer_footer` ("your handoff is posted for you; do not post
  results or acks; do not @mention the spawner"). Peer→spawner posts get `peers.spawner_footer`
  ("automatic report; @mention the peer only for new work"). The `spawn_agent` description and
  its success text carry the same rule. Residual: this relies on the models obeying the prompt.
- The spawner identity is `_board_session.handle`. The main session's `handle` stays `"main"`
  until the board connects.
- The v2 inherited fork (compaction) copies the parent's tool schemas, so it can see
  `spawn_agent`, but `allowed_names` blocks the call.

## Not solved (accepted trade-offs)

Typed subagents in headless runs are still not steerable or visible. There is no eval of
peer-vs-subagent routing; the tool description carries it. Peers are not persisted across GUI
restarts.

## October 18 review: report workers need per-turn identity and immutable evidence

Reviewed main `918041c2cc085398691c5564fe23792393dd30c2`; no implementation repair made.
Open **R32**: an older successful report callback can read a newer turn's shared close
marker and request its closure before its report is posted. An older failed callback can overwrite
a successfully delivered newer turn as unreported. The board-none branch leaves done
eligible for eviction despite no delivery. Carry originating submission identity through
every callback and track computed/delivered separately; reject stale updates and preserve
undelivered reports for retry. ESC must remain target-only pause with no board side effects.

Open **R33**: all turns write the same handoff path. A gated actual BoardSession.post
with fake upload read FIRST's path after SECOND overwrote it, producing FIRST's preview
with SECOND's attachment. Use immutable per-submission bytes/paths and delivery receipts;
callback guards alone cannot fix the file race. These are proposals, not approved repairs.

[Probe](C:/Users/alexr/.codex/visualizations/2026/10/18/01a14c89-816a-7cd3-8b0e-c7a49008ee44/peer_report_probes.py),
[results](C:/Users/alexr/.codex/visualizations/2026/10/18/01a14c89-816a-7cd3-8b0e-c7a49008ee44/peer_report_results.json). Four controlled assertions reproduced with
real AgentSession methods and fake queues/clients; scratch files removed, worker joined.
396 core and 76 offscreen GUI/controller tests passed. No external board/provider or desktop
input. Simple existing report tests pass while these overlap cases are not covered.
The roadmap now extends the shipped spawning/task/result flow with attempt/acceptance
receipts (S13) and retained retryable reports (S9); it does not propose rebuilding the feature.

## October 19 review: task admission and post destination need stable boundaries

At unchanged main `918041c2`, new **R34** reproduces a successful spawn before the initial
snapshot settles: its task enters the snapshot, which never wakes agents, and the live
cursor skips it. A task posted after snapshot setup delivers through the same mention hook.
Preserve current-session assignments across setup and distinguish posted from accepted;
do not start replaying historical mentions or cap live agent conversation.

New **R35** reproduces `BoardSession.post` uploading to A, rebinding to B, then publishing
the A attachment ID to B, which rejects UNKNOWN_ATTACHMENT. Bind all uploads and publication
to one client/generation lease; keep it alive through completion or acknowledged cancellation.
Retain report bytes for explicit retry. This differs from R30 downloads and R33 file reuse.
Both are proposed repairs, not approved implementation. ESC remains a target-only pause.

[Probe](C:/Users/alexr/.codex/visualizations/2026/10/19/01a154aa-60bd-7760-9ec1-7a7c4cacde39/board_boundary_probes.py),
[results](C:/Users/alexr/.codex/visualizations/2026/10/19/01a154aa-60bd-7760-9ec1-7a7c4cacde39/board_boundary_results.json).
Actual spawn/snapshot/mention and post/rebind methods used independent in-process boards,
stub peer creation, fake stream transport and a controlled upload gate; successful controls covered later tasks
and stable-board posts. Workers joined and scratch data removed. 158 core and 76 offscreen
Qt tests passed; no external traffic, provider or desktop input. R32/R33 remain open with
October 18 evidence. S8/S9/S13 now include these boundaries without duplicating built features.
