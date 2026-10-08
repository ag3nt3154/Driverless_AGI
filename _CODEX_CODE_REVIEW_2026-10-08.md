# Dagi code review — 2026-10-08

## Scope and priorities

Reviewed **main** at **c5c4759ccb2a6c34beace3e05b2927a3ce2520f9**. HEAD and application
sources are unchanged since October 6. Existing report/doc edits and an unrelated untracked
image were preserved. The October 6 reports were edited and renamed in place to October 8;
there was no October 7 report. This report contains **12 open findings only**.

Prioritize execution ownership and truthful outcomes (R4/R10/R16), Telegram delivery and
answer routing (R11/R12), then reliable publication and plan assignment (R14/R15/R17).
R16 and R17 are newly reproduced this run. Stable IDs are retained for the other findings.

## R3 — P2: Record scheduler startup failures

**Finding:** Initialization sits outside the per-task error boundary.

**Issue:** [Startup](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:93) constructs the
tracker and loop after a config-only exception handler. This run's injected loop constructor
failure escaped with zero recorded attempts. The due-task loop has no outer per-job boundary,
so later jobs are interrupted. Tracker construction and finish can also escape by inspection.

**Suggested solution:** Include config, tracker, callbacks and loop construction in one
per-task boundary. Record failed attempts and continue later jobs. Isolate cleanup failures
so they cannot overwrite the original diagnostic. Exercise construction and finish failures
through the real scheduler with fake execution.

## R4 — P1: Confirm execution stopped before finalizing

**Finding:** A scheduler timeout ends the wait while owned execution remains active.

**Issue:** [Timeout handling](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111) joins a
daemon thread, calls finish, then checks liveness. The controlled-worker probe reproduced
finish while live and a timeout record. The probe released and waited for its worker afterward.
Real task tools can continue writing after finalization or during a later task.

**Suggested solution:** Own unattended execution in a process and confirm bounded termination
of descendants before finalizing or starting another job. Reuse existing process-tree support
where appropriate. Retain partial evidence and report failure to stop explicitly. Test blocked
providers, long tools and descendants; a thread join timeout cannot enforce a deadline.

## R7 — P2: Reduce remaining orchestration complexity behind supported seams

**Finding:** Several production modules and callback builders exceed the project's size limits.

**Issue:** Repeated AST inventory of 180 production Python files found five above 500 lines:
agent/loop.py (1,080), tools/subagent_main.py (744), tools/read/_reader_controller.py (525),
pyside_gui/app.py (518) and pyside_gui/prompt_input.py (628). Three functions exceed 100:
config_loader._build_config_from_entry (104), PySide bridge.build_callbacks (107), and TUI
callbacks.build_callbacks (178). Counts include comments/docstrings. Size alone is not a bug;
the adapter defects in this report show where supported lifecycle contracts are missing.
Cyclomatic complexity was not measured this run.

**Suggested solution:** Define explicit run outcomes and stop/wait semantics with one state
owner before further extraction. Reduce large files along supported public API boundaries.
Preserve registration, construction, dispatch and child argv ordering tests. Avoid splitting
files solely to improve counts.

## R8 — P2 residual: Release abandoned child metadata

**Finding:** Public child identity can outlive confirmed force-kill or parent closure.

**Issue:** [_pending_children](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:62) retains
the fork and parent provider until terminal resume or PID overwrite. The runner's
[force-kill cleanup](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:227) clears its
own tracking without releasing this public metadata. A child never resumed can therefore
retain parent references. This is source-inspected ownership debt; retained heap growth was
not measured. The scope here is abandoned metadata, not stale-result acceptance.

**Suggested solution:** Tie public identity to an owned handle that releases metadata on
confirmed exit, force-kill and parent closure without requiring another resume. Preserve
branch/generation validation. Add cleanup tests for abandoned children and reused PIDs;
elapsed waiting alone must not imply confirmed exit.

