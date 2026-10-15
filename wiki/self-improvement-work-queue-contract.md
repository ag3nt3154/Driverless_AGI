---
title: 'Self-improvement selection must match the maintained TODO'
description: 'R27: improve-yourself scans a Work Queue absent from current TODO; align candidate intake and define empty-queue behavior.'
tags: [improve-yourself, review-session, TODO, Work-Queue, R27, selection, acceptance]
updated: 2026-10-15
---

Source-inspected at main `db8dde97138c3d67b9c44121f8ce2cce07b5bfca`; no provider or self-improvement run invoked.
The workflow's Step 1 requires `## Work Queue`, review-item/priority tags and Source plan
links. Current TODO instead contains In progress and prose follow-ups. Review-session writes
analysis/report/plan artifacts without defining a shared queue handoff. No missing-queue
branch is specified. The baseline/candidate improvement workflow itself already exists.

Repair proposal: align selection with the actual TODO shape or maintain one explicit queue
contract, and report no eligible candidate before launching experiments. S16 extends the
existing flows with selected finding ID, reviewed revision, reproduction/acceptance checks
and deduplication. These are proposals; report publication does not authorize implementation.
Use the normal approval workflow and retain the Admiral's final apply decision.

Reports: [open findings](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-14.md),
[improvement suggestions](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-14.md).

## Resolved 2026-10-15

Step 1 now reads `## In progress` in TODO.md: top-level `- **Title**` bullets, nested
follow-ups and review finding IDs are candidates, with stated exclusions, a source identity
(`TODO.md › group › item` or `report › R##`), ranking, an `ask_user` choice of the top three,
and a stop on no eligible candidate. Step 12 records the source and moves it to `## Completed`.
`tests/test_improve_yourself_intake.py` fails if the workflow names a section TODO.md lacks.
