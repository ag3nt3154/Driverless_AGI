# Dagi suggestions — 2026-10-05

Proposals for an agentic harness supporting sustained work, measured self-improvement and
understandable recovery. They do not authorize implementation. Reviewed main at
6deff1c409f6e7cf692e73952ec9ef8b195ceb7a and its working files.
The October 3 report was renamed and refreshed in place.

## Current foundation

RequestExecutor, public loop properties, persisted revisions and TurnBoundaries are stronger
foundations than the previous review. Extend their contracts into adapters:
[today's review](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-05.md) reproduced
scheduler false success, dropped Telegram handoffs and blocked answer dispatch.

Campaign remains absent; reconcile the iteration-engine branch before reusing its design.
The [documented improve-yourself workflow](C:/Users/alexr/Driverless_AGI/README.md:1112)
already describes baseline/after comparisons in isolated snapshots. S3/S8 extend that
direction; its end-to-end execution was not tested here. Preserve the standing yolo-only
product decision.

## S1 — One owned run with an explicit outcome

**Improvement:** Give frontends, scheduled tasks and children a supported
start/status/steer/cancel/await-stopped contract and explicit terminal outcome.

**Issue addressed:** R4/R8/R10 show incompatible meanings of timeout, completion and
failure. A PID and returned string cannot retain context identity or prove execution stopped.

**Smallest useful version:** Add stable run identity and an outcome containing terminal
reason, final text, diagnostics and artifact references. Retain branch/generation metadata
through child resume. Distinguish wait timeout from execution deadline. Prototype with
scheduler and child resume before migrating all UIs.

**Acceptance:** Ghost exhaustion is recorded as failure; immediate and resumed results use
the same generation check; no owned execution survives reported deadline enforcement;
output drains even when its diagnostic log is unavailable.

## S2 — Durable objectives and an attempt journal

**Improvement:** Persist objective, acceptance criteria, phase, next action and attempt
evidence independently of conversational summaries.

**Issue addressed:** Sustained work needs restart continuity and evidence of completion.

**Smallest useful version:** Begin with one coding objective and one acceptance command.
Append attempt-start before execution, then running/verifying/terminal events with code
identity and artifacts. Inspect interrupted attempts before replaying non-idempotent
operations. Reconcile campaign's existing schema before introducing a shared store.

**Acceptance:** Restart between stage pairs without losing evidence or double-counting.
Distinguish agent-reported completion from command-verified acceptance. Token, wall-time
and repeated-failure limits yield explicit outcomes. Unknown provider costs remain visible.

## S3 — Measured self-improvement with retained evaluators

**Improvement:** Extend the existing improvement workflow with fixed behavioral fixtures
and retained baseline/candidate evidence.

**Issue addressed:** Structural metrics can reward shorter code while adapter semantics
regress. Core tests passed in this review while boundary probes reproduced defects.

**Smallest useful version:** Retain fixtures for pairing, recovery, scheduler outcome,
child resume, stdout draining, final delivery and question routing. Separate candidate work
from evaluator code/holdouts. Compare the same effective configuration and retain commands,
exits, artifacts and failure classifications. Build on
[dagi_eval](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py) and improve-yourself.

**Acceptance:** A lifecycle or delivery regression rejects a candidate even if code size or
cost improves. Evaluator modification is an integrity failure. Setup failures are distinct
from application regressions. Provider-dependent claims require repeated comparable runs.

## S4 — Reproducibility manifests and experiment history

**Improvement:** Retain effective inputs and rejected hypotheses for each attempt.

**Issue addressed:** HEAD alone did not describe this review's initial merge state.
Prompts, tools, skills, dependencies and fixtures also affect comparisons.

**Smallest useful version:** Save commit, working-diff hash, index/conflict state, effective
model/tools, prompt/skill hashes, interpreter, evaluator identity, commands and artifact
references. Exclude API keys and environment secrets. Link hypotheses and rejection reasons
to that manifest so later work avoids disproven approaches without new evidence.

**Acceptance:** Comparisons disclose different input states and missing evidence. Scored
code survives temporary workspace deletion. Retrieval distinguishes historical experiments
from the latest verified configuration.

## S5 — A task view that explains progress and recovery

**Improvement:** Show objective, phase, active children, verified result, queued steering
and the next useful recovery action.

**Issue addressed:** Progress becomes misleading when final delivery disappears or
completion appears without verification evidence.

**Smallest useful version:** Build a compact panel and milestone timeline on existing
[process-state events](C:/Users/alexr/Driverless_AGI/agent/process_state.py) and steering,
bound to S1/S2 identities. Display wait timeout, cancellation, stale context and failure
distinctly. Keep artifact/diagnostic links after failure. Give Telegram the same concise
final outcome and artifact references.

**Acceptance:** Scripted waits, tools, compaction, questions and recovery show real state.
Final handoffs arrive exactly once. Verified acceptance links its evidence. Background
notifications occur on meaningful changes or required action.

## S6 — Capability preflight with one actionable failure

**Improvement:** Expose effective environment and working capabilities before dependent tasks.

**Issue addressed:** Earlier reviews found shell and converter retries. Importability does
not prove working conversion; this run's WebEngine checks were sandbox-sensitive.

**Smallest useful version:** Report resolved interpreter, shell contract, tool availability
and converter-service health with bounded smoke fixtures. Reuse configuration introspection
and the existing Windows argv/stdin proposal. Preserve the earlier decision against generic
multi-step tool chains; use preflight and small native helpers rather than a workflow language.

**Acceptance:** Unavailable conversion produces one actionable result rather than identical
retries. Shell examples match execution. Fixtures distinguish missing capability from failed
tasks. Document conversion was not retested here; October 3's dependency issue is historical.

## S7 — Checkpoints that survive compaction and revision

**Improvement:** Keep verified task facts outside lossy summaries and qualify memory by
source, revision and verification status.

**Issue addressed:** R6's persistence is fixed, while durable objective continuity and
truthful memory still need explicit evidence. Historical findings can otherwise masquerade
as current defects.

**Smallest useful version:** Derive checkpoints from S2/S4: objective, criteria, revision,
verified result, blockers and artifacts. Summarize reasoning around them. Extend planned
memory-refresh to consolidate duplicates and superseded claims, retaining provenance.
Implement events-log restore together with tool-pairing repair and interruption policy.

**Acceptance:** Repeated compaction/restart preserves objective and latest verified revision.
Retrieval labels proposed, confirmed, resolved and historical claims. Saved revision reload
matches live history; save failure remains visible.

## S8 — Promote review probes into adapter contract fixtures

**Improvement:** Turn repeatable boundary reproductions into a maintained contract corpus.

**Issue addressed:** Core run contracts are strong, but scheduler tests omit runtime
execution, and Telegram delivery/dispatch defects survived previous reviews.

**Smallest useful version:** Promote today's probes into regression tests as each repair
lands. Use a fake provider, delivery sink and controlled worker to drive the real scheduler
and Telegram dispatch path. Assert outcomes, delivery counts, answer routing, cleanup and
disk/live equivalence. Use existing pytest; link review IDs to fixture names.

**Acceptance:** A fixture fails on the current defect and passes only with correct behavior.
Adapters agree on the same core scenario. Infrastructure errors report separately.
Future reviews can check verified closure rather than repeatedly rediscovering the defect.

## Sequence and measures

1. Repair R4/R10 and Telegram R11/R12; preserve R2/R6's verified contracts.
2. Repair R8/R9/R13 and extend S1 through these changes. Add S8 fixtures alongside repairs.
3. Add S2 objectives and S4 manifests; prototype S5 on those records. S6 is a bounded
   backlog opportunity under the project's normal implementation workflow.
4. Connect S7 checkpoints and extend S3's existing improvement workflow.

Measure verified acceptance, false-success rate, final-delivery failures, question-answer
latency, cancellation latency, recovery success, stale-result rejection and repeated failed
hypotheses. Record cost per verified outcome with missing-cost cases explicit. Establish
baselines before choosing numerical targets. No external framework migration is required.

