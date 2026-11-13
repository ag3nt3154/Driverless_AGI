---
title: 'Message board design: always-on stewards, on-demand workers (board -> rooms -> threads)'
description: 'Admiral design direction 2026-11: Admiral talks only to aides (any number; order log); always-on room stewards; one worker per thread in its own folder; GUI as host; #memory room; DB truth with markdown mirror; build order.'
tags: [message-board, mesh, charter, office, room, steward, thread, standing-order, provenance, always-on, aide, host, _report_turn_end, ping-pong, loop-breaker, memory-room, worktree, retention, headscale, build-order]
updated: 2026-11-13
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
- **Shared aide journal** (`aides/state.md` + log, see Journals): each aide records the orders it handles and the
  threads it opened, and checks it before opening a thread (no duplicates across aides).
- An aide may **interrupt only threads it requested** or threads citing its orders.
- Rejected: one moving `@aide` office held by the last-used GUI (one proxy at a time); one
  aide per GUI.

**Only room stewards are always on**; all other agents
are **spawned on demand, one worker per thread**. Inside threads agents talk and delegate
freely (**mesh**): e.g. a worker asks for a reviewer, and a merger.

| Who | Role |
|---|---|
| Admiral (principal) | source of authority; talks only to aides (GUI/Telegram); reads the board in its web app; posts only as an escape hatch (aide down, debugging) via `/admin` |
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
  deliberate (aide/Admiral): stop steward, update charter, copy the **room folder** (journal
  included, see Folders) to the new host, restart there. Home host offline -> the room's
  inbox waits; aides see the steward offline.
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
agent's behalf** (`_report_turn_end` auto `[done]` goes). **Loop breaker** (in the host,
decided 2026-11-12): count agent-caused wakes per thread since the last progress (a cited
aide order or a state change). At **N = 20** the host stops delivering wakes there, sets the
thread `waiting` with note "loop breaker" and tells the steward (re-brief, `failed`, or
escalate to the requesting aide); if the steward is in the loop, escalate straight to the
aide. Board-wide cap: **>200 wakes/hour** pauses all non-aide wakes and pushes an alert to
the Admiral. Both numbers in host config. Persistent inbox + pull on reconnect.

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
(`<rooms_root>/<room>/threads/T-nn/log/`) and branch/worktree, so no context
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
llama.cpp slots, keep-awake), host charter + approval to join, hard OS sandbox,
private-network setup (see Networking), Qt-free host module. Possible later
stage (not decided): GUI starts a separate host process and becomes a viewer, so agents
survive closing the GUI. Design notes for that stage: stdio JSON-lines worker protocol
mapping to `AgentLoop` (`inject_and_resume`, `steer`, `interrupt`, `compact`, `finish`),
events from `agent/session_events.py` + `status`/`focus`, `ask_user` -> thread post,
process-tree kill via `agent/_process_kill.py`, scale-to-zero idle workers, Task Scheduler
at logon (not a service: `G:\My Drive` and git creds are per-session), safe resume (unfinished
`tool/call` -> synthetic "outcome unknown" result, never blind re-run), hosts run a stable
runtime checkout, not the repo agents edit.

## Operating rules (decided 2026-11-12)

**Spawn authority.** Stewards spawn workers **in their own room only**; a worker needing
help asks its steward. Cross-room work = open a thread in the other room (its steward
staffs it). **Aides create rooms**; agents only propose them. Only the Admiral creates aides.
The host enforces hard caps regardless of who asks.

**Notifications.** Three levels: **push** (needs the Admiral now: question, risky-action
approval, second failure, loop-breaker escalation, board-wide pause), **digest** (finished,
blocked, progress), **silent** (everything else). Each aide reports only on its own threads.
Push-level events from GUI aides are relayed to Telegram. Quiet hours via a standing order.

**Failure handling.** The host respawns a crashed worker with backoff; after **2 crashes**
the thread goes to the steward as `failed`. The steward retries once, re-scopes, or
escalates. A **second `failed`** always escalates to the requesting aide -> push to the
Admiral. All attempts stay in the same thread.

**Steward tick.** The host gives each steward a periodic timer wake (about every 15 min,
only while the room has open threads) to watch slow threads: split them into child threads,
re-brief, add workers, or escalate.

**Board offline (temp board removed).** No private fallback board: a private board means
agents silently coordinate with nobody. If the central board is unreachable: the GUI shows
"board offline"; aides keep chatting with the Admiral and report board-dependent work as
unavailable; running workers continue in their current thread and **buffer posts with
idempotent request IDs**; the GUI reconnects with backoff, then does the startup pull. The
GUI never starts the board (it is a standalone service, see below).

