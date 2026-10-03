# Dagi suggestions — 2026-10-03

Updated for `main` at `3ad4240c`. These are proposals, not implemented features or approved
implementation scope. The goal is an agentic harness that can continue useful work, learn
from measured outcomes and make progress/recovery understandable to its user.

## What changed in this run

Yesterday's recommendations assumed the campaign engine on `task/iteration-engine`.
It is absent from this checkout. Reuse its design only after explicitly reconciling that
branch; do not make `main` features depend on nonexistent campaign modules. Current usable
foundations include typed session events, subagent subprocesses, process-state callbacks,
steering, compaction and [dagi_eval](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py).

The new evidence puts child lifetime/context validation and failure visibility ahead of
more autonomy. Preserve the existing yolo-only product decision: the following acceptance
checks and execution limits do not add per-tool approval cards.

## S1 — Shared run ownership and resumable child handles

**Improvement:** Give frontends, scheduler and child tools one supported contract for
start, status, steer, cancel, await-stopped and terminal outcome.

**Why:** Review R3/R4 show scheduler lifetime mismatch; R8 shows that child completion has
different semantics before and after a timeout. A PID alone cannot retain branch identity,
context generation, diagnostics and cleanup ownership.

**Smallest useful version:** First fix those defects, then represent a child with a stable
run ID and an owned handle. Preserve fork identity/generation, artifact paths and its
execution owner through repeated waits. Return explicit completed, failed, cancelled,
stale-context and still-running outcomes. Treat a wait timeout separately from a deadline
that terminates execution. Keep all process cleanup/finalization idempotent.

**Acceptance:** Immediate and resumed completion enforce the same validation. A cancelled
job has no surviving owned execution before another job starts. Logging failure retains
drained output and produces a visible diagnostic. Test provider wait, tools and descendants.

**Sequence:** First foundation; implement one unattended adapter before migrating all UIs.

## S2 — Durable objectives with an attempt journal

**Improvement:** Persist what the agent is trying to achieve and the evidence from each
attempt, so a restart can continue the task coherently.

**Why:** The session log records conversation, but iterative work also needs objective,
acceptance commands, current code identity, hypothesis, phase and result. These facts
should survive summarization and process death independently of narrative handoffs.

**Smallest useful version:** Add a coding-task objective record with an append-only attempt
journal. Record started/running/verifying/terminal transitions before external work starts,
alongside branch/revision, budget and artifact pointers. On restart, inspect an interrupted
attempt before retrying; never blindly replay a non-idempotent tool. Distinguish an
agent-reported completion from acceptance verified by commands. Reconcile the campaign
branch's existing attempt/archive design before choosing a shared schema.

**Acceptance:** Interrupt between every stage pair and resume without losing artifacts or
double-counting attempts. The objective view identifies the latest verified revision and
the next unfinished action. Token, wall-time and repeated-failure limits yield explicit
outcomes; estimated cost limits disclose missing provider cost data and possible overshoot.

**Sequence:** After S1; begin with a single coding objective and one verification command.

## S3 — Evaluate self-improvement proposals against retained fixtures

**Improvement:** Let dagi propose prompt, skill and tool changes, then measure them against
a baseline before choosing them for subsequent work.

**Why:** Existing [benchmark artifacts](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py:101)
and the [session review](C:/Users/alexr/Driverless_AGI/_CODEX_SESSION_LOG_REVIEW_2026-10-02.md)
already supply code/result retention and concrete failure patterns. They are a better
starting point than allowing self-written summaries to certify improvement.

**Smallest useful version:** Build local fixtures for tool pairing, timeout/resume, history
revision, Windows shell execution and document-conversion failure. Separate candidate work
from fixed evaluators. Run baseline and candidate against the same fixtures/configuration,
retain artifacts, and make evaluator changes an integrity failure rather than a score.
Add a few end-to-end task evaluations after deterministic fixtures are reliable. Keep
proposal creation and activation separate, following the existing project Git workflow.

**Acceptance:** A favorable narrative without passing evidence cannot be selected. A known
regression in pairing, cancellation or recovery rejects the candidate. Failed dependencies
are classified separately from functional regressions. No single noisy provider run is
presented as proof of a general quality improvement.

**Sequence:** Start the fixture corpus while repairing today's review findings; add automated
candidate comparison after S2 can reliably retain attempts.

## S4 — Experiment history and reproducibility manifests

**Improvement:** Record hypotheses, outcomes and effective run inputs so the agent can avoid
repeating disproven approaches and the user can interpret improvements.

**Why:** Benchmark code retention and Git identity already exist, but the same revision
can behave differently with another prompt, model, tool set or optional dependency state.
Today's missing conversion extras demonstrate why dependency failures need explicit context.

