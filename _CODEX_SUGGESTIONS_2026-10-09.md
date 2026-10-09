# Dagi suggestions — 2026-10-09

Proposals for sustained agentic work, measured self-improvement and understandable recovery.
They do not authorize implementation. Reviewed main at 94ca6924880867924ca6a90b7d0ca510e8b601a6. The October 8
report was edited in place and renamed to October 9. Only unbuilt improvements or explicit
extensions of existing features are listed.

Code mode now executes Python tool scripts through the current registry; mechanical
multi-step execution is already built and is not a proposal. CLI UTF-8 output is fixed.
RequestExecutor, loop properties, persisted revisions, ordering tests, generation-aware
child resume, tolerant stdout draining, active-plan sidecars, process-state events, steering
receipts/cancellation and the documented improve-yourself baseline/after workflow already
exist. S1–S11 extend these facilities. Campaign is absent from this checkout; reconcile its
separate design before reuse. Central memory also reports a separate board/multi-agent
implementation; it is absent from this main checkout, so align S5 with it before designing
another UI. Preserve the standing yolo-only decision; code scripts do not require a new
workflow language or approval layer.

[Today's review](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-09.md) has 14 open
findings. New R18/R19 reproduce parent-side execution after script cancellation and lost
printed checkpoints on termination. Existing adapters remain open in unchanged source.
Focused tests: 155 passed, three known template failures. S1/S3/S8/S9 now include code-mode
lifecycle/evidence gaps; new S12 measures its effectiveness before promoting recipes.

## S1 — One owned run with an explicit outcome

**Improvement:** Give frontends, scheduled tasks and children a supported
start/status/steer/cancel/await-stopped contract and explicit terminal outcome.

**Issue addressed:** R4/R10/R18 show incompatible meanings of timeout, completion and failure.
R8 now preserves branch/generation through resume; its abandoned metadata remains ownership
debt. A PID alone cannot prove stopped execution or own all cleanup.

**Smallest useful version:** Add stable run identity and an outcome containing terminal
reason, final text, diagnostics and artifact references. Retain branch/generation metadata
through child resume. Distinguish wait timeout from execution deadline. Prototype with
scheduler, code mode and child resume before migrating all UIs. Include one admitted scheduler owner
(R16); an expired wait must not allow another owner while execution survives.

**Acceptance:** Ghost exhaustion is recorded as failure; immediate and resumed results use
the same generation check; no owned execution survives reported deadline enforcement;
no selected code-mode mutation begins after acknowledged cancellation;
preserve R9 tests proving output drains when its diagnostic log is unavailable. These child
contracts already exist; S1 extends ownership and outcomes rather than reimplementing them.

## S2 — Durable objectives and an attempt journal

**Improvement:** Persist objective, acceptance criteria, phase, next action and attempt
evidence independently of conversational summaries.

**Issue addressed:** Sustained work needs restart continuity and evidence of completion.

**Smallest useful version:** Begin with one coding objective and one acceptance command.
Atomically claim an attempt and append attempt-start before execution (R16), then record
running/verifying/terminal events with code identity and artifacts. Inspect interrupted
attempts before replaying non-idempotent
operations. Reconcile campaign's existing schema before introducing a shared store.

**Acceptance:** Restart between stage pairs without losing evidence or double-counting.
A concurrent scheduler cannot claim the same attempt. Distinguish agent-reported
completion from command-verified acceptance. Token, wall-time and repeated-failure limits
yield explicit outcomes. Unknown provider costs remain visible.

## S3 — Measured self-improvement with retained evaluators

**Improvement:** Extend the existing improvement workflow with fixed behavioral fixtures
and retained baseline/candidate evidence.

**Issue addressed:** Structural metrics can reward shorter code while adapter semantics
regress. Core tests passed in this review while boundary probes reproduced defects.

**Smallest useful version:** Retain fixtures for pairing, recovery, scheduler outcome,
child resume, stdout draining, final delivery, question routing, publication failure,
code-mode nested timeouts/cancellation and interrupted output capture. Separate candidate work
from evaluator code/holdouts. Include code_mode and the callable registry in comparisons.
Compare the same effective configuration and retain commands,
exits, artifacts and failure classifications. Build on
[dagi_eval](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py) and improve-yourself.

**Acceptance:** A lifecycle or delivery regression rejects a candidate even if code size or
cost improves. Evaluator modification is an integrity failure. Setup failures are distinct
from application regressions. Provider-dependent claims require repeated comparable runs.

## S4 — Reproducibility manifests and experiment history

**Improvement:** Retain effective inputs and rejected hypotheses for each attempt.

**Issue addressed:** HEAD alone does not describe a run with uncommitted work.
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
Final handoffs arrive once per confirmed local delivery; uncertain remote delivery is shown. Verified acceptance links its evidence. Background
notifications occur on meaningful changes or required action.

## S6 — Capability preflight with one actionable failure

**Improvement:** Expose effective environment and working capabilities before dependent tasks.

**Issue addressed:** Earlier reviews found shell and converter retries. Importability does
not prove working conversion; prior WebEngine checks were sandbox-sensitive; no GUI suite ran this time.

**Smallest useful version:** Report resolved interpreter, shell contract, tool availability
and converter-service health with bounded smoke fixtures. Reuse configuration introspection
and the existing Windows argv/stdin proposal. Use the existing code tool for bounded mechanical probes and small native helpers
for shell-specific cases; no additional workflow language is needed.

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
verified result, blockers and artifacts. Summarize reasoning around them. Consolidate duplicates and superseded claims in the current memory workflow, retaining
provenance. The disabled/removed memory_refresh capability is not a prerequisite.
Implement events-log restore together with tool-pairing repair and interruption policy.

**Acceptance:** Repeated compaction/restart preserves objective and latest verified revision.
Retrieval labels proposed, confirmed, resolved and historical claims. Saved revision reload
matches live history; save failure remains visible.

## S8 — Promote review probes into adapter contract fixtures

**Improvement:** Turn repeatable boundary reproductions into a maintained contract corpus.

**Issue addressed:** Core run contracts are strong, but scheduler tests omit runtime
execution, and Telegram delivery/dispatch defects survived previous reviews.

**Smallest useful version:** Preserve the R8/R9 regression tests that already landed.
Promote still-open scheduler/Telegram/publication probes as their repairs land. Use a fake
provider, delivery sink and controlled worker to drive real adapters. Assert outcomes,
delivery counts, answer routing, cleanup and disk/live equivalence. Use existing pytest;
link review IDs to fixtures. Add the R16 two-process admission scenario and R17 exact-name
worker-selection scenario, plus skill-format checks from S10. Add R18
controlled admission-versus-cancellation and nested-budget fixtures, and R19
print-before-timeout/kill fixtures; idle-script timeout tests do not cover these boundaries.

**Acceptance:** A fixture fails on the current defect and passes only with correct behavior.
Adapters agree on the same core scenario. Infrastructure errors report separately.
Future reviews can check verified closure rather than rediscovering the defect.

## S9 — Retained results and retryable artifact delivery

**Improvement:** Let a user recover a completed result when export or final delivery fails,
without paying for another agent run or repeating its tools.

**Issue addressed:** R14 records success before file publication; R11 drops the final
Telegram handoff. R19 additionally loses printed code-mode evidence on kill/timeout.
Computation, acceptance and delivery have different failure modes.

**Smallest useful version:** Retain final text and artifact references under S1's stable
run identity. Record a delivery receipt with destination, attempt, status and diagnostic.
Offer retry export with a new path and redelivery of the retained final message. Show
computed / verified / delivered separately in S5. Keep scheduler jobs runnable after an
individual publication error; never automatically rerun computation just to export it.
Retain code-mode partial output and its mutation ledger as incomplete attempt evidence;
never treat a checkpoint as verified completion.

**Acceptance:** An unwritable destination retains the result and reports delivery failure.
A corrected destination exports the same retained result without provider or tool calls.
File receipts identify the published bytes; Telegram receipts track successful messages
where available. A timeout with unknown delivery status stays explicit, since remote
exactly-once delivery cannot be guaranteed by a local flag. Resume preserves receipt history.

## S10 — Executable contracts for skill-produced plans

**Improvement:** Validate plans before they enter delivery, and catch skill-format drift
with a small repository-owned contract suite.

**Issue addressed:** R15 shows that deleting a template can break verification while the
writer's inline format and runtime parser evolve independently. The current writer example
omits status markers, which the parser reports as unknown. R17 additionally shows that
substring selection assigns the wrong subtask even when its exact name exists. Both
undermine the iterative harness.

**Smallest useful version:** Define the supported plan heading/marker/global-constraint
contract in one maintained fixture or format specification. Test the current inline skill
examples against parsing, subtask isolation, worker assignment and progress round-trip.
At plan association, report missing markers, empty criteria or unextractable subtasks as
precise diagnostics before work starts. Keep backward compatibility explicit for existing
plans; avoid loading personal global skills as test fixtures. Use the existing parser with
exact task identity or task number. Reject ambiguous partial names and duplicate identities
before assigning worker payloads (R17).

**Acceptance:** Changing the writer example incompatibly fails a contract test. Valid
plans preserve constraints and progress through worker/reviewer handoffs. Invalid plans
name the exact heading or missing field; they never silently appear to have no pending
work. An exact task title that is a substring of an earlier title still selects the intended task.
The three stale tests are updated to validate current behavior rather than removed.

## S11 — Schedule control and missed-run recovery

**Improvement:** Let the Admiral see what is running, why a schedule was skipped, and whether
a missed or interrupted attempt should run now, without editing YAML or rerunning all jobs.

**Issue addressed:** The scheduler exposes due times and completed history, while R16 shows
no admission ownership. Long work needs a visible policy for overlapping ticks and restart
recovery. A schedule interval alone cannot express these user decisions.

**Smallest useful version:** After R16's lock and S2's attempt identity, add per-task status
showing owner, attempt, last outcome and next due time. Default to skipping overlaps and
coalescing missed ticks into one pending attempt. Provide run-now and retry-interrupted actions
that use the same claim path. Reuse schedule models/history and S5's task view; avoid introducing
a separate workflow language or service. Keep export-only retry under S9.

**Acceptance:** Two triggers cannot start the same task. A blocked tick records why it was
skipped. Restart with a live owner cannot launch a replacement; confirmed owner death exposes
one recoverable interrupted attempt. Several missed ticks produce one pending run under the
default policy. Manual retry names the prior attempt and preserves its evidence.

## S12 — Measure code-mode effectiveness per verified task

**Improvement:** Record enough execution evidence to choose when code mode improves work,
and feed verified examples back into the existing improvement workflow.

**Issue addressed:** Script chaining is already shipped, but its advertised efficiency is
not established by passing functional tests. Compressing output can also hide evidence that
the next model step needs. A completed script is not proof that the coding objective passed.

**Smallest useful version:** After R18/R19, record script/registry identity, nested-call count,
durations, intermediate-result byte counts, returned bytes, output artifact and final task
acceptance. Use bounded artifact storage and redact sensitive results; full raw tool results
need not be duplicated. Compare matched code_mode on/off runs for two mechanical tasks with
the same provider/configuration and independent acceptance command. Explicitly admit code
in the benchmark allowlist for the enabled arm; its current tools list omits code, so toggling
code_mode alone cannot exercise it. Feed only accepted
examples and their limitations into S3/S4; keep ordinary tools available.

**Acceptance:** A shorter transcript with failed acceptance cannot win. Report observed
latency, tokens and context bytes separately; do not label estimated avoided requests as
measured savings. If prompt/tool configuration differs between runs, disclose it. Failed
scripts retain partial evidence without replaying mutations. No automatic recipe promotion
or new tool-chain language is needed.

## Sequence and measures

1. Repair R4/R10/R16/R18 and Telegram R11/R12; retain verified R2/R6/R8/R9 contracts.
2. Repair R3/R13/R14, add S8 regression fixtures and the minimal S9 retained-export path;
   repair R19 to retain interrupted script diagnostics.
   Extend S1 ownership to abandoned-child cleanup. Repair R15/R17 and establish S10's plan
   contract before relying on unattended delivery.
3. Add S2 objectives and S4 manifests; prototype S5 on those records. S6 remains a bounded
   capability-preflight opportunity under the project's normal implementation workflow.
   Add S11 once admission and attempt recovery have durable ownership.
4. Connect S7 checkpoints and extend S3's existing self-improvement workflow. Candidate
   promotion requires intact evaluator evidence and passing behavioral contracts.
   Measure shipped code mode through S12 before choosing examples to reuse.

Measure verified acceptance, false-success rate, final-delivery failures, question-answer
latency, cancellation latency, code-mode deadline overrun/partial-output retention, export recovery without recomputation, plan-contract rejection,
recovery success, duplicate-admission rate, exact task-selection accuracy, stale-result
rejection and repeated failed hypotheses. Record cost per verified outcome with missing-cost
cases explicit. Establish
baselines before choosing numerical targets. No external framework migration is required.

