---
title: 'RPA replay needs coverage, revision and stop ownership'
description: 'Review R23–R26: partial/failed replay can verify, edits can verify unexecuted YAML, expectation timeout repeats actions, and cancellation releases ownership before stop.'
tags: [run_workflow, mark_verified, workflow_hash, for_each, DesktopLock, cancel, R23, R24, R25, R26]
updated: 2026-10-16
---

Open review findings at main `ff18da869a8a1885f3ed7d3851cb3c7d0e40e458`.
These are repair proposals, not approved implementation decisions.

- **R23:** on_fail=continue produces a failed step but overall ok; verify then permits
  whole-workflow approval. A verify run starting at the last step also permits approval
  of the unexecuted prefix. Require complete clean coverage or a qualified partial receipt.
- **R24:** mark_verified hashes the file at completion rather than the loaded workflow
  that ran. A controlled edit inside a fake driver's act verified the replacement and
  pre-approved its unexecuted confirm:once step. Bind evidence, verification and approval
  to the admitted revision; compare/update under serialized store ownership.
- **R25:** expectation timeout retries the whole resolve/act/check sequence. An approved
  click executed twice with retry=1 and an absent expectation. Separate post-action
  observation from mutation retry; retain uncertain completion and reconcile before replay.
- **R26:** ComputerUseInteractWithWindowTool.cancel sets a flag and releases DesktopLock
  immediately. A gated first for_each action stayed live while B acquired its lock; A then
  completed all three items with status ok despite cancellation. Hold the lock until
  acknowledged stop and check cancellation before every item/action admission.

The probes use the real interpreter/store/temporary lock with FakeDriver. They perform no
OS input, keyboard hook, external request or real payment/send. Controlled interleavings
prove ordering, not user encounter rates. Workers are released/joined and temp stores removed.

Evidence: `C:/Users/alexr/.codex/visualizations/2026/10/12/01a12ff5-eea2-7331-bb17-fd980fad5b50/`
contains `review_probes.py`, `review_probe_results.json`, and `verification-final.log`.
Focused offline/Qt controller verification: 810 passed, three known R15 template failures,
24 skipped. Desktop/hook tests stayed disabled. No full suite or live cross-app repair run.

Reports were edited in place and renamed from October 11 to October 12. R20 was removed
after owner-scoped cancellation regression verification; R8 metadata and R21 closure remain.
The 15-item roadmap recognizes shipped RPA and adds a read-only replay preflight preview,
extending current APIs rather than reproposing recording/replay or the Workflows rail.

## October 14 refresh

All five assertions for R23–R26 still reproduce at main `db8dde97138c3d67b9c44121f8ce2cce07b5bfca` with FakeDriver and
temporary stores/lock. No live OS input or hook. Source paths are unchanged from October 12.
Fresh probe and JSON: `C:/Users/alexr/.codex/visualizations/2026/10/14/01a13a2e-5379-7132-8195-5f595075ddad/review_probes.py`, `review_probe_results.json`.
Reports renamed in place to October 14: 21 open findings and 16 unbuilt extensions; the new
finding concerns improvement intake (R27), not an RPA repair. Focused board/GUI/plan checks:
379 passed, three known missing-template failures, two opt-in skips. Project dagi interpreter
now resolves under miniconda3 rather than the historical anaconda3 directory.

## October 15 refresh

All five R23–R26 assertions reproduced again at main
`6b5b5a9534ce8fbd9af864b4d362cd6774bfc593` with real interpreter/store/temporary lock
and FakeDriver. No desktop input, hooks or provider calls; gated workers were joined.
The [probe](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/review_probes.py)
and [results](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/review_probe_results.json)
retain the evidence. Reports were updated/renamed in place to October 15: 23 open findings,
17 unbuilt improvements. Focused config/board/plan and Qt checks: 394 passed, three known
plan-template failures, two opt-in skips. No RPA implementation changed.

## October 16 refresh

All five R23–R26 assertions reproduce at `a53f6eabe9d684b884ec14c98aab3f8312d4abac` with the real interpreter/store/lock
and FakeDriver. No input/hooks/providers; gated workers joined.
[Results](C:/Users/alexr/.codex/visualizations/2026/10/16/01a144a3-a300-71c0-ae87-57f26f2608ca/review_probe_results.json).