## R10 — P1: Propagate terminal failure into scheduler and benchmark results

**Finding:** Both adapters classify a normally returned terminal error as successful execution.

**Issue:** [Scheduler execution](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:102)
selects success from liveness and Python exceptions. The real loop with mocked null responses
ended with TURN_END error, while the scheduler recorded success and an empty summary.
The [benchmark path](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py:171)
likewise returned stats.error=None and timed_out=False for a real loop terminal error.
Artifact correctness scoring is separate; score inflation was not tested.

**Suggested solution:** Expose a typed outcome with terminal reason, final text, diagnostics
and artifacts, then require both adapters to consume it. Distinguish completion, failure,
exhaustion and cancellation; report artifact acceptance separately. Cover null exhaustion,
continuation limits, handoff and exceptions without classifying text prefixes.

## R11 — P1: Deliver Telegram's final handoff

**Finding:** A tool-only completed handoff produces no Telegram message.

**Issue:** [Callbacks](C:/Users/alexr/Driverless_AGI/tg/callbacks.py:88) discard on_done and
tool results. This run's real loop with these callbacks, fake bot and mocked provider returned
FINAL REPORT with zero send_message calls. The defect is reproduced without Telegram traffic.

**Suggested solution:** Deliver the final outcome and track already delivered text to avoid
duplicates within a known attempt. Retain the result when sending fails. Test tool-only and
text-only completion plus delivery failure. Keep uncertain remote delivery status explicit.

## R12 — P1: Keep Telegram answer dispatch available

**Finding:** A task handler waiting for an answer blocks dispatch of the answer itself.

**Issue:** [Application setup](C:/Users/alexr/Driverless_AGI/tg/bot.py:58) uses sequential
PTB dispatch; [the handler](C:/Users/alexr/Driverless_AGI/tg/bot.py:143) awaits the executor
job. Through the local PTB update fetcher, a synthetic answer was dispatched only after
the waiting handler was released. Concurrency=1 and a blocking handler were confirmed.
No network calls occurred.

**Suggested solution:** Own per-chat background tasks while leaving dispatch available.
Preserve per-session start guards. Register pending questions before sending, and clear
them in finally. Test answers, two chats, repeated messages, clear, late answers and shutdown
through real dispatch with mocked delivery.

## R13 — P2: Release Telegram busy state on every exit

**Finding:** Failure of optional typing notification leaves the session permanently busy.

**Issue:** [_run_agent_task](C:/Users/alexr/Driverless_AGI/tg/bot.py:150) sets busy and awaits
typing before entering try/finally. Injecting a typing exception again left busy=true. Finish
also precedes the busy reset by source inspection; finish failure was not separately injected.

**Suggested solution:** Cover the full acquired lifetime with outer try/finally and reset
busy even if finalization fails. Treat typing as optional diagnostics, clear pending questions,
and preserve original error context. Test typing, finish and cancellation failures.

## R14 — P2: Include output publication in the scheduler outcome

**Finding:** The scheduler records success before delivering the configured output file.

**Issue:** [record_run](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:127) precedes
[publication](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:129). A fake successful loop
with an existing directory as output_file again produced a success record followed by an
uncaught PermissionError. No requested file was published. Interval advancement and later-job
interruption follow this ordering; no external scheduled task was run.

**Suggested solution:** Separate computation from required delivery, retain the result and
record final status after publication. Use temporary-file replacement where feasible. Expose
export retry with a corrected destination without rerunning tools. Keep later jobs runnable.
Test unwritable destinations, replace failure and successful publication with real temp files.

## R15 — P2: Restore verification of the current plan format

**Finding:** Plan-format tests still target an intentionally removed template.

