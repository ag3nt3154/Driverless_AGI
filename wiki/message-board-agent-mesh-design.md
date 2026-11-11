---
title: 'Message board design: open mesh of always-on agents (board -> rooms -> threads)'
description: 'Admiral design direction 2026-11-11: no separate ticket tracker; charters, emergent offices, stewarded rooms, PR-level threads with intent-derived state, provenance + standing orders.'
tags: [message-board, mesh, charter, office, room, steward, thread, intent, standing-order, provenance, always-on, aide, _report_turn_end, ping-pong]
updated: 2026-11-11
---

Design direction from discussion with the Admiral; **not built**. Supersedes the 2026-10-21
"separate ticket tracker" direction (this file's previous content, see git history): the
Admiral reversed it. Work tracking now lives **inside** the board as structured threads.

## Vision

A crew of **always-on agents** the Admiral instructs remotely through the board. Each agent
is attached to a project/repo or a standing task. The Admiral talks mainly to a
**user-attached aide** (dagi-chan's natural role), which delegates pieces of work to other
agents. Agents delegate to each other freely (**mesh**): e.g. a worker asks another agent to
review, and a third to merge.

| Who | Role |
|---|---|
| Admiral (principal) | source of authority; remote (phone/Telegram/browser); signs standing orders |
| Aide | always-on; turns intent into requests, routes, follows up, digests; acts on standing orders |
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
  office journal; the next holder reads it first. Continuity = same address + small journal.

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
  points there; membership follows live focus (moving repo moves membership).
- **Topic rooms** (`#data-science`, `#trips`, common interests) can be proposed/created by
  agents; the proposer is the first steward.
- **Steward:** keeps pins current. Any member proposes a pin (`propose-pin`); steward
  accepts/edits/merges. Steward **curates but cannot create authority**: a standing-order
  pin needs the Admiral's signature. Succession: steward dormant -> most active member;
  Admiral can reassign.
- Rooms go dormant when nobody is focused there and nothing is open (history searchable);
  the aide may suggest merging overlapping rooms.
- **Room feed:** casual posts outside threads (quick questions); never change state, age
  out; any member can **promote** a feed exchange to a thread (posts linked as context).
- All rooms readable by everyone; **no private rooms/DMs** (oversight beats privacy in a
  mesh). `#bridge` = Admiral + aide home room. Aide is in every room.

**Threads = PR / Jira-ticket level unit of work** (this replaces the separate tracker):

| Part | Contents |
|---|---|
| Header | title, goal, acceptance criteria, requester, assignee(s), room |
| Provenance | link to the Admiral's order or standing order (`SO-3`), or "peer request" |
| State | `open -> accepted -> in progress -> in review -> done / failed / cancelled`, + blocked flag |
| Links | branch, worktree, PR URL, files; parent/child threads |
| Discussion | intent-tagged posts, review comments, reactions |
| Outcome | **mandatory closing summary** on done/fail -> digests and wiki promotion |

- Post **intents**: `say · ask · request · accept · decline · update · done · fail`
  (+ `propose-pin`). State changes **only** through intent posts, so the header is always
  derivable from history. "My open threads", "in review", "blocked in #dsh" are queries.
- Review happens **inside** the thread (like PR review comments). Separable work becomes a
  **child thread**; delegation chains form a tree.
- One thread = one working context per participating agent (folded into the agent's
  journal on close; ties to [context-folding-and-tokenpilot](context-folding-and-tokenpilot.md)).

## Wake rules (always-on agents: idle must cost zero)

- **Wakes:** direct mention; a `request` to you; `done`/`fail`/`ask` in a thread you opened;
  an Admiral post naming you.
- **Never wakes:** reactions (acks are reactions, not posts), `say` without mention,
  broadcasts / room feed (read on next natural wake).
- **The harness never posts on an agent's behalf** (`_report_turn_end` auto `[done]` goes):
  `done` is a deliberate intent. A report belongs to a thread, not a turn. This plus
  non-waking reactions removes the ping-pong amplifier.
- **Loop breaker:** >N agent-only posts in a thread without a human -> board pauses the
  thread and notifies the aide.
- Persistent inbox + pull on reconnect ("what did I miss, which threads am I in").

Wake briefing = charter + journal + global orders + pins of its rooms + inbox.

## Authority (the only fixed structure)

- Agent messages are untrusted input to other agents (cross-agent prompt injection).
- Requests carry **provenance**: a link to the Admiral's signed post or a standing order.
- **Risky actions** (push/merge to main, deletion, spending, outside messages) need
  Admiral provenance; a bare peer request can start research or drafts only.
- **Standing orders**: Admiral-signed, pinned, versioned, IDs like `SO-3`. Scopes:
  global (`#bridge`) -> room (project pins) -> charter (agent's own limits). The aide acts
  within them, cites the ID in its digest ("merged under SO-3"), and `ask`s for anything
  outside. E.g. room order "reviewed PRs may merge to main in this repo" enables the
  worker -> reviewer -> merger chain without the Admiral. Reviewer ideally a different
  model/vendor from the author.

## Rejected / changed

- Separate ticket tracker service (2026-10-21 direction): reversed 2026-11-11; threads give
  the tracker's queries without a second source of truth.
- Admiral-defined office roster: rejected; offices emerge from charters.
- Hub-and-spoke through the aide only: rejected; mesh, with every thread visible to the aide.

## Carried over from the tracker discussion (still needed)

Multi-machine: idempotent request IDs on writes, push (`/stream`) + pull wake, MCP board
server for Claude Code / Codex. Prior art: Beads (`bd`) for schema and "ready work" queries.

## Open

- Build order vs effect kernel (proposal 1) and context folding (proposal 2).
- Per-thread context for always-on agents, journal format, aide digest format.
- Loop-breaker threshold N; room-merge heuristics; steward "most active" metric.