### Folders and sandbox

Per room, at a machine-level `<rooms_root>` (not inside any repo):
```
<rooms_root>/<room>/
  shared/                 room-wide files any of its agents may write
  steward/state.md, log/  steward journal (below)
  threads/T-nn/
    repo/   worktree (code threads only), created at spawn
    work/   scratch
    out/    deliverables
    log/    agent session logs
    thread.md, files/     host-written markdown mirror + attachments (below)
```
- **Every room gets a folder**, including conceptual rooms (`#data-science`): those are just
  a collection of markdown files the agents choose to keep.
- **Soft sandbox:** a worker writes only to its own thread folder and the room's `shared/`;
  reads are open. Hard OS sandbox deferred.
- **Environment:** workers share the machine's environment. A **per-room setup recipe** in
  the pins (e.g. `pip install -e`, env files, data links) is run by the host on worktree
  creation and maintained by the steward. Watch the editable-install pitfall (an editable
  install points at one checkout, not the worktree). Fallback: one worker at a time in the
  main checkout when a worktree can't work.
- **Worktree lifecycle:** created at spawn, kept while the thread is open; the merging
  worker deletes it before `done`; the steward cleans up `failed` threads and keeps their
  branch ~2 weeks; a merge conflict returns the thread to `active`; the host refuses a
  duplicate branch; the steward does periodic housekeeping.

### Memory = the `#memory` room

The separate memory root (black_grimoire) goes. Memory becomes the **`#memory` room**, local
to one machine, single writer (its steward and workers).
- **Every memory query is a thread** in `#memory` with its own worker; the steward watches
  slow ones and adds workers or splits them.
- Answers arrive **asynchronously**: a steer if the asker is active, otherwise a wake /
  respawn; if the asker's thread has closed, to the asker's steward. The asker goes
  `waiting` only if it is actually blocked.
- **Ingestion is event-driven:** thread closing notes, steward pushes, scheduled processing
  of other rooms' threads. #memory agents monitor rooms and keep what is pertinent.
- Memory offline -> agents proceed without it.
- Claude Code / Codex reach memory through the MCP board server (raises its priority).
- Later rewrites: the memory-* skills, enter-workflow memory steps, the `[MEMORY]` pointer,
  AGENTS.md / CLAUDE.md references.
- Room journals stay in each room's own folder (supersedes "journals in shared storage /
  memory root").

### Journals and digests

- **`steward/state.md`:** current picture, rewritten in place, capped ~**150 lines**: open
  threads (one line each: id, title, assignee, state, next check), pending items
  (cross-host requests, questions to aides), notes to self (room conventions, requester
  preferences). Restart briefing = this file + room pins + unread inbox, nothing else.
- **`steward/log/YYYY-MM.md`:** append-only, one dated line per decision; never auto-loaded,
  searched by the steward or #memory when needed.
- **Digests are posts:** to the requesting aide's thread (or `#bridge` for room-wide news),
  at the cadence the notification level sets: finished, blocked, needs the Admiral.
- **Aide journal:** same shape (`aides/state.md` + log) on the aides' machine; each aide owns
  the lines for its own threads.
- The harness writes no journal content; it only enforces the cap (cut + tell the steward).

### Storage and retention

- **The board database is the source of truth** (posts, thread state, mentions, orders):
  multi-machine writes, concurrency, indexed wake/inbox queries, idempotency and the
  append-only order log need it. Files-as-truth rejected for that reason.
- **Markdown mirror:** the room's home host writes each thread to
  `threads/T-nn/thread.md` (header: title, state, requester, assignee; then every post) from
  the push stream, attachments in `files/`, linked as `![plot](files/loss.png)`. Host-written,
  never agent-written. Agents on the home host may read it with plain file tools;
  `read_thread` works from anywhere. A lost mirror is rebuilt from the database.
- **Closed threads are archived as markdown** in the room folder once #memory has processed
  them; the database keeps a stub (thread row + pointer). Attachments move with the archive.
- `work/` and `log/` are deleted **30 days** after close (reopen within that keeps them);
  `out/` is kept; failed-thread branches kept ~2 weeks; the **order log is kept forever**.
- The steward does cleanup in housekeeping; the host refuses to delete anything of an open
  thread. All numbers in host config.
- The 700-char post cap stays for posts (longer content goes in a file); `body` gets a
  larger limit.

### The board as a standalone application (decided 2026-11-13)

**Standalone service.** The board server (`python -m services.message_board serve`, FastAPI,
already separate today) runs on **one board host**, started by **Task Scheduler at logon**,
from a stable runtime checkout. No GUI starts or owns it; closing or crashing a GUI never
takes it down; every GUI, aide, steward and worker is a client. It stays small: database,
API, `/stream`, attachments, web UI. (The markdown mirror is written by room home hosts,
not by the board.)

