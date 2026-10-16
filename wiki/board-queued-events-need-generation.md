---
title: 'Board switching must reject obsolete queued GUI events'
description: 'R22 queued board events repaired and verified; R30 still needs source-board identity for attachment jobs and completions.'
tags: [BoardController, board_post, Qt, generation, queued-signal, mentions, rebind]
updated: 2026-10-16
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

## October 14 refresh

Still open at main `db8dde97138c3d67b9c44121f8ce2cce07b5bfca`. Added purge events share the same pre-emit generation gap.
Fresh offline probe queued old post #99 plus all-history purge through #500, switched through
the actual controller, and seeded new-board card identity #7. Real Qt delivery woke #99;
the actual MessageBoardView.remove_purged method removed #7 from the fake card storage.
Clients, settled snapshot and card storage were stubbed; no real cards, traffic or agent work.
Carry event identity into the GUI slot for purges as well as posts/status before admission.
Evidence: `C:/Users/alexr/.codex/visualizations/2026/10/14/01a13a2e-5379-7132-8195-5f595075ddad/board_boundary_probes.py` and `board_boundary_results.json`.
Focused GUI checks: 65 passed. Existing fixtures do not cover this queued switch ordering.

## Resolved 2026-10-15

`bridge.board_post`, `board_purge` and `board_status` now carry `(generation, payload)`.
`BoardController._on_*_event` slots drop any event whose generation is not current before
rendering, waking agents or removing cards. Snapshot posts and the live cursor commit together
on the GUI thread via `_snapshot`, so a stale snapshot cannot move `_live_after`. Worker error
statuses are tagged with the generation at `_run_worker` time. Regressions in
`pyside_gui/tests/test_board_controller.py` queue old post/purge/status/snapshot from a worker,
bump the generation, then process events. In-flight attachment downloads from cleared old
cards still resolve via the current client (not addressed).

## October 16 verification and attachment residual

At `a53f6eabe9d684b884ec14c98aab3f8312d4abac`, the focused controller regressions pass for obsolete queued post/purge/status
and snapshot events. R22 is removed from the open report. R30 remains separate: downloads
queue only attachment IDs and choose runtime.client at execution; completion resolves the
current card by post ID. A real pool/controller-method probe with fake clients routed an
old queued request to the new board. A real offscreen view/future probe delivered an old
path to a replacement card with colliding post/attachment IDs while its future was pending.
No network, input or real files; all pool threads joined. Collisions were constructed.

Proposed repair: bind source client/board generation and expected metadata at submission;
cancel obsolete queued work, retain client ownership through active completion, and check
generation plus card identity before delivery. Existing event guards must remain intact.
[Probe](C:/Users/alexr/.codex/visualizations/2026/10/16/01a144a3-a300-71c0-ae87-57f26f2608ca/attachment_probe.py), [results](C:/Users/alexr/.codex/visualizations/2026/10/16/01a144a3-a300-71c0-ae87-57f26f2608ca/attachment_results.json).
