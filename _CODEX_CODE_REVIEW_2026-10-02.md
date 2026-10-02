# Dagi code review — 2026-10-02

## Scope and conclusion

First run of this automation. Reviewed checkout: `task/iteration-engine` at
`6917b131d2e8789e30e27adc343cf6875c889e8e`. This includes the campaign engine awaiting
merge; it is not a review of `main` alone. Existing untracked meme images were left intact.
This report proposes fixes; no application code was changed.

Dagi has useful foundations: typed tool side effects, a session event projection, separated
campaign evaluation, atomic campaign-log replacement, and process containment for campaign
children. The most consequential gaps are at lifecycle boundaries: completing a tool batch,
rejecting an invalid experiment, timing out work, and recovering interrupted state.

Seven findings follow, ordered by impact. P1 means prioritize before relying on the affected
unattended flow; P2 means a reliability or maintainability follow-up. These are review
priorities, not claims that every entry point is unusable.

| ID | Priority | Finding | Evidence / prior status |
|---|---|---|---|
| R1 | P1 | Holdout tampering can still promote a candidate | New reproduction in this review |
| R2 | P1 | Multiple end-turn calls leave unmatched tool calls | New reproduction in this review |
| R3 | P1 | Scheduled tasks cannot construct AgentLoop | Reconfirmed September 6 finding |
| R4 | P1 | Scheduler timeout does not stop its worker | Reconfirmed September 6 finding; latent behind R3 |
| R5 | P2 | Pre-archive interruption loses work and attempt accounting | New reproduction in this review |
| R6 | P2 | Garbled-response revision is not persisted | Reproduced; extends known event-durability concern |
| R7 | P2 | Core orchestration remains too large and tightly coupled | Source inspection and AST size inventory |

## R1 — Holdout tampering can still promote a candidate

**Finding:** `_holdout_if_better` treats evaluator-integrity failures as ordinary optional
holdout failures, allowing the candidate to become the incumbent.

**Issue:** In [campaign/engine.py:187](C:/Users/alexr/Driverless_AGI/campaign/engine.py:187),
every `StepFailed` is logged and converted to `None`. `_finalize` then returns `completed`
with the validation score. A temporary copy of the toy campaign, with perfect validation
predictions and inference that changes holdout labels only during the holdout pass, produced
`completed`, `accepted`, incumbent trial `1`, and `fingerprint_ok=False`. The detector worked;
the outcome handler discarded its significance. The next run will refuse the changed
fingerprint, but the invalid trial has already been promoted and rebuilt into the workspace.
This differs from the intentional policy that holdout *quality* does not gate acceptance.

**Suggested solution:** Propagate `evaluator_modified` out of the optional-holdout handler
and convert the entire trial to a failed integrity outcome in `_finalize`. Keep ordinary
holdout inference/evaluation failures non-gating if that remains the chosen policy. Reuse
the distinction already made by `_rescore_holdout`/`_abort_if_tampered`. Add a regression
where holdout inference alters a label or evaluator: the trial must fail, the prior
incumbent must remain selected, and the fingerprint mismatch must remain visible.

## R2 — Multiple end-turn calls leave unmatched tool calls

**Finding:** A tool batch with two `END_TURN` results records only the last result.

**Issue:** [agent/_tool_dispatch.py:119](C:/Users/alexr/Driverless_AGI/agent/_tool_dispatch.py:119)
overwrites the single `deferred_end_turn` tuple on every end-turn result. Each call was
already logged, but earlier deferred results never reach `bookkeep_tool_call`. A mocked
provider response containing two `write_handoff` calls returned the second answer and
logged calls `end1`, `end2`, with a result only for `end2`. The next conversation request
therefore contains an assistant tool-call batch without all corresponding tool results,
and a provider enforcing complete tool pairing can reject it. The event log also
misrepresents a completed call as unfinished.

**Suggested solution:** Define one deterministic turn-ending result per batch and record
an explicit result for every call, including redundant end-turn requests. Complete all
bookkeeping before emitting the final callback. Test duplicate handoffs, mixed end-turn
tools, and an ordinary tool after an end-turn request; assert one result per call ID and
one final callback, including after another user turn and persisted-history replay.

## R3 — Scheduled tasks cannot construct AgentLoop

**Finding:** The standalone scheduler still passes the unsupported `tracker=` keyword.

