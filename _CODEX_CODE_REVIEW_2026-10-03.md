# Dagi code review — 2026-10-03

## Scope and conclusion

Reviewed `main` at `3ad4240cb69b05a7ea9f5ecea5576138ab534d35`; the working tree was
clean at entry. This is a review and documentation task, not implementation of the fixes.

Yesterday's review covered `task/iteration-engine` at `6917b131`, not this branch.
Their merge base is `16d0f519`. The campaign package is absent from this checkout;
its holdout-integrity and interrupted-attempt findings cannot be marked fixed here.
The shared files behind R2/R3/R4/R6 are identical between those two reviewed revisions.

This run rechecked those defects, inspected the prompt/scroll changes on `main`, and
sampled subagent completion, output draining, document conversion and benchmark execution.
The most useful immediate work remains reliable completion, cancellation and recovery.
A new resumed-subagent context defect and an incomplete earlier pipe-draining fix extend
that conclusion. Passing unit tests currently miss these cross-stage scenarios.

## Changes since the previous review

Stable IDs below refer to the October 2 review; new IDs continue its sequence.

| ID | Priority | Current status |
|---|---|---|
| R1 | P1 | Campaign holdout tampering: outside this checkout; not claimed resolved |
| R2 | P1 | Duplicate END_TURN pairing: reproduced again |
| R3 | P1 | Scheduler constructor mismatch: reproduced again |
| R4 | P1 | Scheduler timeout leaves execution alive: reproduced again with a fake worker |
| R5 | P2 | Interrupted campaign attempt accounting: outside this checkout; not claimed resolved |
| R6 | P2 | Garbled-response revision durability: reproduced again |
| R7 | P2 | Orchestration ownership/size debt: persists; inventory refreshed |
| R8 | P2 | New finding: timeout/resume bypasses inherited-context validation |
| R9 | P2 | Residual September 15 R16: log-open/decode failures still stop stdout draining |

Two improvements on `main` are visible in source: prompt sections now deduplicate
AGENTS.md by resolved path and share their metadata source; chat scrolling now repins
on submission and handles image load/resize events. Their focused tests passed in this
run. Scroll tests do not constitute a live Qt/browser interaction check.

## R2 — Complete every tool call before ending the turn

**Finding:** Two END_TURN tools in one response leave the first without a result.

**Issue:** [agent/_tool_dispatch.py:119](C:/Users/alexr/Driverless_AGI/agent/_tool_dispatch.py:119)
overwrites one deferred tuple. The real loop, with a mocked response containing two
`write_handoff` calls, logged calls `end1` and `end2`, returned `second`, and logged a
result only for `end2`. This still affects `main` without `finalize_trial`. A subsequent
request can violate a provider's required call/result pairing, and replay sees unfinished work.

**Suggested solution:** Choose a deterministic ending result, bookkeep every call including
redundant handoffs, and emit one final callback after the batch is complete. Cover duplicate
handoffs, mixed ordinary/end-turn tools and a subsequent user turn with persisted replay.

## R3 — Keep scheduler startup inside its failure boundary

**Finding:** Due tasks cannot construct AgentLoop with the scheduler's current arguments.

