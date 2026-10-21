---
title: 'Ticket tracker separate from message board (design discussion, open)'
description: 'Admiral direction 2026-10-21: official work goes to a ticket tracker with status/leases; the board stays chat. Open question: own service vs same process as board.'
tags: [ticket-tracker, jira, message-board, PatchBoard, write_handoff, _report_turn_end, ping-pong, leases, idempotency, Beads, multi-machine]
updated: 2026-10-21
---

Design discussion only; **nothing approved or built**. Origin: proposal 3 in
[explore-radical-architecture-proposals-2026-10](explore-radical-architecture-proposals-2026-10.md)
(PatchBoard, arXiv 2605.29313).

## Admiral decisions so far

1. The board coordinates agents on **all machines** (Claude Code, Codex, remote dagi).
2. **Agent-to-agent chat mentions keep waking agents** (`test_agent_mentions_always_wake` stays).
3. **Tracker ("jira") and message board are separate things.** Tracker = tickets with status,
   official reports and updates. Board = agent-to-agent / agent-to-all chat.

## Why (problem found)

`pyside_gui/agent_session.py::_report_turn_end` posts a `[done]`/`[error]`/
`[max-continuations]` report at the end of **every** turn of a spawned peer, whatever started
the turn. A chat ack ("@probe nice work") wakes the peer, its turn end auto-posts `[done]`,
which wakes the spawner: the ping-pong amplifier (see [[model-spawned-gui-peers]]).
Principle: a report belongs to a **task**, not to a **turn**.

With the tracker, `write_handoff` on a ticket turn completes the ticket (no board post); a
chat-started turn posts nothing automatically. Interim option without a tracker: harness rule
by turn origin (report only for turns started by a `[task]` post or the spawn). A model-chosen
`post_to_board` flag alone was rejected as the only trigger: failure becomes a silent lost
result (worse than noise); acceptable only as a suppress-only override.

## Responsibilities

| | Tracker | Message board |
|---|---|---|
| Purpose | tasks, status, reports | conversation, you, broadcasts |
| Rules | owner write contracts, version (`rev` test), claim lease, request ID | free text; mentions wake |
| Truth | source of truth for work | not a source of truth |
| Wakes on | ticket assigned / done / failed | mention |
| Holds | spec, immutable versioned result handoff, artifacts | posts, casual attachments |

Ticket states: `open → claimed → done | failed | cancelled`. Only the assignee claims or
completes; only the spawner cancels; stale `rev` writes are rejected (targets R32/R33).

## Multi-machine needs

- Claim **leases** with renew/expiry (crashed agent's ticket returns to open).
- **Idempotent request IDs** on every write (network retry must not double-claim/post).
- Wake by **push** (`/stream` SSE) plus **pull** ("my tickets not done") on start and
  periodically; pull makes a missed event a delay, not a loss.
- Ticket operations for non-dagi agents through an **MCP server** (existing TODO).

## Design points

1. **One identity** for both systems: reuse board members/keys (`register_member`,
   `authenticate` in `services/message_board/store.py`) or a shared identity service.
2. **Links only:** chat may reference `T-42` (rendered as link); tracker may link a chat
   thread; neither copies the other's data.
3. **Artifacts live on the ticket** (immutable, versioned): removes ticket results from board
   uploads, targeting R33/R35.
4. Leanings: fixed protocol schema (not Architect-generated), typed tools (`claim_task`,
   `complete_task`, `fail_task`, `renew`) over raw JSON Patch; kernel may still log each call
   as a patch.

## Prior art

Beads (`bd`, Steve Yegge, MIT, Go, Dolt/git-backed): agent issue tracker with dependencies,
"ready work" query, MCP server. Syncs per project via git; no real-time leases or wake-ups,
so not a drop-in for live multi-machine coordination; good model for schema and ready query.

## Open question (Admiral thinking, 2026-10-21)

Where does the tracker run?
- (a) own service: separate process, port, database;
- (b) same server process as the board, separate database and API (one thing to start, one
  identity, shared uptime). Claude recommended (b) first; API allows a later split.
Also still open: order relative to the general effect kernel (proposal 1); Claude recommended
the tracker first as the cheaper prototype of the kernel pattern.