**Smallest useful version:** Link each attempt to a redacted manifest containing revision
and dirty-diff hash, model/provider identifiers, effective config, prompt/skill hashes,
tool allowlist, interpreter/dependency versions, input/evaluator hashes and budgets. Add
hypothesis, commands, result and evidence paths. Search failed hypotheses before retrying;
allow a retry when changed inputs or new evidence justify it.

**Acceptance:** The user can distinguish baseline drift from a candidate's change. Identical
failed attempts are detectable; secrets are excluded from manifests. Offline fixtures can
be reconstructed from retained inputs. Live-provider manifests preserve inputs without
claiming deterministic model output.

**Sequence:** Add alongside S2, then use it to support S3's comparisons. This extends
yesterday's ledger/manifest proposals rather than introducing another independent store.

## S5 — A progress and recovery view tied to actual execution

**Improvement:** Show objective, active phase, running children, latest verified result,
queued steering, remaining configured budget and the available recovery action.

**Why:** [ProcessStateController](C:/Users/alexr/Driverless_AGI/agent/process_state.py) already
distinguishes thinking, tools, pause, compaction and errors. Extend those events with S1/S2
identities instead of inferring progress from chat text or maintaining a second UI state machine.

**Smallest useful version:** Add a compact task panel and milestone timeline. Show children
as running, waiting, stale or finished; make timeout semantics clear. Link failed runs to
their diagnostic tail and full artifacts, including after a resumed wait. Provide relevant
retry, resume or inspect actions. Keep the last useful state visible after failure.

**Acceptance:** Scripted waits, long tools, compaction, queued input, stale child results
and recovery each show the actual state. A completion links an artifact and verification
evidence. Background notifications occur on meaningful changes or required action, avoiding
repeated messages for unchanged work.

**Sequence:** Prototype using existing process events; bind final behavior to S1/S2.

## S6 — Capability preflight and reusable local tool sequences

**Improvement:** Expose an effective environment/capability summary and make common mechanical
sequences reusable, with clear failure evidence.

**Why:** Yesterday's session review found shell and conversion retries; today's DOCX test
could import MarkItDown but could not use its DOCX converter. Package presence is not the
same as working capability. The current conversion code already returns DAGI_CANNOT_PROCESS;
better preflight should build on that behavior.

**Smallest useful version:** Add a diagnostic command reporting resolved interpreter,
actual shell contract, tool availability and converter-extra checks. Make service connectivity
checks explicit and bounded. Supply reusable sequences for read/convert/inspect and
edit/focused-verify/artifact capture, with typed outputs and stop conditions. Use direct
argv/stdin execution where appropriate rather than fragile nested shell quoting; reconcile
the existing Windows-shell proposal before adding a separate tool.

**Acceptance:** A missing DOCX dependency produces one actionable result without repeated
identical conversions. Converter smoke fixtures distinguish healthy, unavailable and failed
states. Verification failures retain command, exit code and diagnostic artifacts. Sequences
stop for semantic decisions instead of hiding them inside a script.

**Sequence:** A useful bounded improvement while S1/S2 are developed. Reuse the existing
configuration-introspection and Windows-shell backlog.

## S7 — Evidence-preserving compaction and current memory

**Improvement:** Keep deterministic task facts outside lossy summaries and qualify memory
entries by source, revision, verification status and whether they have been superseded.

**Why:** R6 shows live/persisted history divergence. This run also found a historical
interpreter-path note that does not match this environment, and campaign recommendations
that apply to another branch. Without provenance, old facts can misdirect future work.

**Smallest useful version:** Fix revision durability first, then derive a checkpoint from
verified objective/attempt events: acceptance criteria, current revision, open blockers and
artifact pointers. Summarize reasoning around that checkpoint. Extend the planned memory
refresh to mark outdated claims and consolidate duplicate todos while retaining provenance.

**Acceptance:** Repeated compaction and restart retain the same objective, tested revision,
blockers and evidence. Retrieved proposals are distinguishable from verified outcomes and
historical observations. Branch-specific findings are not silently promoted to current facts.

**Sequence:** Coordinate with S2/S4 and the existing hybrid-compaction/memory-refresh backlog.

## Recommended order and measures

1. Fix [review R2/R3/R4](C:/Users/alexr/Driverless_AGI/_CODEX_CODE_REVIEW_2026-10-03.md),
   then R8/R9/R6; establish the S1 lifecycle contract through those changes.
2. Add S2's durable objective and S4's manifest/attempt records. Start S6 capability checks.
3. Connect S5's user view and S7's checkpoints to those records.
4. Use S3's fixture corpus and retained comparisons to evaluate self-improvement candidates.

Measure verified completion, cancellation latency, recovery success, stale-result rejection,
repeated failed attempts and cost per accepted outcome. Establish a baseline before choosing
numerical targets. These suggestions are grounded in repository evidence; no external
products, services or framework migration are required.