**Issue:** [scheduler/runner.py:98](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:98)
passes `tracker=`; [AgentLoop's constructor](C:/Users/alexr/Driverless_AGI/agent/loop.py:64)
accepts `_tracker`. Binding the real signature reproduced
`got an unexpected keyword argument 'tracker'`. Construction lies outside both the config
exception handler and worker exception capture, so this path aborts before recording the
task's startup failure. This is the previously reported September 6 defect.

**Suggested solution:** Correct the wiring and include tracker/loop construction in a
per-task startup boundary that records failure and permits later due tasks to run. Add a
real-constructor scheduler smoke test with provider calls mocked. Move adapter construction
behind a supported runtime factory when addressing R7.

## R4 — A timeout must stop owned execution before recording completion

**Finding:** The scheduler snapshots a worker that is still running after its deadline.

**Issue:** [scheduler/runner.py:111](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111)
joins with a timeout, then calls `finish()` before checking liveness.
[finish](C:/Users/alexr/Driverless_AGI/agent/loop.py:1062) records a snapshot; it does not
stop execution. With a controlled fake loop to bypass R3, the actual scheduler recorded
`timeout` and called `finish` while the worker remained alive. It could therefore overlap
the next scheduled task's changes. The probe released its worker and waited for it to stop.

**Suggested solution:** Give unattended jobs an owned process and bounded process-tree
termination, then finalize only after stop confirmation. Preserve partial evidence and
distinguish cancellation failure from successful timeout enforcement. Test provider wait,
long tools and descendants. The prior recommendation to reuse `campaign/process.py` is
conditional on that branch becoming available; the module is not on this `main`.

## R6 — Persist revisions made by automatic recovery

**Finding:** Garbled-response recovery changes live history without changing persisted events.

**Issue:** [agent/loop.py:884](C:/Users/alexr/Driverless_AGI/agent/loop.py:884) calls
[revise_last_step](C:/Users/alexr/Driverless_AGI/agent/session_log.py:273) without durable
revision recording. Three mocked empty responses followed by a handoff, with a real append
sink and stubbed compaction, left zero empty assistant events live and three on disk.
Explicit frontend revision paths rewrite history separately; this automatic path does not.
This finding concerns event-file fidelity, not a claim that current snapshot-based UI
restore necessarily selects these discarded events.

**Suggested solution:** Own revision persistence in one API. Prefer a revision event
understood by replay; if using a full rewrite initially, replace the file atomically and
make every caller use it. Verify that production-path recovery reloads to the same messages
and turn/step state as the live log.

## R7 — Narrow lifecycle contracts before further orchestration growth

**Finding:** Extracting helper files has left lifecycle policy distributed across adapters.

**Issue:** The current AST inventory covered 178 production Python files under `agent`,
`tools`, `scheduler`, `pyside_gui`, `tui` and `tg`, excluding `tests` directories. Five
files exceed 500 lines and nine functions exceed 100 source lines. Examples:

| Source | Lines |
|---|---:|
| [agent/loop.py](C:/Users/alexr/Driverless_AGI/agent/loop.py) | 1,064 |
| [AgentLoop.run](C:/Users/alexr/Driverless_AGI/agent/loop.py:628) | 351 |
| [tools/subagent_main.py](C:/Users/alexr/Driverless_AGI/tools/subagent_main.py) | 744 |
| [run_subagent](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:283) | 110 |

Counts include comments/docstrings; cyclomatic complexity was not measured. The lower file
count than yesterday reflects checkout scope, not demonstrated cleanup. More consequential
than size alone, initial completion and resumed completion have different validation (R8),
while scheduler lifecycle ownership differs from the loop (R3/R4).

**Suggested solution:** Establish supported construction, tool-batch completion and child
finalization contracts incrementally. Pass explicit lifecycle context rather than entire
loop objects/private fields. Centralize semantic decisions and validate all entry paths
with contract tests before extracting more files. Enforce the project's limits on changed
functions without a broad cosmetic rewrite.

## R8 — Resumed subagents bypass the stale-context guard

**Finding:** A timed-out inherited child can return an accepted handoff after its parent's
surface generation changes, although immediate completion rejects the same result.

**Issue:** [run_subagent](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:381) checks the
captured generation only when its first result is successful. On timeout, the parent context
and branch metadata are not retained for finalization.
[resume_subagent_by_pid](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:395) only polls
and builds a result. An offline public-API probe captured generation 4, returned timeout,
advanced the parent to generation 5, then resumed successfully: status `ok`, old handoff
text, `branch_id=None`. Immediate completion with the same mismatch returned `stale`.
The [extend-timeout tool](C:/Users/alexr/Driverless_AGI/tools/extend_timeout/_extend_timeout.py:40)
then exposes that resumed handoff normally. This matters after history revision/compaction;
it is not an assertion that ordinary new messages must invalidate every child.

**Suggested solution:** Retain an owned child handle containing branch ID, captured
generation and its parent-generation accessor until terminal exit. Route immediate and
resumed completion through the same validation/finalization function and release metadata
on every terminal path. Test unchanged-generation resume, changed-generation rejection,
repeated timeouts, parent closure and diagnostic preservation. The reproduction mocked
process execution; no actual model or child process was launched.

## R9 — Output draining still depends on logging and valid UTF-8

**Finding:** The prior callback/write isolation fix does not cover log opening or decoding.

**Issue:** [_tee_stdout](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:73) opens its
log before starting iteration and silently catches exceptions around the entire operation.
If directory creation/open fails, it consumes no output. The subprocess uses strict UTF-8
decoding at [line 254](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:254), so malformed
bytes can also end draining. Probes using the real drain function captured zero lines
when log opening raised PermissionError (both input lines remained unread), and zero lines
for a strict UTF-8 stream containing an invalid byte. A verbose live child could fill the
undrained pipe and block; this backpressure consequence was not tested with a real process.
This is residual scope of September 15 R16, not a wholly new discovery. Per-line observer
and log-write exceptions are already isolated.

**Suggested solution:** Always drain stdout independently of optional log availability;
continue the bounded tail buffer if logging fails. Use an explicit tolerant decoding policy
for diagnostic output and surface log/decoding degradation in result diagnostics. Keep
protocol parse errors distinct from diagnostic text. Add log-open, invalid-byte, callback
failure and output-beyond-pipe-capacity tests with bounded completion.

## Verification and limits

- Focused suite: **189 passed, 1 failed, 1 skipped**, 9.76 seconds. Modules:
  `test_subagent_api`, `test_subagent_runner`, `test_doc_convert`, `test_read_tool`,
  `test_scheduler`, `test_continuation`, `test_session_store`, `test_system_prompt`, and
  `pyside_gui/tests/test_scroll_to_bottom.py`.
- Failure: `TestMarkitdown.test_real_docx` reported MissingDependencyException for DOCX
  support. The declared read extra and `requirements-tools.txt` already include it; this
  does not establish a missing dependency declaration or application regression. One real
  PDF conversion test skipped. No packages were installed; conversion integration remains
  unverified in this environment. The mock-based conversion tests passed.
- Used `C:/Users/alexr/miniconda3/envs/dagi/python.exe -u -m pytest -q -p no:pytest-qt`,
  a fresh writable `--basetemp`, and disabled pytest's cache provider. Contrary to a prior
  machine-memory note, this interpreter exists here; the anaconda3 path does not.
- [Offline probe source](C:/Users/alexr/.codex/visualizations/2026/10/03/01a0ff6e-f659-71e1-9af9-019c0572ba44/review_probes.py)
  and [results](C:/Users/alexr/.codex/visualizations/2026/10/03/01a0ff6e-f659-71e1-9af9-019c0572ba44/review_probe_results.json)
  contain the six defect probes (R2/R3/R4/R6/R8/R9) and AST inventory. Assertions in the
  probe demonstrate observed behavior, not passing regression tests for proposed fixes.
- No full suite, live provider, live GUI, Telegram, actual pipe-capacity stress, process-tree
  cancellation or OS-crash test. No campaign code was executed on this checkout.
- No application source changes or Git mutations. Required documentation pointers were
  refreshed; implementation remains proposed.

## Prior knowledge consulted

- [October 2 code review, updated 2026-10-02](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/code-review-2026-10-02.md>)
- [Broad review, updated 2026-09-06](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/broad-review-2026-09-06.md>)
- [Production review, updated 2026-09-15](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/production-review-2026-09-15.md>)
- [Session review, updated 2026-10-02](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/session-log-review-2026-10-02.md>)

Prioritize R2 and R3/R4, then R8/R9 and R6. Apply R7's contract work while repairing those
paths. See [today's suggestions](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-03.md)
for the iterative-work and self-improvement roadmap.
