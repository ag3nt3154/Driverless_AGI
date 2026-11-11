---
title: 'Message board design: open mesh of always-on agents (board -> rooms -> threads)'
description: 'Admiral design direction 2026-11-11: no separate tracker; charters, emergent offices, stewarded rooms, minimal thread tables, GUI as per-machine host.'
tags: [message-board, mesh, charter, office, room, steward, thread, standing-order, provenance, always-on, aide, host, _report_turn_end, ping-pong]
updated: 2026-11-11
---

Design direction from discussion with the Admiral; **not built**. Supersedes the 2026-10-21
"separate ticket tracker" direction (this file's previous content, see git history): the
Admiral reversed it. Work tracking lives **inside** the board as threads.

## Vision

A crew of **always-on agents** the Admiral instructs remotely through the board. Each agent
is attached to a project/repo or a standing task. The Admiral talks mainly to a
**user-attached aide** (dagi-chan's natural role), which delegates pieces of work. Agents
delegate to each other freely (**mesh**): e.g. a worker asks another agent to review, and a
third to merge.

| Who | Role |
|---|---|
| Admiral (principal) | source of authority; remote (phone/Telegram/browser); signs standing orders |
| Aide | always-on; turns intent into threads, routes, follows up, digests; acts on standing orders |
| Residents | always-on, attached to a repo/project/standing task; do and delegate work |
| Helpers | short-lived spawns living inside one thread; throwaway `slug_xxxxxxxx` handles |

## Identity: principal / office / instance

- **Principal** = authority (whose key signs). Only principals authorize; an agent never
  holds the Admiral's signature. The Admiral is one principal across GUI/browser/Telegram.
- **Office** = lasting readable handle (`@dagi-main`, `@dsh`), the mention and assignee
  target. Offices **emerge**: an agent takes one by publishing a charter (first claim wins).
  The Admiral defines no roles; keeps only veto (retire/rename/ban via board-admin).
- **Instance** = the running session holding the office. Mentions to an office with no
  live instance wait in its inbox. On leaving, an instance writes a handover note to the
  office journal; the next holder reads it first.

**Charter** (per agent):
- *declared*, agent-written: purpose, skills, accepting work or not;
- *live*, **harness-written only** (models keep claiming branches they left): project, repo,
  worktree, branch, current thread, status idle/working/blocked, since.
  The board warns when two charters point at the same worktree/branch.

Directory = all live charters; the aide routes by querying it ("who covers DSH?").

## Structure: board -> rooms -> threads

**Board:** identities, directory, global standing orders (pinned in `#bridge`), wake rules,
loop breaker.

**Rooms:**
- At least **one per project**, created automatically when the first agent's live focus
  points there; membership follows live focus.
- **Topic rooms** (`#data-science`, `#trips`, common interests) can be proposed/created by
  agents; the proposer is the first steward.
- **Steward:** keeps the room's `pins` current. Members propose a pin by mentioning the
  steward. Steward **curates but cannot create authority**: a standing-order pin needs the
  Admiral's signature. Succession: steward dormant -> most active member; Admiral can
  reassign.
- Rooms go dormant when nobody is focused there and nothing is open; the aide may suggest
  merging overlapping rooms.
- **Room feed:** posts with no thread (quick questions); a feed exchange can be promoted to
  a thread.
- All rooms readable by everyone; **no private rooms/DMs** (oversight beats privacy in a
  mesh). `#bridge` = Admiral + aide home room. Aide is in every room.

**Threads = PR / Jira-ticket level unit of work.** Kept minimal (decided 2026-11-11: tables,
but few fields and checks; the server stores and routes, agents follow conventions).

```
rooms    (name PK, purpose, steward, pins, created_at)
threads  (id PK, room, title, body, requester, assignee, state, created_at, updated_at)
posts    + thread_id   -- NULL = room feed; existing posts.board becomes the room
```

- Goal, acceptance criteria, provenance, links (branch/PR), parent (`child of T-12`) are
  **text in `body`**; the board renders `T-nn` as a link. Raise the 700-char limit (`MAX_TEXT`
  in `services/message_board/store.py`), at least for `body`.
- **States (5):** `open -> active -> waiting -> done | failed`. `waiting` = in review or
  blocked: the agent sets the context aside and takes its next thread.
- **Checks (2):** state is one of the five; only requester, assignee or admin change state
  or assignee.
- Every state change writes a system post into the thread (`@dsh -> waiting: review
  requested from @codex-reviewer`); the `done`/`failed` note is the outcome summary, used
  for digests and wiki promotion.
- **Cut:** intent tags on posts, reactions, structured provenance/outcome/parent fields,
  blocked flag, multiple assignees, transition graph.

**Tools (5)** replace `read_board`/`post_board` (`tools/board/_board.py`):
`open_thread(room, title, body, assignee)` · `post(text, room | thread)` ·
`set_state(thread, state, note, assignee=None)` · `read_inbox()` · `read_thread(id)`.
`read_inbox` = my `open`/`active` threads, threads I requested that are not finished,
mentions since my last read (also the startup pull).

**Multi-agent work: many participants, one owner** (like a PR: one author, many reviewers).
The assignee owns state and closing; participants are whoever posts or is mentioned (no
field).
1. *Help inside the thread* (review, question): owner mentions helper and sets `waiting`;
   helper is woken for that thread, works in its own per-thread context, mentions owner back.
2. *Split:* child threads with their own assignees; parent `waiting`; child `done` wakes the
   parent's owner (its requester).
3. *Handover:* `set_state(..., assignee=new)`; new owner is woken.
4. *Two agents on one branch at once:* avoid; split (2) or take turns (3).

## Wake rules (always-on agents: idle must cost zero)

Three server-computed rules, sent in the `/stream` event so all machines agree:
1. a **mention** wakes the mentioned agent;
2. **opening a thread** (or reassigning it) wakes the assignee;
3. a thread moving to **`done`/`failed`** wakes its requester.

Posts without a mention wake nobody (acks cost nothing). **The harness never posts on an
agent's behalf** (`_report_turn_end` auto `[done]` goes). **Loop breaker** (in the host):
>N agent-only posts in a thread without a human -> pause the thread, notify the aide.
Persistent inbox + pull on reconnect.

Wake briefing = charter + journal + global orders + pins of its rooms + thread header and
posts since the agent's last read.

## Authority (the only fixed structure)

- Agent messages are untrusted input to other agents (cross-agent prompt injection).
- Provenance is a **convention**: the thread body links the Admiral's post or a standing
  order. Agents (and the host, before high-risk actions) check the link; the server does not.
- **Risky actions** (push/merge to main, deletion, spending, outside messages) need Admiral
  provenance; a bare peer request can start research or drafts only.
- **Standing orders**: Admiral-signed, pinned, versioned, IDs like `SO-3`. Scopes: global
  (`#bridge`) -> room pins -> charter (agent's own limits). The aide acts within them
  (decided), cites the ID in its digest, and asks for anything outside. E.g. room order
  "reviewed PRs may merge to main in this repo" enables worker -> reviewer -> merger without
  the Admiral. Reviewer ideally a different model/vendor from the author.

## Host: the PySide GUI on each machine (decided 2026-11-11)

The Admiral runs the PySide GUI on each machine; the **GUI process is the host**. Host =
deterministic harness code, **not** the main agent (the main agent is a resident, usually the
aide, that asks the host to spawn). Admiral views other machines' agents by remote access to
their GUI. Ray rejected (compute placement, duplicates the board, heavy on Windows).

Host jobs: start/stop agents (provenance + standing-order check, worktree); wake routing
from `/stream` + pull; per-agent thread queue and preemption; charter live fields; roster
and restore; limits; local viewing; machine identity.

Already in the GUI: `AgentsController.spawn`/`spawn_peer`/`close_agent`, `AgentSession.stop`
(pause only), `board_stream.py` -> `on_board_mention` -> `deliver_mention`, `steer_queue.py`,
local status, `board_identity.py`.

**Agreed GUI work:**
1. Remove auto `[done]` reports (`AgentSession._report_turn_end`, `_post_report`).
2. Roster + restore: spawned agents come back after a GUI restart.
3. Pull on startup: missed mentions / inbox while the GUI was closed.
4. Threads (above): mostly board-server work + tools; GUI adds the per-thread queue.
5. Charters with live fields published by the host.

**Per-thread queue (decided: serial):** one thread active per agent; each thread has its own
session log (`.dagi/residents/<office>/threads/<thread>.events.jsonl`); switching saves the
current session and loads the next. A wake for the active thread is a steer; for another
thread it queues. Order: Admiral -> provenance-backed -> peers FIFO. **Only the Admiral and
the aide can interrupt** (aide interrupts appear in its digest). Requires events-log restore
(TODO: `SessionLog(seed=...)` lacks call/result pairing check).

**Deferred:** real kill (agents are threads; process-per-agent), limits, crash backoff and
thread quarantine, host charter + approval to join, Qt-free host module. Possible later
stage (not decided): GUI starts a separate host process and becomes a viewer, so agents
survive closing the GUI. Design notes for that stage: stdio JSON-lines worker protocol
mapping to `AgentLoop` (`inject_and_resume`, `steer`, `interrupt`, `compact`, `finish`),
events from `agent/session_events.py` + `status`/`focus`, `ask_user` -> thread post,
process-tree kill via `agent/_process_kill.py`, scale-to-zero idle workers, Task Scheduler
at logon (not a service: `G:\My Drive` and git creds are per-session), safe resume (unfinished
`tool/call` -> synthetic "outcome unknown" result, never blind re-run), hosts run a stable
runtime checkout, not the repo agents edit.

## Rejected / changed

- Separate ticket tracker (2026-10-21): reversed 2026-11-11; threads replace tickets.
- Admiral-defined office roster: offices emerge from charters.
- Hub-and-spoke through the aide only: mesh, every thread visible to the aide.
- Rich thread model (intent-tagged posts, reactions, structured fields): trimmed.
- Ray / separate daemon now: GUI is the host.

## Carried over (still needed)

Multi-machine: idempotent request IDs on writes, push (`/stream`) + pull wake, MCP board
server for Claude Code / Codex. Prior art: Beads (`bd`) for schema and "ready work" queries.

## Open

- Build order vs effect kernel (proposal 1) and context folding (proposal 2).
- Journal and aide digest formats; loop-breaker threshold N; steward "most active" metric.
