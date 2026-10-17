# Dagi suggestions — 2026-10-17

Proposals for sustained agentic work, measured self-improvement and understandable recovery.
They do not authorize implementation. Reviewed main at **902a083b782a725f929d91719512d46119e52fa9**.
Committed changes since the previous reviewed source are Markdown only. The existing
October 16 report was edited in place and renamed. There are **17 unbuilt improvements
or explicit extensions**; no newly completed proposal was found. Shipped portions remain
excluded. New review R31 adds a concrete prerequisite for trustworthy self-improvement
experiments, rather than a proposal to rebuild the existing workflow.

Already shipped: Settings form/raw YAML editing, comment-preserving writes/watch/conflicts,
tool-catalog checks, welcome video/maximized launch, full-handle mention warnings/member
discovery, exact/numbered task lookup with ambiguity rejection, live writer-example contracts,
TODO-based candidate selection/source identity/no-candidate handling, queued board-event
generation rejection, and reasoning/schema/system context estimates. These are not proposals.
Configuration validation and board identity/stream/temp lifecycle are now extracted modules.

Also present: code mode, standalone board/member/admin/moderation/attachment features, image
input, board switching, Agents rail/mention wake-ups, owner-scoped child cancellation,
RPA recording/compilation/replay/approval/repair evidence and Workflows cards. Build on
RequestExecutor, persisted revisions, child generation checks, output draining, active-plan
sidecars, process-state events and steering receipts. Campaign remains absent; reconcile its
historical schema before introducing another store. Preserve intentionally uncapped mentions.

Extend [improve-yourself](C:/Users/alexr/Driverless_AGI/.dagi/workflow/improve-yourself/workflow.md) and
[review-session](C:/Users/alexr/Driverless_AGI/.dagi/skills/review-session/SKILL.md). Existing baseline/candidate
testing and compatible TODO intake are not missing features. Save/draft issues R28/R29 and
attachment provenance R30 are repairs, not proposals for replacement editors/boards.

