# Dagi suggestions — 2026-10-11

Proposals for sustained agentic work, measured self-improvement and understandable recovery.
They do not authorize implementation. Reviewed main at 3079386f6cc562e584608d97bed0024dfe0c6d8a. The October 10 report
was edited in place and renamed to October 11. Only unbuilt improvements or explicit
extensions of existing features are listed.

Already shipped: Python code-mode tool scripts, CLI UTF-8 output, standalone message-board
browser composition, token resolution, attachment save/preview and image input, board
switching/fallback, AgentSession state, Agents rail spawn/open/close and @mention wake-ups
with a five-wake guard. RequestExecutor, persisted revisions, generation-aware child resume,
output draining, active-plan sidecars, process-state events and steering receipts exist.
The existing improve-yourself baseline/after workflow is recognized, not reproposed.
Campaign is absent from this checkout; reconcile its design before schema reuse.
RPA computer-use/record/replay and a Workflows rail are already planned in
[research](C:/Users/alexr/Driverless_AGI/wiki/tasks/2026-10-10_rpa-computer-use/research.md);
do not create a competing automation feature. Keep the coding harness on its standing
yolo workflow without an additional orchestration language or approval layer; the separate
RPA design's explicit replay/confirmation contract remains its own planned scope.

[Today's review](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-11.md) contains
17 open findings. R22 adds board event provenance to the ownership prerequisites for teamwork.
Fresh verification: 336 passed, three known plan-template failures and two opt-in clean-install
skips; another 55 focused Qt tests passed. SQLite's previous setup blockage is cleared.
The roadmap contains 14 unbuilt extensions; S14 adds failure-directed retry decisions.

## S1 — One owned run with an explicit outcome

**Improvement:** Give frontends, scheduled tasks and children a supported
start/status/steer/cancel/await-stopped contract and explicit terminal outcome.

**Issue addressed:** R4/R10/R18/R20/R21 show incompatible meanings of timeout, completion and failure.
R22 adds the need to preserve input provenance across concurrent UI lifetimes.
R8 now preserves branch/generation through resume; its abandoned metadata remains ownership
debt. A PID alone cannot prove stopped execution or own all cleanup.

**Smallest useful version:** Add stable run identity and an outcome containing terminal
reason, final text, diagnostics and artifact references. Retain branch/generation metadata
through child resume. Distinguish wait timeout from execution deadline. Prototype with
scheduler, code mode and child resume before migrating all UIs. Include one admitted scheduler owner
(R16); an expired wait must not allow another owner while execution survives.

**Acceptance:** Ghost exhaustion is recorded as failure; immediate and resumed results use
the same generation check; no owned execution survives reported deadline enforcement;
no selected code-mode mutation begins after acknowledged cancellation; cancelling one
parent preserves other parents' children, and closing a session terminates/reaps its worker;
queued events from a previous board cannot admit new work after a switch;
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

**Smallest useful version:** Extend the shipped Agents rail and AgentSession state with a
compact task panel and milestone timeline on existing
[process-state events](C:/Users/alexr/Driverless_AGI/agent/process_state.py) and steering,
bound to S1/S2 identities. Display wait timeout, cancellation, stale context and failure
distinctly. Keep artifact/diagnostic links after failure. Give Telegram the same concise
final outcome and artifact references.

**Acceptance:** Scripted waits, tools, compaction, questions and recovery show real state.
A closed agent shows stopping until its worker exits; background agents retain isolated
status and diagnostics. Final handoffs arrive once per confirmed local delivery; uncertain remote delivery is shown. Verified acceptance links its evidence. Background
notifications occur on meaningful changes or required action.

## S6 — Capability preflight with one actionable failure

**Improvement:** Expose effective environment and working capabilities before dependent tasks.

**Issue addressed:** Earlier reviews found shell and converter retries. Importability does
not prove working conversion; prior WebEngine checks were sandbox-sensitive. Focused Qt
controller/feed tests ran this time, but rendered WebEngine interaction was not verified.

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
Add two-parent cancellation isolation (R20) and actual worker exit after session close (R21),
rather than a mocked stop return alone. Include queued old-board events delivered after
a switch (R22); checking generation only before emitting is insufficient.

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

## S13 — Bounded collaboration receipts on the existing board

**Improvement:** Connect board collaboration to a concrete task/attempt and retained result,
so an @mention starts useful bounded work without losing ownership or replaying it.

**Issue addressed:** Agent spawning, board messages and mention wake-up are already built.
The current five-wake guard limits consecutive agent mentions, but does not describe the
delegated objective, acceptance command, execution budget or returned evidence. R20/R21
show why hidden or cancelled agents need explicit ownership before unattended teamwork;
R22 adds event provenance across board switches.

**Smallest useful version:** After S1/S2 and R20/R21/R22, attach a task/attempt reference to a
board assignment and its reply. Record accepted/running/result-received/verified states
against the existing run identity. Start with a read-only reviewer in a separate agent,
with one acceptance check and a bounded token/time budget. Deduplicate deliveries by board
identity plus post/task ID. Reject old-generation events at GUI delivery (R22) before they
can admit work on the current board. Keep shared-folder write ownership explicit before allowing
editing collaborators. Reuse existing worker/reviewer skills; do not create another agent
protocol or interpret an ordinary board message as implementation approval.

**Acceptance:** Replaying a mention cannot duplicate an admitted task. Closing or cancelling
the reviewer leaves other agents alive. A reported result links the exact source revision,
checks and artifacts, and the main task remains unverified until its acceptance check passes.
Exhausted budgets and rejected/stale results remain inspectable in the existing Agents UI.

## S14 — Retry only when the next attempt changes something relevant

**Improvement:** Show repeated failure causes and require a useful recovery change before
spending another automatic attempt on the same failure.

**Issue addressed:** RequestExecutor already bounds ghost-response retries and the loop
guards consecutive empty replies. Those controls do not connect identical tool, capability,
publication or acceptance failures across objective attempts. S2 budgets bound total work;
S14 explains what needs to change to make the next attempt useful. Yesterday's missing
SQLite DLL and today's still-missing plan template illustrate different recovery causes.

**Smallest useful version:** Extend S2's journal with a normalized failure signature, affected
operation and relevant input/environment revision. Retain the diagnostic/artifact under S9.
After the configured repeat budget, stop automatic retries and show one recovery action:
repair a capability, change a destination, revise the implementation, or retry a transient
failure with bounded backoff. Allow an explicit user retry and record its reason. Start with
deterministic setup and export failures; reuse RequestExecutor for request-local retry.
Do not classify failures by error text alone or replay mutations with unknown completion.

**Acceptance:** The same deterministic failure with unchanged relevant inputs stops consuming
automatic attempts. A verified capability repair or corrected destination admits a new
attempt while preserving prior evidence. Transient retries remain bounded; uncertain side
effects require reconciliation. The task view names the blocked operation and useful next
action. S3's evaluation corpus covers false suppression and repeated-failure escape.

## Sequence and measures

1. Repair R4/R10/R16/R18/R20/R21/R22 and Telegram R11/R12; retain verified R2/R6/R8/R9 contracts.
2. Repair R3/R13/R14, add S8 regression fixtures and the minimal S9 retained-export path;
   repair R19 to retain interrupted script diagnostics.
   Extend S1 ownership to abandoned-child cleanup. Repair R15/R17 and establish S10's plan
   contract before relying on unattended delivery.
3. Add S2 objectives and S4 manifests; prototype S5 on those records. Add S14 once retained
   failure evidence can distinguish recovery changes. S6 remains a bounded
   capability-preflight opportunity under the project's normal implementation workflow.
   Add S11 once admission and attempt recovery have durable ownership.
4. Connect S7 checkpoints and extend S3's existing self-improvement workflow. Candidate
   promotion requires intact evaluator evidence and passing behavioral contracts.
   Measure shipped code mode through S12 before choosing examples to reuse.
5. Pilot S13 with read-only review after per-parent cancellation and durable attempt
   ownership work; expand collaboration only when receipts prove correct admission/results.

Measure verified acceptance, false-success rate, final-delivery failures, question-answer
latency, cancellation latency, code-mode deadline overrun/partial-output retention, export
recovery without recomputation, plan-contract rejection, recovery success, duplicate-admission
rate, exact task-selection accuracy, obsolete-board wake-ups, retry-without-change rate, stale-result
rejection and repeated failed hypotheses. Record cost per verified outcome with missing-cost
cases explicit. Establish
baselines before choosing numerical targets. No external framework migration is required.

