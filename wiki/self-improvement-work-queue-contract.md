---
title: 'Self-improvement selection must match the maintained TODO'
description: 'R27 intake remains repaired; open R31 masks a failing improvement subprocess when a session log exists.'
tags: [improve-yourself, review-session, TODO, Work-Queue, R27, selection, acceptance]
updated: 2026-10-19
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

Reports: [open findings](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-19.md),
[improvement suggestions](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-19.md).

## Resolved 2026-10-15

Step 1 now reads `## In progress` in TODO.md: top-level `- **Title**` bullets, nested
follow-ups and review finding IDs are candidates, with stated exclusions, a source identity
(`TODO.md › group › item` or `report › R##`), ranking, an `ask_user` choice of the top three,
and a stop on no eligible candidate. Step 12 records the source and moves it to `## Completed`.
`tests/test_improve_yourself_intake.py` fails if the workflow names a section TODO.md lacks.

## October 16 verification

At `a53f6eabe9d684b884ec14c98aab3f8312d4abac`, current TODO intake and live plan-format/worker-selection regressions pass.
R27/R15/R17 are removed from the open report. S16 now proposes revision-bound reproduction
and acceptance evidence beyond the shipped selection rules; S10 proposes runtime validation
of arbitrary attached plans beyond the shipped writer-example contracts. No candidate run
or implementation was authorized by report publication.

## October 17 review: runner failure is separate from repaired intake

At `902a083b782a725f929d91719512d46119e52fa9`, TODO selection contracts still pass.
New open R31: `.dagi/workflow/improve-yourself/run_test_task.py` captures child returncode
but ignores it when a new session log exists. A real local scratch main.py wrote a log
and exited 7; the actual runner CLI printed LOG and exited 0. Child stderr remained visible.
No provider or real improvement run was used; no candidate verdict was generated.

Proposed repair: retain evidence while reporting failed child exit/terminal outcome, and
make Steps 6/8 consume that status. Expected baseline failure differs from infrastructure
failure; candidate acceptance needs an independent check. Add CLI coverage for all four
exit/log combinations. This extends S3/S8/S16 and does not reopen repaired intake R27.
[Probe](C:/Users/alexr/.codex/visualizations/2026/10/17/01a14762-55a6-7d40-81ec-501147369932/improvement_exit_probe.py),
[results](C:/Users/alexr/.codex/visualizations/2026/10/17/01a14762-55a6-7d40-81ec-501147369932/improvement_exit_results.json).
Reports were updated/renamed in place: 21 open findings, 17 unbuilt extensions; 390 focused
tests passed. No Qt runtime checks today; documentation remains uncommitted.

## October 18 refresh

The improvement runner source is unchanged; R31 remains open with October 17 CLI evidence.
Current TODO-intake and writer/parser contract tests pass in the focused 396-test core run.
No improvement experiment, provider call or candidate approval was performed. Report
links above now target the October 18 in-place renames; the review contains 23 open findings
after adding peer-report R32/R33, and the roadmap retains 17 extensions beyond shipped work.

## October 19 refresh

HEAD and application sources remain at `918041c2`; no finding repair or remaining roadmap
extension shipped since October 18. Current report links target the October 19 in-place
renames: 25 open findings, 17 extensions. New R34/R35 concern snapshot-time peer-task loss
and upload/publication across a board switch; S8/S9/S13 extend their existing contracts.
234 focused board/peer tests passed. R31 retains its October 17 CLI evidence; no improvement
experiment, candidate verdict or implementation was performed.