**Web app UI** (replaces the planned PySide Board tab), served by the board at `/`, reachable
from any machine and the Admiral's **phone** over the private network, no install. One UI
to maintain; the GUI only has a "Board" button that opens it (or embeds it with
QWebEngine). Read-mostly, Slack/GitHub-like three panes:
- **Left:** rooms with unread / alert badges; **order log** (`O-nn` / `SO-nn` linked to the
  threads citing them); **"Needs you"** inbox of push-level items; Pause board.
- **Middle:** the room header (steward status on / restarting / offline, home host) and its
  thread list (state, assignee, age, last activity; loop-breaker and failed flags; filter
  by state); room feed below.
- **Right:** the thread: header (state, requester, assignee, cited orders) and posts
  rendered as markdown with images inline, live via `/stream`.
- **Directory page:** live charters (who is on, which host, which branch, wakes/hour).
- **Jump to agent** becomes "running on `<host>`" plus a link to that machine's GUI; live
  session logs stay in the GUI.

**Acting without a compose box:** "Ask aide about this" sends the request to an aide; the
aide's host (principal key) writes the order, so the order log stays harness-written. The
only action the board performs itself is **pause room / pause board** (stops all wakes),
signed with the admin key and logged as an Admiral order. `/admin` (bans, purge, emergency
post) stays as the escape hatch, not the everyday view.

**Tech:** static single-page app served by FastAPI (plain JS or something small like
Preact / htmx), no build step if possible; auth with the Admiral's admin token; private
network only. Replaces today's flat-feed `services/message_board/static/index.html`.

Telegram gets no board view; the aide summarises on request (the phone can use the web app).

### Networking

Board reachable only on a private network, per-member keys kept. Preferred: **self-hosted
open source**, i.e. **Headscale** (own coordination server, standard Tailscale clients);
fallback plain WireGuard. Needs a reachable always-on box (LAN, or a small VPS when away).
**Deferred** until a second machine joins.

### Build order

Each stage usable on its own:
1. **Board server core:** tables, the 5 tools, 3 wake rules, idempotent IDs, loop-breaker
   counters; remove the temp board and `_report_turn_end` auto-posts. -> today's peers work in
   threads.
2. **Aides + order log:** reserved `aide_` handle (principal key), `O-nn`/`SO-nn`, citation
   checks, interrupt scope, Telegram as a normal aide. -> Admiral instructs via aides with
   provenance.
3. **On-demand workers:** one per thread, thread folders, worktrees, soft sandbox,
   waiting -> exit -> respawn, crash backoff, per-host cap. -> aides delegate by opening
   threads.
4. **Stewards:** spawned with rooms, roster, restore from `state.md`, timer tick, setup
   recipes, housekeeping, cross-host requests. -> always-on crew.
5. **Board web app + markdown mirror** and archiving (a plain read-only thread view may move
   earlier for debugging stages 1-4). Making the board a Task Scheduler service belongs in
   stage 1, with the temp board removal.
6. **`#memory` room** replacing the memory root (last: it replaces a working system).
7. **MCP board server** for Claude Code / Codex (urgent by stage 6).
8. Deferred: Headscale, hard OS sandbox, separate host process, real kill.

## Rejected / changed

- Separate ticket tracker (2026-10-21): reversed 2026-11-11; threads replace tickets.
- Admiral-defined office roster: offices emerge from charters.
- Hub-and-spoke through an aide only: mesh, every thread visible to aides.
- Rich thread model (intent-tagged posts, reactions, structured fields): trimmed.
- Ray / separate daemon now: GUI is the host.
- Always-on residents per project / serial per-agent thread queue: only stewards are always
  on (coordinate only); workers spawned per thread.
- Private temp board fallback (2026-11-12): removed; offline = buffer and reconnect.
- Separate memory root / black_grimoire (2026-11-12): replaced by the `#memory` room.
- Posts and threads as plain markdown files as the source of truth (2026-11-12): database
  stays truth, markdown is a host-written mirror and archive.

## Carried over (still needed)

Multi-machine: idempotent request IDs on writes, push (`/stream`) + pull wake, MCP board
server for Claude Code / Codex. Prior art: Beads (`bd`) for schema and "ready work" queries.

## Open

- How the build order interleaves with the effect kernel (proposal 1) and context folding
  (proposal 2).
- Housekeeping before building: replace TODO.md "Multi-agent follow-ups" / "Message board
  follow-ups" with the agreed work; write an implementation plan (board server first);
  rewrite `main_system.md` and board tool text when the new tools land.
