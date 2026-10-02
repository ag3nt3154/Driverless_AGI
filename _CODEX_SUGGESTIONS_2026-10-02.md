# Dagi suggestions — 2026-10-02

First automation run; current proposals for `task/iteration-engine` at `6917b131`.
These are design recommendations, not implemented features or approved scope.

The strongest direction is to make long-running work measurable and recoverable, then
use the same machinery to improve dagi itself. Dagi already has campaigns, benchmark
fixtures, typed session events, steering, compaction, tools and multiple frontends.
Build on those pieces instead of adding a second agent framework.

## Existing capabilities and decisions to preserve

- [campaign/](C:/Users/alexr/Driverless_AGI/campaign/engine.py) already evaluates candidates,
  archives attempts and derives an incumbent. Prefect can trigger one trial per run.
- [benchmarks/dagi_eval](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py)
  already separates public workspaces from benchmark fixtures and records results/code.
- Typed session events and surface-based compaction already exist. Older central-memory
  todos proposing their initial creation are partly superseded.
- [TODO.md](C:/Users/alexr/Driverless_AGI/TODO.md) already tracks holdout gating, artifact
  retention, tree search, stronger isolation and memory-refresh redesign. Extend these
  entries when chosen rather than creating duplicate projects.
- Preserve the recorded choice that dagi remains yolo-only. The proposals below concern
  execution limits, evidence and automated acceptance checks; they do not introduce a
  permission-card UI or a new per-tool approval mode.

## S1 — A shared run controller with explicit outcomes

**Improvement:** Give CLI, scheduler, GUI and campaign execution a supported controller for
start, steer, cancel, await-stopped and outcome retrieval.

**Why:** The scheduler's timeout currently outlives its result, `finish` means snapshotting
rather than stopping, and adapters depend on private `AgentLoop` fields. A stable controller
would make ownership and completion consistent across entry points.

**Smallest useful version:** Introduce a typed outcome distinguishing completed,
interrupted, failed, budget-exhausted and waiting states. Add optional wall-time, token/cost
and no-progress budgets. Check budgets at request/tool boundaries and use owned-process
termination for unattended jobs that must enforce deadlines. A cost ceiling should be
explicitly approximate when providers omit cost data or an in-flight call overshoots.
Keep Prefect as a trigger; let the shared execution layer own job lifetime.

**Acceptance:** Timeout leaves no owned worker or child running; a duplicate finish is
idempotent; all frontends display the same outcome; a continuation limit cannot be
reported as verified task success. Verify long tools as well as model-call boundaries.

**Dependency / effort:** Fix review R3/R4 first. Medium-to-large architectural work;
start with the scheduler adapter before changing interactive flows.

## S2 — Durable objectives and resumable attempts

**Improvement:** Extend campaigns into a general iterative-work harness with a durable
objective, acceptance commands, attempt journal and resumable checkpoints.

**Why:** The current campaign contract is specialized to `inference.py`, evaluator scores
and trial archives. Coding tasks also need a reproducible way to propose, edit, verify,
compare and continue across process restarts.

**Smallest useful version:** Add a coding-task adapter alongside the existing campaign
adapter. Record `objective_id`, attempt/parent ID, code revision, running phase, verification
artifacts and explicit outcome before each external stage begins. Reuse incumbent selection
and archived workspaces. Keep objective/acceptance data separate from agent-written narrative.
Recover interrupted attempts before rebuilding their workspaces.

**Acceptance:** Inject a stop between every pair of stages and restart: evidence survives,
the attempt is counted once, and non-idempotent tools are never blindly replayed. A failed
test prevents promotion. An interruption offers a bounded retry from a known checkpoint.

**Dependency / effort:** R1/R5/R6 and S1. Large; first ship a single coding adapter and
linear attempts before adding tree search or multi-project scheduling.

## S3 — Evaluation-driven self-improvement with a frozen baseline

**Improvement:** Let dagi propose changes to its prompts, skills or runtime, then compare
each candidate against a pinned baseline using repeatable evaluations.

**Why:** A self-improving harness needs evidence that a change helps across tasks. A single
successful conversation or validation score is insufficient, especially when the candidate
can alter its own evaluator or training evidence.

**Smallest useful version:** Connect the existing benchmark harness to candidate snapshots.
Start with prompt/skill variants, run identical task sets and model configurations for the
baseline and candidate, and retain traces, costs, latency and correctness outcomes. Include
failure-path fixtures from this review: tool pairing, cancellation, recovery and frontend
construction. Keep evaluator fixtures outside candidate write access for unattended trials.
Report a candidate recommendation; do not automatically merge or deploy runtime changes.

**Acceptance:** A candidate that improves speed but regresses correctness is rejected by the
declared acceptance policy. Repeated runs disclose variability and infrastructure failures.
The report links exact candidate/baseline revisions and evaluation artifacts. Holdout tasks
remain outside the feedback loop used to tune candidates.

**Dependency / effort:** S2 plus evaluator integrity fixes. Medium for prompt comparisons;
larger for safely evaluating runtime changes. Extends existing benchmarks and the recorded
isolation/holdout backlog.

## S4 — An experiment ledger that separates hypotheses from evidence

