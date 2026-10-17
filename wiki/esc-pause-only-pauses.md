---
title: 'ESC / pause only pauses: no side effects apart from user-facing displays'
description: 'Decision 2026-10-17: ESC on any agent pauses its own turn only. No board posts, no wake-ups, no closes, no cascade to peers. Only info lines and displays may be added.'
tags: [ESC, pause, interrupt, AgentSession.stop, AgentLoop.interrupt, _action_pause, esc_stop, peer, spawn_agent, D14]
updated: 2026-10-17
---
## Decision (Admiral, 2026-10-17)

ESC (and any user pause) **only pauses** the agent that it targets. This applies to the main
agent, to user-spawned agents and to model-spawned peers. ESC must not:
- post to the message board (no `[stopped]` report to a spawner);
- wake, steer or stop another agent (no cascade from main to its peers);
- close or remove any agent, even a peer with `close_on_done=True`;
- change any other state that the user did not ask for (for example `last_outcome`, eviction eligibility).

Allowed: information and displays for the user, for example the "Interrupted — type a message
to continue" line, or the D10 line on main that lists peers that are still active.

Stopping the agent's **own** work in progress is part of the pause, and is still correct:
`AgentLoop.interrupt()` kills its own bash, code scripts and owner-scoped subagents
([[subagent-cancellation-is-owner-scoped]]).

## Why

ESC means that the Admiral is present. The Admiral decides what happens next. For example, the
Admiral can guide a stopped peer to completion while the main agent works on another task. Any
automatic reaction (a post, a wake-up, a close) acts before the Admiral has decided.

## Consequences

- A paused agent's worker thread stays alive inside the same `run()` call. When the Admiral
  continues it, its normal turn end still produces the usual result (for example a peer's
  `[done]` post). Pausing does not break the result contract.
- If the Admiral closes a paused peer, its spawner gets no report. This is accepted.
- A **server-error** pause (`_on_agent_paused`, retries exhausted) is not a user pause. The plan
  for model-spawned agents reports it as `[error]` to the spawner (confirmed by the Admiral,
  2026-10-17): no user pressed anything, so nobody may be present.

## Rejected

- ESC on a peer posts `@main [stopped]`: it wakes main while the Admiral steers the peer, and
  it gives two reports (`[stopped]`, then `[done]`) for one task.
- ESC on main cascades to its peers: it loses peer work that the Admiral wanted to keep.

Source: `wiki/tasks/2026-10-17_model-spawned-agents/plan.md` (D10, D14).
