---
title: 'Board switching must reject obsolete queued GUI events'
description: 'R22: a generation check before emitting a Qt signal cannot reject a post already queued when the GUI switches boards.'
tags: [BoardController, board_post, Qt, generation, queued-signal, mentions, rebind]
updated: 2026-10-11
---

Review finding R22 remains open at main `3079386f6cc562e584608d97bed0024dfe0c6d8a`.
`BoardController._load_snapshot` checks the listener generation before emitting `board_post`.
The emitted object contains only the post, so `_on_post` cannot reject it after a board switch.
Switching increments the generation and rebinds all sessions but cannot withdraw queued signals.

The October 11 offline probe queued old-board post #99 from a worker, called the real switch
handler, then processed Qt events. The post appeared and the mention hook fired while the
session client pointed at the new board. Clients/listener and the settled new snapshot were
stubbed; Qt queued delivery and controller methods were real. No board traffic, provider
request or agent dispatch occurred. This controls an interleaving, not its frequency.

Suggested repair: carry generation plus board/runtime identity in snapshot, post and status
events and check them in the GUI slot before rendering or waking an agent. Commit snapshot
baseline/posts together on the GUI thread. Keep attachment provenance. A regression should
queue an old event, switch before processing it, and assert no render, wake or new-board fetch.
This is a proposal, not an approved implementation decision.

Fresh verification: 336 passes, three known R15 missing-template failures and two opt-in
clean-install skips; 55 focused Qt tests pass. Existing tests do not cover this queued ordering.
Evidence: `C:/Users/alexr/.codex/visualizations/2026/10/11/01a128a5-2829-73f1-a28a-648eb65c6cf3/`
contains `review_probes.py`, `review_probe_results.json` and `verification.json`.

Review reports remain one file of each kind, updated in place and renamed daily. Runtime
reproductions must keep their actual dates when source inspection carries findings forward.
SQLite now imports as 3.51.2; the October 10 environment blockage is historical.
