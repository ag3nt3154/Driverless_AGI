---
title: 'Model-spawned GUI peers (spawn_agent): design and gotchas'
description: 'Main GUI agent spawns visible, steerable peer AgentSessions; task and result travel on the board. Register before the [task] post, cancel timed-out spawns, generation-guard close_on_done.'
tags: [spawn_agent, spawn_peer, AgentsController, AgentSession, board_members, close_on_done, max_spawned_agents, QVariant, Q_ARG, peers.py]
updated: 2026-10-17
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
- The spawner identity is `_board_session.handle`. The main session's `handle` stays `"main"`
  until the board connects.
- The v2 inherited fork (compaction) copies the parent's tool schemas, so it can see
  `spawn_agent`, but `allowed_names` blocks the call.

## Not solved (accepted trade-offs)

Typed subagents in headless runs are still not steerable or visible. There is no eval of
peer-vs-subagent routing; the tool description carries it. Peers are not persisted across GUI
restarts.