**Issue:** [scheduler/runner.py:98](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:98)
calls `AgentLoop(..., tracker=tracker_session)`, while
[agent/loop.py:64](C:/Users/alexr/Driverless_AGI/agent/loop.py:64) accepts `_tracker`.
Binding the real constructor signature reproduced `got an unexpected keyword argument
'tracker'`. Construction occurs outside the configuration exception handler and before
the worker's exception capture, so the first due task aborts the scheduler without a run
failure record. The existing scheduler tests cover models, tracking and schedule tools,
but do not exercise this construction path.

**Suggested solution:** Correct the wiring, and include tracker/loop initialization in the
per-task failure boundary so other due tasks can proceed after a recorded startup failure.
Add a scheduler smoke test using the real constructor contract with provider calls mocked.
In a later refactor, give frontends a supported runtime/session factory instead of coupling
them to private constructor arguments. This is an open finding from the September 6 review,
not a newly introduced campaign regression.

## R4 — Scheduler timeout does not stop its worker

**Finding:** A scheduler timeout records termination while execution is still alive.

**Issue:** [scheduler/runner.py:111](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111)
performs a timed `thread.join`, then calls `loop.finish()` before checking liveness.
[AgentLoop.finish](C:/Users/alexr/Driverless_AGI/agent/loop.py:1062) only writes a session
snapshot. It does not cancel the provider call, tool, or worker. After substituting a
controlled fake loop to get past R3, the real runner recorded `timeout` and called `finish`
while the worker was still waiting. That worker can continue modifying a project while
the scheduler moves on to another task. The probe released and joined its test worker;
it did not leave background work running.

**Suggested solution:** Run scheduled jobs in an owned subprocess with bounded process-tree
termination, reusing the existing [campaign process runner](C:/Users/alexr/Driverless_AGI/campaign/process.py:57)
where appropriate. Finalize the outcome only after execution has stopped, and preserve
partial session evidence. Test timeout during provider wait, a long tool, and a descendant
process; the next task must not start while owned execution survives. This also reconfirms
the September 6 review and is currently masked by R3.

## R5 — Pre-archive interruption loses evidence and attempt accounting

**Finding:** Campaign recovery covers completed archives but not an attempt still running
when the parent is interrupted.

**Issue:** [campaign/engine.py:124](C:/Users/alexr/Driverless_AGI/campaign/engine.py:124)
does not persist a started attempt before launching it. `_execute_trial` archives only after
launch and evaluation return, and [recover](C:/Users/alexr/Driverless_AGI/campaign/workspace.py:133)
recognizes only unrecorded archive directories. A launcher probe wrote a partial experiment
note and raised `KeyboardInterrupt` before archiving. The persisted attempt count stayed at
zero; on retry, `rebuild_workspace` removed that note before the next launcher ran.
A real process crash additionally requires the documented manual lock recovery. Repeated
interrupted attempts can consume work without consuming the campaign's attempt budget.

**Suggested solution:** Persist a small started-attempt record before launching, including
attempt ID, parent trial and workspace identity. On recovery, preserve the interrupted
workspace before rebuilding it and transition the attempt to an explicit interrupted
outcome. Define that outcome's budget semantics. Test interruption before launch, during
agent work, during evaluation and between archive/log writes; recovery must be idempotent
and must neither lose evidence nor double-count an attempt.

## R6 — Garbled-response revision is not persisted

**Finding:** Automatic empty-response recovery removes events in memory but leaves them
in the append-only session file.

**Issue:** [agent/loop.py:884](C:/Users/alexr/Driverless_AGI/agent/loop.py:884) calls
`revise_last_step` without persisting the revision.
[SessionLog.revise_last_step](C:/Users/alexr/Driverless_AGI/agent/session_log.py:273)
deletes in-memory events and rebuilds its projection without an append notification.
Unlike the explicit TUI/PySide history-revision paths, this recovery path does not rewrite
the file. A mocked-provider probe with three empty responses, a stubbed compactor, a real
append sink and then a successful handoff left zero empty assistant events in memory but
three on disk (8 versus 20 total events). Replaying the event file can reintroduce discarded
history and disagree with the active surface. Normal UI restore currently uses tracker
snapshots, so this finding is specifically about event-file fidelity and event-based recovery.

