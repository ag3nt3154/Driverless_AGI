---
title: 'Message board design: always-on stewards, on-demand workers (board -> rooms -> threads)'
description: 'Admiral design direction 2026-11: Admiral talks only to aides (one per open GUI + Telegram; order log); always-on room stewards; one worker per thread; GUI as host.'
tags: [message-board, mesh, charter, office, room, steward, thread, standing-order, provenance, always-on, aide, host, _report_turn_end, ping-pong]
updated: 2026-11-12
---

Design direction from discussion with the Admiral; **not built**. Supersedes the 2026-10-21
"separate ticket tracker" direction (this file's previous content, see git history): the
Admiral reversed it. Work tracking lives **inside** the board as threads.

## Vision

A crew of agents the Admiral directs remotely. **The Admiral does not post on the board in
normal circumstances**: they talk only to **aides** (dagi-chan's natural role) through a
private channel. An aide is the Admiral's **proxy** on the board.

**Aides (decided 2026-11-12): any number, any number per GUI.** Every agent the Admiral
opens to talk to directly is an aide (the GUI main agent, extra agents opened in the GUI for
different things, the Telegram-connected agent), so several things run at once in parallel
conversations. E.g. one GUI can hold a main aide and a Telegram aide at the same time.
Telegram is **just another aide** (a normal aide handle, hosted as one of a GUI's agents, no
special treatment). The aide role is **designated by the handle** (`aide_<8hex>`); agents
spawned by agents (stewards, workers) never get it. The `aide` slug is reserved for hosts
serving the Admiral's private channel (holding the principal key), so an agent cannot claim
it.
- Threads an aide opens list **its own handle** as requester; `done`/`failed` wakes the aide
  that asked. If its GUI is closed, the wake waits in its inbox (aides are restored with
  their GUI, like stewards).
- `#bridge` = the aides' shared room, **no steward**; global standing orders are pinned there
  by the harness from the order log.
- **Shared aide journal** (shared storage): each aide records the orders it handles and the
  threads it opened, and checks it before opening a thread (no duplicates across aides).
- An aide may **interrupt only threads it requested** or threads citing its orders.
- Rejected: one moving `@aide` office held by the last-used GUI (one proxy at a time); one
  aide per GUI.

**Only room stewards are always on**; all other agents
are **spawned on demand, one worker per thread**. Inside threads agents talk and delegate
freely (**mesh**): e.g. a worker asks for a reviewer, and a merger.

| Who | Role |
|---|---|
| Admiral (principal) | source of authority; talks only to aides (GUI/Telegram); board only as an escape hatch (aide down, debugging) via browser composer/admin |
| Aides | every agent the Admiral opens directly (any number per GUI, incl. a Telegram aide); the Admiral's proxies; turn instructions into threads in rooms, follow up, send digests and questions back over their private channel; act on standing orders |
| Stewards | one per room, always on, **coordinate only**: route, open threads, spawn and brief workers, keep pins and journal, digests; at most small tasks (feed questions). Topic-room stewards may sleep until woken |
| Workers | spawned per thread, own it, close it, exit; throwaway `slug_xxxxxxxx` handles; cold start briefed from room pins + thread + steward handoff |

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

Directory = all live charters; aides route by querying it ("who covers DSH?").

With on-demand workers, **long-lived offices are mostly stewards** (one per room). Worker
charters are just "working on T-17". Specialization lives in room pins, skills and the
**steward's journal, which is the room's memory**. A mention to a worker that has exited:
the host respawns a worker if the thread is open, else routes it to the room's steward.
Stewards decide *what* to spawn; the host (code) spawns and enforces provenance and limits.
Keep room pins + system prompt a stable prefix so cold workers hit the prefix cache.

## Structure: board -> rooms -> threads

**Board:** identities, directory, global standing orders (pinned in `#bridge`), wake rules,
loop breaker.

**Rooms:**
- At least **one per project**. Rooms are created by an aide (for the Admiral) or proposed
  by agents (topic rooms: `#data-science`, `#trips`, common interests). **Creating a room
  spawns its steward.**
- **Home host (decided):** each room has one fixed home machine (for a project: the machine
  with the repo; topic room: the creator's machine), recorded in the steward's charter. The
  steward runs there and workers spawn there by default; work needing another machine is an
  explicit board request (with provenance) to that machine's host. Moving a room is
  deliberate (aide/Admiral): stop steward, update charter, restart on the new host from its
  journal, so **journals live in shared storage** (board or memory root). Home host offline
  -> the room's inbox waits; aides see the steward offline.
- **Steward:** what it does: receive the room's work, spawn and brief workers, keep journal
  and `pins`, follow up stuck/failed threads, room digest, answer small feed questions.
  Why: workers start cold and exit; the steward is the room's addressable, always-on
  continuity. Members propose a pin by mentioning the steward. Steward **curates but cannot
  create authority** (standing orders come only from the order log). Succession: the host
  restarts the steward from its journal; an aide or the Admiral can reassign.
- Rooms go dormant when nothing is open; an aide may suggest merging overlapping rooms.
- **Room feed:** posts with no thread (quick questions); a feed exchange can be promoted to
  a thread.
- All rooms readable by everyone; **no private rooms/DMs** (oversight beats privacy in a
  mesh). `#bridge` = the aides' shared room (no steward; global standing orders pinned by
  the harness); the Admiral does not post there. Aides can act in every room.

**Threads = PR / Jira-ticket level unit of work.** Kept minimal (decided 2026-11-11: tables,
but few fields and checks; the server stores and routes, agents follow conventions).

```
rooms    (name PK, purpose, steward, home_host, pins, created_at)
threads  (id PK, room, title, body, requester, assignee, state, created_at, updated_at)
orders   (id PK, kind order|standing, text, channel, created_at)  -- append-only, harness-written
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
1. *Help inside the thread* (review, question): owner mentions a helper (or asks its steward
   to spawn one, e.g. a Codex reviewer) and sets `waiting`; the helper works in its own
   context for that thread and mentions the owner back.
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
>N posts in a thread without an aide taking part -> pause the thread, notify the requesting aide.
Persistent inbox + pull on reconnect.

Wake briefing = charter + journal + global orders + pins of its rooms + thread header and
posts since the agent's last read.

## Authority (the only fixed structure)

- Agent messages are untrusted input to other agents (cross-agent prompt injection).
- **Order log (decided):** since the Admiral never posts, the **harness (not the model)**
  records each Admiral instruction to an aide (GUI or Telegram) as an append-only order on
  the board, `O-57` with the exact words; standing orders likewise as `SO-3`. Only the
  host serving the Admiral's private channel writes it (holds the principal key). A tricked
  aide cannot fabricate an order ID.
- Provenance is a **convention**: the thread body cites `O-nn` or `SO-nn`. Agents (and the
  host, before high-risk actions) check it against the log; the server does not.
- **Risky actions** (push/merge to main, deletion, spending, outside messages) need a real
  order or standing order; a bare peer or aide request can start research or drafts only.
- **Standing orders** scopes: global (`#bridge` pins) -> room pins -> charter (agent's own
  limits). The aide acts within them (decided), cites the ID in its digest, and asks the
  Admiral (private channel) for anything outside. E.g. a room standing order "reviewed PRs
  may merge to main in this repo" enables worker -> reviewer -> merger without the Admiral.
- Rejected: trusting every aide post as Admiral authority (one injected aide turn could
  merge or delete).

## Host: the PySide GUI on each machine (decided 2026-11-11)

The Admiral runs the PySide GUI on each machine; the **GUI process is the host**. Host =
deterministic harness code, **not** the main agent (the main agent is a steward, usually the
aide, that asks the host to spawn). Admiral views other machines' agents by remote access to
their GUI. Ray rejected (compute placement, duplicates the board, heavy on Windows).

Host jobs: start/stop agents (provenance + standing-order check, worktree); wake routing
from `/stream` + pull; worker cap and preemption; charter live fields; order log; roster
and restore; limits; local viewing; machine identity.

Already in the GUI: `AgentsController.spawn`/`spawn_peer`/`close_agent`, `AgentSession.stop`
(pause only), `board_stream.py` -> `on_board_mention` -> `deliver_mention`, `steer_queue.py`,
local status, `board_identity.py`.

**Agreed GUI work:**
1. Remove auto `[done]` reports (`AgentSession._report_turn_end`, `_post_report`).
2. Roster + restore: **stewards** come back after a GUI restart; open threads get their
   worker respawned from the thread log.
3. Pull on startup: missed mentions / inbox while the GUI was closed.
4. Threads (above): mostly board-server work + tools; GUI spawns one worker per thread.
5. Charters with live fields published by the host.
6. **Max concurrent workers per host** (required now: it is the only queue left).
7. **Order log** written by the host serving the Admiral's channel.
8. **Telegram connects to a normal aide** hosted in a GUI (its own `aide_` handle and
   conversation), instead of the current separate dagi routing; touches open R11/R12
   routing findings. Agents the Admiral opens in the GUI get `aide_` handles; agent-spawned
   ones never do.
9. Reserve the `aide` slug for principal-key hosts; aide interrupt scope check.

**One worker per thread** (supersedes the earlier serial per-agent thread queue): each
thread has its own worker, session log
(`.dagi/rooms/<room>/threads/<thread>.events.jsonl`) and branch/worktree, so no context
switching and few worktree collisions. Order under the worker cap: order-backed (`O`/`SO`)
-> peers FIFO. On the board **only aides interrupt** a steward or worker, and only threads
they requested or that cite their orders (interrupts appear in the aide's digest); the Admiral can stop anything locally from the GUI on that machine.
Risk to watch: a busy steward is a bottleneck, hence coordinate-only.
- **Model (decided, simple for now):** every worker uses the GUI's default model. No
  per-room/per-thread choice and no cross-vendor reviewer yet.
- **Waiting threads (decided):** a worker whose thread goes `waiting` writes a short note in
  the thread (what it waits for, next step) and **exits**; the host respawns a worker from the
  thread log on wake. Makes events-log restore required (TODO: `SessionLog(seed=...)` lacks
  call/result pairing check); also used for crash recovery.

**Deferred:** real kill (agents are threads; process-per-agent), other limits (budget,
llama.cpp slots, keep-awake), crash backoff and
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
- Hub-and-spoke through an aide only: mesh, every thread visible to aides.
- Rich thread model (intent-tagged posts, reactions, structured fields): trimmed.
- Ray / separate daemon now: GUI is the host.
- Always-on residents per project / serial per-agent thread queue: only stewards are always
  on (coordinate only); workers spawned per thread.

## Carried over (still needed)

Multi-machine: idempotent request IDs on writes, push (`/stream`) + pull wake, MCP board
server for Claude Code / Codex. Prior art: Beads (`bd`) for schema and "ready work" queries.

## Open

- Build order vs effect kernel (proposal 1) and context folding (proposal 2).
- Journal and aide digest formats; loop-breaker threshold N.
- Housekeeping before building: replace TODO.md "Multi-agent follow-ups" / "Message board
  follow-ups" with the agreed work; write an implementation plan (board server first);
  rewrite `main_system.md` and board tool text when the new tools land.