[Today's review](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-17.md) contains **21 open findings**.
October 17: **390 focused tests passed**; offline scheduler/Telegram, RPA and config-save
probes still reproduce defects. A new actual CLI probe shows the self-improvement wrapper
returning exit 0 after child exit 7 when a log exists (R31). No Qt checks ran today;
October 16 attachment/GUI evidence remains dated there. No live provider or desktop input.

## S1 — One owned run with an explicit outcome

**Improvement:** Give frontends, scheduled tasks and children a supported
start/status/steer/cancel/await-stopped contract and explicit terminal outcome.

**Issue addressed:** R4/R10/R18/R21/R26 show incompatible meanings of timeout, completion and failure.
R30 adds attachment provenance; R23/R24 add verification coverage and executed-revision identity.
R8 now preserves branch/generation through resume; its abandoned metadata remains ownership
debt. A PID alone cannot prove stopped execution or own all cleanup.

**Smallest useful version:** Add stable run identity and an outcome containing terminal
reason, final text, diagnostics and artifact references. Retain branch/generation metadata
through child resume. Distinguish wait timeout from execution deadline. Prototype with
scheduler, code mode, child resume and RPA replay before migrating all UIs. Include one admitted scheduler owner
(R16); an expired wait must not allow another owner while execution survives.

**Acceptance:** Ghost exhaustion is recorded as failure; immediate and resumed results use
the same generation check; no owned execution survives reported deadline enforcement;
no selected code-mode mutation begins after acknowledged cancellation; cancelling one
parent preserves other parents' children, and closing a session terminates/reaps its worker;
attachment jobs and results cannot cross board identities after a switch;
RPA cancellation holds ownership until stopped, verification names executed revision and
coverage, and post-action timeout cannot duplicate a mutation. Preserve R9 tests proving
output drains when its diagnostic log is unavailable. Per-parent child cancellation and
these resume/drain contracts already exist; S1 extends ownership and outcomes.

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
and retained baseline/candidate evidence. Repair R31's lost child exit status first.

**Issue addressed:** Structural metrics can reward shorter code while adapter semantics
regress. Focused board/GUI tests pass while controlled boundary probes reproduce defects.

**Smallest useful version:** Retain fixtures for pairing, recovery, scheduler outcome,
child resume, stdout draining, final delivery, question routing, publication failure,
code-mode nested timeouts/cancellation and interrupted output capture. Separate candidate work
from evaluator code/holdouts. Include code_mode and the callable registry in comparisons.
Capture the actual improvement child exit and terminal outcome alongside its log; a
log marker alone is not success. Classify expected baseline failure separately from a
broken experiment, and require independent candidate acceptance. Compare the same
effective configuration and retain commands,
exits, artifacts and failure classifications. Build on
[dagi_eval](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py) and improve-yourself.
The existing [budget-capped ALE pilot TODO](C:/Users/alexr/Driverless_AGI/wiki/todo-ale-bench-budget-pilot.md)
is pending planning, not a built evaluator; connect its evidence to these same manifests
if implemented. No benchmark installation, paid run or suitability claim is added here.

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
not prove working conversion; prior WebEngine checks were sandbox-sensitive. Focused offscreen Qt Settings/controller tests passed October 16; rendered WebEngine interaction was not verified.

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

**Issue addressed:** Passing core and RPA tests miss replay acceptance gaps. Scheduler tests
omit runtime execution, and Telegram delivery/dispatch defects survived previous reviews.

**Smallest useful version:** Preserve the R8/R9 regression tests that already landed.
Promote still-open scheduler/Telegram/publication probes as their repairs land. Use a fake
provider, delivery sink and controlled worker to drive real adapters. Assert outcomes,
delivery counts, answer routing, cleanup and disk/live equivalence. Use existing pytest;
link review IDs to fixtures. Add the R16 two-process admission scenario. Preserve the shipped exact-name
worker-selection and live skill-format fixtures; extend them for S10 runtime preflight. Add R18
controlled admission-versus-cancellation and nested-budget fixtures, and R19
print-before-timeout/kill fixtures; idle-script timeout tests do not cover these boundaries.
Preserve the shipped two-parent cancellation isolation tests and add actual worker exit after session close (R21),
rather than a mocked stop return alone. Preserve the shipped queued old-board
post/purge/status/snapshot regressions. Extend attachment coverage with R30's queued jobs
and late completions across switches. Include current admin identity, reserved-handle and
ban/purge behavior in board contracts.
Add R23/R24 complete coverage and executed-revision verification, R25 post-action
expectation timeout and R26 per-item cancellation/lock acknowledgment fixtures.

**Acceptance:** A fixture fails on the current defect and passes only with correct behavior.
Adapters agree on the same core scenario. Infrastructure errors report separately.
Cover R31 through the actual improvement runner CLI: child failure with/without a log,
and successful exit with/without evidence must remain distinct.
Future reviews can check verified closure rather than rediscovering the defect.

## S9 — Retained results and retryable artifact delivery

**Improvement:** Let a user recover a completed result when export or final delivery fails,
without paying for another agent run or repeating its tools.

**Issue addressed:** R14 records success before file publication; R11 drops the final
Telegram handoff. R19 additionally loses printed code-mode evidence on kill/timeout.
Computation, acceptance and delivery have different failure modes.

**Smallest useful version:** Retain final text and artifact references under S1's stable
run identity. Record a delivery receipt with destination, attempt, status and diagnostic.
Offer retry export with a new path and redelivery of the retained final message.
Extend existing RPA run.json evidence with executed revision, per-item coverage and unknown
side-effect status; retain its existing halt/repair artifacts rather than rebuilding them. Show
computed / verified / delivered separately in S5. Keep scheduler jobs runnable after an
individual publication error; never automatically rerun computation just to export it.
Retain code-mode partial output and its mutation ledger as incomplete attempt evidence;
never treat a checkpoint as verified completion.

**Acceptance:** An unwritable destination retains the result and reports delivery failure.
A corrected destination exports the same retained result without provider or tool calls.
File receipts identify the published bytes; Telegram receipts track successful messages
where available. A timeout with unknown delivery status stays explicit, since remote
exactly-once delivery cannot be guaranteed by a local flag. Resume preserves receipt history.

## S10 — Validate an attached plan before delivery starts

**Improvement:** Add runtime preflight to the existing active-plan association and worker flow.

**Issue addressed:** The writer now documents markers, its real examples feed contract tests,
and worker lookup prefers exact names/numbers and rejects ambiguous names. Those capabilities
are shipped. [set_active_plan](C:/Users/alexr/Driverless_AGI/tools/active_plan/_active_plan.py:78) currently validates
path/containment and writes a pointer, without checking the attached document's task structure
or acceptance criteria. A valid writer example does not validate every user-authored plan.

**Smallest useful version:** At association or before first dispatch, reuse the parser to
report duplicate task numbers/names, unknown markers, missing requirements or empty acceptance
checks with heading-specific diagnostics. Keep legacy-plan compatibility explicit. Preserve
the current writer/example, exact-selection and marker-round-trip regression suite; do not
introduce another plan format, deleted template or personal-global-skill test dependency.

**Acceptance:** A well-formed plan attaches and dispatches normally. Malformed or ambiguous
plans show precise actionable diagnostics before a worker starts; a rejected association
preserves the previous usable plan. Tests use actual skill examples plus invalid runtime
documents and confirm no worker/provider execution on failed preflight.

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
Agent-to-agent wake-ups are intentionally uncapped. Existing messages do not carry the
delegated objective, acceptance command, execution budget or returned evidence. R21
shows why hidden or cancelled agents need terminal ownership before unattended teamwork;
R30 adds attachment provenance across board switches; queued post/purge/status guards already exist.

**Smallest useful version:** After S1/S2 and R21/R30, attach a task/attempt reference to a
board assignment and its reply. Record accepted/running/result-received/verified states
against the existing run identity. Start with a read-only reviewer in a separate agent,
with one acceptance check and a bounded token/time budget. Deduplicate deliveries by board
identity plus post/task ID. Preserve the shipped old-generation event rejection before events
can admit work on the current board. Keep those guards around new assignment/receipt handling.
Treat @board-admin as the shipped launcher identity; ordinary task assignment must not imply
authority to ban, clear or shut down a board. Keep shared-folder write ownership explicit before allowing
editing collaborators. Reuse existing worker/reviewer skills; do not create another agent
protocol or interpret an ordinary board message as implementation approval.

**Acceptance:** Replaying a mention cannot duplicate an admitted task. Closing or cancelling
the reviewer leaves other agents alive. An old-board purge cannot erase current-board task cards. A reported result links the exact source revision,
checks and artifacts, and the main task remains unverified until its acceptance check passes.
Exhausted budgets and rejected/stale results remain inspectable in the existing Agents UI.

## S14 — Retry only when the next attempt changes something relevant

**Improvement:** Show repeated failure causes and require a useful recovery change before
spending another automatic attempt on the same failure.

**Issue addressed:** RequestExecutor already bounds ghost-response retries and the loop
guards consecutive empty replies. Those controls do not connect identical tool, capability,
publication or acceptance failures across objective attempts. S2 budgets bound total work;
S14 explains what needs to change to make the next attempt useful. Setup failures and evaluator/application failures require different recovery actions. R25 shows why post-action uncertainty must not trigger an automatic mutation retry.

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

## S15 — Preview a replay before it controls applications

**Improvement:** Add a read-only preflight preview to the shipped Workflows rail and CLI.

**Issue addressed:** verify is a real replay, not a dry run. The current workflow detail view
lists default parameters, secret names and steps, but does not show effective parameters,
expanded item counts, skipped prefix, destinations or confirm coverage for the next run.
R23/R24 demonstrate why a planned or partial run must not masquerade as verified execution.

**Smallest useful version:** Use the existing workflow parser/rendering and
[detail API](C:/Users/alexr/Driverless_AGI/rpa/api.py) to show the exact workflow hash, resolved non-secret inputs,
secret names/availability only, planned step/item count, start-step coverage and confirmation
policy. Display templated paths/URLs without launching drivers or rendering secret values.
Flag missing parameters/capabilities before replay. A resume preview must show the skipped
prefix and distinguish expected root bindings from bindings established by this attempt.
Extend the existing rail rather than inventing a new workflow editor or language.

**Acceptance:** Opening a preview performs zero launches, actions, global hooks or verification
writes. Missing secrets name the missing variable without revealing values. Changing input or
YAML invalidates the preview. Planned coverage stays visibly separate from execution/acceptance
receipts; only a clean complete run earns verification after R23/R24 are repaired. Add preview
fixtures to S3/S8 and keep replay retry behavior under S14/R25.

## S16 — Revalidate evidence before an improvement experiment

**Improvement:** Enrich the shipped TODO-based selection with a reproducible candidate packet.

**Issue addressed:** Current intake already understands In progress, nested follow-ups and
review IDs, records source identity, ranks candidates, asks the user to choose and stops on
no eligible candidate. Review-session already produces analysis/plans; improve-yourself
already compares baseline/candidate runs. The remaining opportunity is binding selection to
the current source revision and executable evidence, rather than a dated prose observation.

**Smallest useful version:** Attach reviewed revision, stable finding ID, reproduction command,
expected failure and independent acceptance check to one user-selected candidate. Recheck
whether it remains open and reproduce it in the snapshot before baseline/candidate stages.
Preserve failed subprocess status even when a session log exists (R31); a retained log
does not establish a completed or accepted experiment.
If the defect is repaired or the reproduction is inconclusive, record that result and return
to selection. Carry the candidate identity into S2/S4 manifests and retained hypotheses.
Use the existing implementation approval workflow when applying a candidate.

**Acceptance:** A repaired historical finding cannot start an obsolete experiment. A valid
candidate records its source revision, reproduced failure and evaluator before comparison.
Repeated ingestion preserves identity without duplicate experiments. Failed reproduction is
distinct from a rejected candidate. Applying changes remains the Admiral's decision.

## S17 — Explain each agent's effective configuration and pending changes

**Improvement:** Extend the shipped Settings editor with a read-only comparison between an
agent's captured configuration and the configuration intended for its next session.

**Issue addressed:** Settings edits root defaults, while project overrides and explicit model
selection participate in resolution. Existing agents retain their loaded AgentConfig. A saved
form therefore does not by itself identify the model/tool set that produced a result, or which
agents will adopt changed defaults. S4 needs those effective inputs for valid comparisons.

**Smallest useful version:** Capture non-secret model/tier IDs, tool availability, limits,
project/root source paths and revision hashes when constructing each session. In the existing
Agents/Settings views show that snapshot, overridden values and a concise pending-settings
diff, with clear instructions for starting a new session. Reuse
[configuration resolution](C:/Users/alexr/Driverless_AGI/agent/config_loader.py:380) and existing session state;
do not introduce a second editor or mutate active runs. Passive inspection reads captured
data and must not execute client scripts. Any explicit candidate-resolution action should
be bounded and keep its errors visible. Feed the same snapshot into S4 experiment manifests.

**Acceptance:** Two agents with different project overrides show their actual differing
configuration sources. Saving defaults leaves active-run snapshots unchanged and identifies
which settings require a new session; the next session records the adopted inputs. Model
selection and project override precedence are explained. API keys/tokens/client objects are
excluded, and merely opening the comparison performs no provider request, script execution
or configuration write. Cover unchanged, overridden, pending and invalid candidate states.

## Sequence and measures

1. Repair R4/R10/R16/R18/R21/R23/R24/R25/R26 and Telegram R11/R12; preserve existing
   owner-scoped cancellation, resume/drain and stale board-event regression contracts.
2. Repair R28/R29 Settings writes/drafts and R30 attachment provenance. Repair R3/R13/R14,
   repair R31 in the improvement runner, add S8 adapter fixtures and the minimal S9
   retained-export path; repair R19 to retain
   interrupted diagnostics. Extend S1 to abandoned-child cleanup. Pilot S10 runtime plan
   preflight on the shipped format/lookup contracts.
3. Add S2 objectives/S4 manifests and prototype S5 task recovery. Add S17 configuration
   provenance; distinguish executed/verified/delivered in Workflows. Add S14 when retained
   failures can identify relevant recovery changes. S6 preflight, S11 schedule recovery and
   S15 replay preview can extend existing APIs once admission/verification ownership is sound.
4. Add S16 evidence revalidation to existing TODO intake; connect S7 checkpoints and extend
   S3 experiments. Promotion requires intact evaluators and passing behavioral contracts.
   Measure code-mode effectiveness through S12 before choosing examples to reuse.
5. Pilot S13 with read-only review once durable attempt ownership exists. Expand collaboration
   when receipts demonstrate admission, provenance and result acceptance.

Measure verified acceptance, false-success rate, delivery failures, answer/cancellation latency,
deadline overrun, partial-output retention, export recovery without recomputation, runtime plan
rejection, duplicate admission, review-candidate reproduction, stale attachment delivery,
replay coverage/hash mismatches, post-action duplicates, preview/input drift, configuration
ambiguity, save byte/hash mismatches and retry-without-change rate. Record cost per verified
outcome with missing-cost cases explicit. Establish baselines before numerical targets.