**Improvement:** Persist a compact, structured record of what each attempt tried, why it
was expected to help, what actually changed, and what the evaluator established.

**Why:** Campaigns carry the latest trial's `docs/` even when its code is rejected. The
generated context already warns about this, but free-form notes can still blur conjecture,
incumbent behavior and discarded changes, causing repeated experiments or false lessons.

**Smallest useful version:** Add a hypothesis ID, parent code revision, change summary,
expected effect, observed metrics, outcome and evidence links. Let the engine populate
observed metrics/outcome; let the agent author the hypothesis and interpretation. Retrieve
similar prior attempts before launching a new one. Mark lessons as provisional until their
evidence supports reuse.

**Acceptance:** Rejected code cannot be described as the current implementation without a
visible qualification; repeated hypotheses are surfaced with prior outcomes; every promoted
lesson points to a trial and verification artifact. Measure repeated failed hypotheses and
retries saved, without assuming a benefit before evaluation.

**Dependency / effort:** Small-to-medium extension of campaign history/context. Can begin
before the general coding adapter, with S2's stable attempt IDs.

## S5 — Reproducibility manifests and comparable run reports

**Improvement:** Capture the effective execution configuration and artifact identities for
every trial, benchmark and long-running task.

**Why:** Campaign history snapshots configuration, and benchmarks already record Git
identity, but interpreting an improvement also requires knowing which effective model,
prompt, tools, environment and inputs produced it.

**Smallest useful version:** Store a redacted manifest with code revision/dirty diff hash,
prompt and skill hashes, effective model/provider settings, tool allowlist, Python and
dependency versions, input/evaluator hashes, seeds where supported, and budget settings.
Link the manifest from each result. Add a comparison view explaining configuration drift
before interpreting a score delta. Exclude credentials and secret-bearing request fields.

**Acceptance:** An offline fixture can be reconstructed from its manifest and retained
artifacts; incomparable runs are labeled; manifests contain no API keys. Provider-backed
results are described as reproducible inputs, not a promise of deterministic model output.

**Dependency / effort:** Medium; builds on the existing campaign config snapshot and the
central-memory configuration-introspection/request-observability ideas.

## S6 — A work-status view centered on progress, blockers and recovery

**Improvement:** Show the user's objective, active phase, current activity, last verified
result, remaining configured budget, queued steering and next available recovery action.

**Why:** A spinner or `running` label cannot distinguish a provider wait, executing tool,
compaction, paused question or abandoned worker. The current process snapshot, session
events and steering queue provide useful inputs for a clearer view.

**Smallest useful version:** Add a task-status panel and a chronological milestone list to
the PySide UI, fed by the shared run controller rather than inferred from chat text. Show
candidate-versus-incumbent results for campaigns. Preserve the latest status after failure
with a relevant action such as retry request, resume objective or inspect failed evaluation.
Allow steering to show queued/consumed/cancelled state explicitly.

**Acceptance:** In scripted provider wait, long tool, compaction, user-question, timeout and
recovery scenarios, the panel identifies the actual state. Completed items link the final
artifact and verification evidence. Background runs notify on actionable transitions;
unchanged progress does not generate repeated notifications.

**Dependency / effort:** Medium after S1's outcome contract; reuse existing process events
and steering signals rather than introducing another independent state machine.

## S7 — Evidence-preserving compaction and memory maintenance

**Improvement:** Keep deterministic task facts outside lossy narrative summaries, and make
memory entries track their source and verification status.

**Why:** Dagi already has event-based compaction and a central wiki. The useful next step is
preserving objective/acceptance state, tested revisions, unresolved errors and artifact
pointers through repeated compactions. Existing wiki todos include partly implemented
designs and historical review claims, which can otherwise misdirect future runs.

**Smallest useful version:** Extract a structured checkpoint from verified events and the
attempt ledger, then ask the model to summarize reasoning and uncertainties around it.
Restore file excerpts on demand from retained artifacts. As part of the existing
memory-refresh redesign, mark superseded entries and merge duplicate ideas while retaining
their provenance; do not silently treat an agent's interpretation as verified knowledge.

**Acceptance:** A repeated-compaction fixture retains objective, acceptance criteria,
current revision, outstanding blockers and evidence links. Reloading persisted history
matches the active projection. Memory retrieval clearly distinguishes current verified
facts, proposals and superseded notes. Compare completion quality and context usage against
today's summarization before making it the default.

**Dependency / effort:** R6 and S4; medium. Extends the existing hybrid-compaction and
memory-refresh backlog rather than reimplementing session events.

## Recommended sequence

1. Repair the concrete correctness gaps in the
   [review report](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-02.md), especially
   invalid promotion, tool pairing and scheduler lifetime.
2. Establish shared outcomes and durable attempts (S1/S2); add manifests as attempts become
   durable (S5).
3. Add the experiment ledger and user-facing progress/recovery view (S4/S6).
4. Evaluate self-improvement candidates and compaction changes against pinned evidence
   (S3/S7).

Track verified completion rate, cancellation latency, interrupted-work recovery success,
regression rate, cost per accepted result and repeated failed hypotheses. Establish a local
baseline before choosing numerical targets. None of these proposals requires buying a
service; this report is based on repository evidence and existing project decisions.