**Suggested solution:** Centralize revision persistence. Prefer a durable revision event
understood by the projector; an atomic snapshot rewrite can be an interim solution if all
callers use it consistently. Add a production-path garbled-recovery test that reloads the
event file and compares its derived messages and open-turn/step state with the live log.
Existing revision tests manually call `write_session`, so they do not cover this omission.

## R7 — Core orchestration remains too large and tightly coupled

**Finding:** File extraction has not produced sufficiently narrow lifecycle interfaces.

**Issue:** The AST inventory scanned 195 Python files under `agent`, `tools`, `campaign`,
`scheduler`, `pyside_gui`, `tui`, and `tg`, excluding directories named `tests`. Five files
exceed the project's 500-line cap and nine functions exceed 100 source lines:

| Example | Measured size |
|---|---:|
| [agent/loop.py](C:/Users/alexr/Driverless_AGI/agent/loop.py) | 1,064 lines |
| [AgentLoop.run](C:/Users/alexr/Driverless_AGI/agent/loop.py:628) | 351 lines |
| [tools/subagent_main.py](C:/Users/alexr/Driverless_AGI/tools/subagent_main.py) | 744 lines |
| [pyside_gui/prompt_input.py](C:/Users/alexr/Driverless_AGI/pyside_gui/prompt_input.py) | 684 lines |

These counts include comments/docstrings, and no cyclomatic-complexity measurement was made.
`run` coordinates request retries, pause/steering, budget compaction, event boundaries,
garbled-response recovery, tool dispatch and completion. Extracted helpers still receive
the entire loop and access private state; GUI worker construction also uses `_tracker`,
`_session_log` and `_messages`. R2, R3 and R6 show concrete contract/durability gaps at these
boundaries, rather than line length being the sole concern.

**Suggested solution:** Introduce focused ownership boundaries incrementally: a request
executor for retry/cancel/stream completion, a turn coordinator for event boundaries, and
a tool-batch finalizer guaranteeing complete call/result pairing. Supply explicit context
or protocol objects instead of the whole loop. Start with contract tests for actual
frontends and failure paths; enforce size/complexity limits for changed functions without
undertaking a repository-wide cosmetic split.

## Verification and limits

- Focused existing tests: **183 passed**, one pytest-cache warning, in 65.26 seconds.
  Modules: `test_scheduler`, `test_campaign_engine`, `test_campaign_evaluation`,
  `test_campaign_workspace`, `test_agent_loop`, `test_session_log_revise`, `test_session_store`.
- Used `C:/Users/alexr/miniconda3/envs/dagi/python.exe -u -m pytest -q -p no:pytest-qt`
  with a fresh writable `--basetemp`. The initial attempt had 183 setup errors because
  pytest's default temporary root was inaccessible; none was counted as a code defect.
- Six offline probes confirmed R1–R6. Scheduler timeout used a fake worker; provider
  responses and compaction were mocked; campaign probes used temporary template copies
  and real local inference/evaluation subprocesses. Probe source:
  [review_probes.py](C:/Users/alexr/.codex/visualizations/2026/10/02/01a0fa21-067b-7f03-a3e9-ef7fdbc54ab3/review_probes.py).
- This was selective architecture and failure-path review, not exhaustive coverage of
  every file. No live model, Telegram, Prefect service, GUI interaction, full test suite,
  production soak test or real OS-crash test was run.
- Existing deferred work includes event-based interrupted restore, orderly GUI shutdown,
  session filename collisions, stronger campaign isolation, holdout acceptance policy and
  archive retention. These are not claimed as new discoveries or verified fixes here.

## Prior knowledge consulted

- [Architecture, updated 2026-09-27](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/architecture.md>)
  supplies background; several historical sections are superseded, so source code took precedence.
- [Broad review, updated 2026-09-06](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/broad-review-2026-09-06.md>)
  records R3/R4's earlier observations. Its first-snapshot restore claim is stale:
  current `load_raw_messages` selects the last snapshot.
- [Production review, 2026-09-15](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/production-review-2026-09-15.md>)
  and current [TODO.md](C:/Users/alexr/Driverless_AGI/TODO.md) identify deferred recovery work.

Suggested implementation order: R1/R2, R3/R4 together, R5/R6, then R7 alongside the affected
changes. See the [suggestions report](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-02.md)
for the broader iterative-harness roadmap.