**Issue:** Three [contract tests](C:/Users/alexr/Driverless_AGI/tests/test_workflow_plan_template.py:15)
again fail with FileNotFoundError for .dagi/skills/write-plan/references/plan-template.md.
The [inline writer format](C:/Users/alexr/Driverless_AGI/.dagi/skills/write-plan/SKILL.md:48)
omits status markers; the parser reports unmarked headings as unknown. The writer/parser
contract is inconsistent. No live generated plan or delivery run was tested.

**Suggested solution:** Validate current inline skill examples or a small repository-owned
format fixture, rather than the deleted template or a personal global skill. Specify marker
rules consistently. Exercise constraints, subtask isolation, assignment and marker round-trip.
Do not restore removed content merely to satisfy stale tests.

## R16 — P1 new: Claim scheduled work before execution

**Finding:** Independent scheduler launches can execute the same due task concurrently.

**Issue:** [main](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:146) reads due times into
each process and starts work without a claim or lock. [RunTracker](C:/Users/alexr/Driverless_AGI/scheduler/tracker.py:38)
knows only completed attempts. Two actual Python processes invoking the real scheduler against
one temporary history both entered the same task before either finished, then wrote two success
records. Provider execution was replaced with a controlled fake loop; the race is in scheduler
admission. A later launch during a long task can duplicate tools and workspace changes. The
batch launcher describes frequent invocation as harmless without specifying an overlap guard.

**Suggested solution:** For the current sequential design, acquire a process-scoped lock for
the schedule before loading due state; re-read history after admission and release only after
owned execution stops. Reject overlapping launches explicitly. If per-task concurrency is later
needed, use durable attempt identity and atomic claims, with recovery that verifies the previous
owner stopped. Add a two-process regression plus killed-owner recovery. A thread lock or a
finished-only JSONL record cannot coordinate independent launches.

## R17 — P2 new: Select the exact requested plan subtask

**Finding:** Worker assignment silently picks an earlier task whose title contains the request.

**Issue:** [extract_subtask](C:/Users/alexr/Driverless_AGI/tools/_plan_parser.py:111) returns
the first case-insensitive substring match in any level-three heading. The real
[worker composer](C:/Users/alexr/Driverless_AGI/.dagi/subagents/worker/plan_utils.py:37),
given Subtask 1: Validate input and Subtask 2: Validate, assigned the first task's body/tests
when asked for Validate. The requested second task's content was absent. Existing tests allow
partial-name lookup but do not protect an exact match later in the plan. No model call is needed
to reproduce incorrect delegation.

**Suggested solution:** Parse numbered task headings and prefer an exact normalized task name
or stable task number. If partial-name lookup remains supported, allow only a unique match and
report ambiguity. Reject duplicate identities or missing matches before delegation. Test exact
names that are substrings of earlier titles, ambiguous fragments and unrelated level-three headings.

## Verification and limits

- Focused repository suite: **238 passed, 3 failed in 12.77s** across run/END_TURN/request,
  public API, construction, registration, child resume/draining, scheduler models, session
  storage and plan parsing/rendering. All three failures are the missing-template tests in R15.
- Repeated offline adapter probes reproduce R3/R4/R10–R14 using real adapters and fake
  providers/delivery. Completed outside the sandbox to avoid the previously observed Windows
  asyncio socket-pair limitation. New overlap and plan-selection probes passed inside it.
- New overlap probe uses two real subprocesses; both were reaped. Controlled workers in the
  lifecycle probe were released and awaited. All artifacts use temporary test destinations.
- Python: C:/Users/alexr/miniconda3/envs/dagi/python.exe -u; pytest-qt and cache disabled.
  [Probe source/results](C:/Users/alexr/.codex/visualizations/2026/10/08/01a11b73-16a4-7810-b1e8-4e890c34d652/)
  retain current reproductions and the AST inventory. Defect assertions reproduce current
  behavior; they do not validate proposed repairs.
- No full suite, GUI suite, live provider/Telegram, campaign, converter, power-loss or real
  process-tree cancellation run. This is a documentation-only review; no repairs were made.

See the [improvement roadmap](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-08.md).
