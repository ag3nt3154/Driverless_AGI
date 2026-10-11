# Dagi code review — 2026-10-11

## Scope and priorities

Reviewed **main** at **3079386f6cc562e584608d97bed0024dfe0c6d8a**, starting from a clean checkout.
The October 10 reports were edited in place and renamed to October 11. This report contains
**17 open findings only**, retaining stable IDs. No existing finding was verified closed.
The standalone board split, token resolution and GUI switching are the main changed paths;
the owning scheduler, Telegram, plan, loop and code-mode defect paths are unchanged.
R7 adds board_runtime.py to the remaining size violations. SQLite now imports successfully;
yesterday's environment blockage is cleared, rather than retained as an application finding.

Prioritize execution ownership and truthful outcomes (R4/R10/R16/R18/R20/R21), then Telegram
delivery/routing (R11/R12), board event provenance (R22), publication, plan assignment and
retained diagnostics (R14/R15/R17/R19). A new offline Qt probe confirms that an old-board post
already queued before a switch can display and wake agents after the switch. Earlier
reproductions are dated explicitly; unchanged defects were not re-probed indiscriminately.

## R3 — P2: Record scheduler startup failures

**Finding:** Initialization sits outside the per-task error boundary.

**Issue:** [Startup](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:93) constructs the
tracker and loop after a config-only exception handler. October 8's injected loop constructor
failure escaped with zero recorded attempts. The due-task loop has no outer per-job boundary,
so later jobs are interrupted. Tracker construction and finish can also escape by inspection.

**Suggested solution:** Include config, tracker, callbacks and loop construction in one
per-task boundary. Record failed attempts and continue later jobs. Isolate cleanup failures
so they cannot overwrite the original diagnostic. Exercise construction and finish failures
through the real scheduler with fake execution.

## R4 — P1: Confirm execution stopped before finalizing

**Finding:** A scheduler timeout ends the wait while owned execution remains active.

**Issue:** [Timeout handling](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111) joins a
daemon thread, calls finish, then checks liveness. The October 8 controlled-worker probe reproduced
finish while live and a timeout record. The probe released and waited for its worker afterward.
Real task tools can continue writing after finalization or during a later task.

**Suggested solution:** Own unattended execution in a process and confirm bounded termination
of descendants before finalizing or starting another job. Reuse existing process-tree support
where appropriate. Retain partial evidence and report failure to stop explicitly. Test blocked
providers, long tools and descendants; a thread join timeout cannot enforce a deadline.

## R7 — P2: Reduce remaining orchestration complexity behind supported seams

**Finding:** Five production modules and three callback/config builders exceed size limits.

**Issue:** Today's AST inventory selects 218 tracked Python files under agent/tools/
scheduler/tg/tui/pyside_gui/providers/services plus root entry points, excluding nested
tests. Five exceed 500 lines: agent/loop.py (1,082), tools/subagent_main.py (744),
tools/read/_reader_controller.py (525), pyside_gui/prompt_input.py (635) and
pyside_gui/board_runtime.py (513). Three functions exceed 100:
config_loader._build_config_from_entry (106), PySide bridge.build_callbacks (105) and TUI
callbacks.build_callbacks (178). Counts include comments/docstrings. This uses yesterday's
explicit production selection; the removed board composer explains the file-count change.
Cyclomatic complexity was not measured. R20–R22 show why ownership and event provenance
need supported contracts before extracting more orchestration code.

**Suggested solution:** Define per-run child ownership, terminal outcomes and stop/wait
contracts before further extraction. Reduce remaining large modules along supported public
API boundaries and preserve registry/construction/dispatch/argv ordering tests. Avoid
splitting files solely to improve counts.

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
selects success from liveness and Python exceptions. The October 8 real-loop probe with mocked null responses
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
tool results. October 8's real loop with these callbacks, fake bot and mocked provider returned
FINAL REPORT with zero send_message calls. The defect is reproduced without Telegram traffic.

**Suggested solution:** Deliver the final outcome and track already delivered text to avoid
duplicates within a known attempt. Retain the result when sending fails. Test tool-only and
text-only completion plus delivery failure. Keep uncertain remote delivery status explicit.

## R12 — P1: Keep Telegram answer dispatch available

**Finding:** A task handler waiting for an answer blocks dispatch of the answer itself.

**Issue:** [Application setup](C:/Users/alexr/Driverless_AGI/tg/bot.py:58) uses sequential
PTB dispatch; [the handler](C:/Users/alexr/Driverless_AGI/tg/bot.py:143) awaits the executor
job. In the October 8 probe through the local PTB update fetcher, a synthetic answer was dispatched only after
the waiting handler was released. Concurrency=1 and a blocking handler were confirmed.
No network calls occurred.

**Suggested solution:** Own per-chat background tasks while leaving dispatch available.
Preserve per-session start guards. Register pending questions before sending, and clear
them in finally. Test answers, two chats, repeated messages, clear, late answers and shutdown
through real dispatch with mocked delivery.

## R13 — P2: Release Telegram busy state on every exit

**Finding:** Failure of optional typing notification leaves the session permanently busy.

**Issue:** [_run_agent_task](C:/Users/alexr/Driverless_AGI/tg/bot.py:150) sets busy and awaits
typing before entering try/finally. The October 8 typing-exception probe left busy=true; current ordering is unchanged. Finish
also precedes the busy reset by source inspection; finish failure was not separately injected.

**Suggested solution:** Cover the full acquired lifetime with outer try/finally and reset
busy even if finalization fails. Treat typing as optional diagnostics, clear pending questions,
and preserve original error context. Test typing, finish and cancellation failures.

## R14 — P2: Include output publication in the scheduler outcome

**Finding:** The scheduler records success before delivering the configured output file.

**Issue:** [record_run](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:127) precedes
[publication](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:129). The October 8 fake successful loop
with an existing directory as output_file produced a success record followed by an
uncaught PermissionError. No requested file was published. Interval advancement and later-job
interruption follow this ordering; no external scheduled task was run.

**Suggested solution:** Separate computation from required delivery, retain the result and
record final status after publication. Use temporary-file replacement where feasible. Expose
export retry with a corrected destination without rerunning tools. Keep later jobs runnable.
Test unwritable destinations, replace failure and successful publication with real temp files.

## R15 — P2: Restore verification of the current plan format

**Finding:** Plan-format tests still target an intentionally removed template.

**Issue:** Three [contract tests](C:/Users/alexr/Driverless_AGI/tests/test_workflow_plan_template.py:15)
still target a missing file and fail with FileNotFoundError for .dagi/skills/write-plan/references/plan-template.md.
The [inline writer format](C:/Users/alexr/Driverless_AGI/.dagi/skills/write-plan/SKILL.md:48)
omits status markers; the parser reports unmarked headings as unknown. The writer/parser
contract is inconsistent. No live generated plan or delivery run was tested.

**Suggested solution:** Validate current inline skill examples or a small repository-owned
format fixture, rather than the deleted template or a personal global skill. Specify marker
rules consistently. Exercise constraints, subtask isolation, assignment and marker round-trip.
Do not restore removed content merely to satisfy stale tests.

## R16 — P1: Claim scheduled work before execution

**Finding:** Independent scheduler launches can execute the same due task concurrently.

**Issue:** [main](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:146) reads due times into
each process and starts work without a claim or lock. [RunTracker](C:/Users/alexr/Driverless_AGI/scheduler/tracker.py:38)
knows only completed attempts. On October 8, two actual Python processes invoking the real scheduler against
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

## R17 — P2: Select the exact requested plan subtask

**Finding:** Worker assignment silently picks an earlier task whose title contains the request.

**Issue:** [extract_subtask](C:/Users/alexr/Driverless_AGI/tools/_plan_parser.py:111) returns
the first case-insensitive substring match in any level-three heading. The real
[worker composer](C:/Users/alexr/Driverless_AGI/.dagi/subagents/worker/plan_utils.py:37),
given Subtask 1: Validate input and Subtask 2: Validate, assigned the first task's body/tests
when asked for Validate on October 8. October 9's direct parser probe again selected the
wrong block; the parser and worker composer remain unchanged today. The requested second task's content was absent. Existing tests allow
partial-name lookup but do not protect an exact match later in the plan. No model call is needed
to reproduce incorrect delegation.

**Suggested solution:** Parse numbered task headings and prefer an exact normalized task name
or stable task number. If partial-name lookup remains supported, allow only a unique match and
report ambiguity. Reject duplicate identities or missing matches before delegation. Test exact
names that are substrings of earlier titles, ambiguous fragments and unrelated level-three headings.

## R18 — P1: Give code-mode execution one cancellation and deadline owner

**Finding:** Killing the script does not reliably prevent parent-side tool execution.

**Issue:** [_serve](C:/Users/alexr/Driverless_AGI/tools/code/_code.py:192) runs each
proxied call synchronously in the parent and checks its deadline only when waiting for an
RPC line. On October 9, a real nested bash sleeping two seconds kept a one-second code call alive for
2.18 seconds. This overrun is documented in the design, but the execution budget remains
unenforced during nested tools. More seriously,
[force_kill](C:/Users/alexr/Driverless_AGI/tools/code/_code.py:157)
sets a flag and kills only the runner tree; the flag is not checked before dispatching a
selected call. A controlled gate between RPC selection and actual dispatch demonstrated
a real temporary-file write after force_kill returned true, followed by a killed result.
AgentLoop separately kills bash before code, leaving a similar start-versus-stop race.
This probe controls the interleaving; it does not measure how often users encounter it.

**Suggested solution:** Coordinate cancellation with admission of each nested call. Reject
new dispatch after stop is requested, propagate the remaining budget to nested bash, and
track/stop the active parent-owned operation before reporting stopped. Support cooperative
stop for file tools or own non-cooperative execution in a terminable process. A runner-tree
kill alone cannot stop work executing in the parent. Add gated cancellation and long nested
tool tests alongside the existing idle-script timeout/kill tests.

## R19 — P2: Retain code-mode output before abnormal termination

**Finding:** Script progress is held only in child memory until normal completion.

**Issue:** [Capture](C:/Users/alexr/Driverless_AGI/tools/code/_runner.py:108) replaces
stdout/stderr with StringIO and sends their contents only in the final done message. October 9
scripts printed a flushed checkpoint before an infinite loop or sleep. Timeout and force-kill
both returned [no output], losing that checkpoint. The mutation ledger survives in the parent,
but printed observations and diagnostics do not. The existing exception test passes because
caught script exceptions still send done; it does not cover process termination. Capture
is also unbounded before the outer result filter, by inspection; memory growth was not tested.

**Suggested solution:** Stream output frames over the existing RPC channel or spool them to
a parent-owned per-attempt artifact. Retain a bounded tail and a full artifact reference on
timeout, kill and crash; apply size limits while capturing, before final formatting. Preserve
ordering with tool replies and avoid replaying mutations to recover lost output. Add real
print-then-timeout/kill/crash fixtures and a bounded-output check.

## R20 — P1: Scope subagent cancellation to the interrupted agent

**Finding:** Interrupting one GUI agent kills children owned by other concurrent agents.

**Issue:** [AgentLoop.interrupt](C:/Users/alexr/Driverless_AGI/agent/loop.py:306) invokes
[force_kill_active_subagents](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:227),
which iterates the process-global `_active` table without an owner filter. Each
[GUI session](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:37) can run its own
loop concurrently. October 10's offline probe created two independent parent loops and two
synthetic registered child states: interrupting A targeted both child PIDs and cleaned
both states, while B itself remained unpaused. The kill primitive was mocked; this proves
target selection, not real process-tree termination. Esc or closing one agent can therefore
terminate another agent's delegated work and invalidate its expected handoff.

**Suggested solution:** Carry a stable parent/run identity through the public subagent API,
runner state and resume lifetime. Interrupt only that owner's children. Reserve a separate
all-owner shutdown operation for application exit. Test two concurrent parents, including
timed-out children and PID reuse; cancelling A must preserve B's execution and metadata.

## R21 — P2: Terminate and release closed GUI agent sessions

**Finding:** Closing a running agent removes its UI but retains a live paused worker.

**Issue:** [close_agent](C:/Users/alexr/Driverless_AGI/pyside_gui/agents_controller.py:89)
calls [stop](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:216), removes the session
and appends it to `_retired`. Stop calls interrupt, which pauses rather than terminates;
the loop blocks on its pause event. `_retired` has no reap/release path. October 10's real-loop
probe called the actual controller/stop methods with stub GUI/provider sinks: at the pause
checkpoint the agent was absent from visible sessions, its worker was alive, and the retired
list retained it. The probe explicitly resumed and joined its worker afterward. Repeated
closure retains threads, loop/session state and conversation objects for the GUI lifetime.
Central memory already acknowledges this workaround; it does not provide cancellation.
If stop returns false before loop publication, closure still removes the live session by
source inspection; that startup interleaving was not separately reproduced.

**Suggested solution:** Add terminal cancellation distinct from resumable pause. Handle
cancellation requested before loop construction, wake paused workers to exit through cleanup,
and release session/widgets only after confirmed worker termination. Show stopping until
acknowledgment. Reap completed retired sessions; do not resume hidden work just to close it.
Test running, already-paused and starting agents, repeated closes, and application shutdown
with background sessions. Apply R20's owner isolation to this path.

## R22 — P1: Reject queued events from the previous board at GUI delivery

**Finding:** Switching boards can deliver an old board's queued post as live input on the new board.

**Issue:** The [listener callback](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:289)
checks its generation before emitting a Qt signal, but the signal carries only the post.
The [GUI slot](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:303) does not check
generation or board identity. The [switch](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:191)
increments generation, clears the feed and rebinds sessions; it cannot retract already queued
signals. Today's controlled probe used the real controller, listener callback and Qt queued
delivery with fake clients. Old-board post #99 was queued in a worker, a switch completed,
then GUI events were processed: #99 appeared and triggered the mention hook while the
session client pointed at the new board. The new snapshot baseline was stubbed at zero.
No real board request, agent dispatch or provider call occurred. Old requests can therefore
wake agents with board tools now bound to a different board; old attachment cards likewise
resolve through the current client by source inspection, not a separate download probe.

**Suggested solution:** Carry generation and board/runtime identity with snapshot, stream
and status events, and reject obsolete events in the GUI slot immediately before rendering
or waking an agent. Commit snapshot baseline and posts on the GUI thread under the same
identity. Preserve attachment provenance or invalidate obsolete cards. Add a deterministic
test that queues an old post, switches before processing Qt events, and proves no display,
mention wake-up or new-board attachment fetch. Cover pending old snapshots and status too.

## Verification and limits

- Today's focused board/service/client/tool/runtime/download/helper, parser, interrupt and
  run-contract suites: **336 passed, 3 failed, 2 skipped in 50.29s**. All failures are R15's
  missing-template tests. The two clean-install tests require DAGI_RUN_SLOW=1 and network;
  they were skipped. SQLite-dependent modules collect and pass now; sqlite3 reports 3.51.2.
- Existing Qt controller/mention/agent/feed suites: **55 passed in 3.56s**. These do not cover
  R22's queued-before-switch event ordering. Both commands used the dagi interpreter outside
  the Windows sandbox with pytest-qt and pytest cache disabled; local GUI conftest registers
  pytestqt after DLL bootstrap. Test services use temporary stores; no live user board posts.
- R22's new assertion passes using real Qt queued signals and actual controller methods,
  with fake board clients, a listener stub and a settled-new-snapshot stub. Its emission-to-
  delivery interleaving is deliberate; frequency in real use was not measured.
- R3/R4/R10–R14/R16 runtime evidence is from **October 8**, R17–R19 from **October 8/9**,
  and R20/R21 from **October 10**. Owning defect code is unchanged. R21's close method has
  nearby board-removal changes but retains the stop/pause/_retired behavior. R8 remains
  source-inspected metadata debt; retained heap growth was not measured. R15 failures and
  R7 inventory are fresh. Resolved R2/R6/R8-generation/R9 defects remain removed.
- [Today's probe source](C:/Users/alexr/.codex/visualizations/2026/10/11/01a128a5-2829-73f1-a28a-648eb65c6cf3/review_probes.py),
  [results](C:/Users/alexr/.codex/visualizations/2026/10/11/01a128a5-2829-73f1-a28a-648eb65c6cf3/review_probe_results.json) and
  [verification summary](C:/Users/alexr/.codex/visualizations/2026/10/11/01a128a5-2829-73f1-a28a-648eb65c6cf3/verification.json)
  retain fresh evidence. [October 10 evidence](C:/Users/alexr/.codex/visualizations/2026/10/10/01a1236a-9530-7a20-9210-07bdb703de16/review_probe_results.json),
  [October 9 evidence](C:/Users/alexr/.codex/visualizations/2026/10/09/01a12093-68e8-7b40-98a4-9682ae3fc5c0/review_probe_results.json) and
  [October 8 evidence](C:/Users/alexr/.codex/visualizations/2026/10/08/01a11b73-16a4-7810-b1e8-4e890c34d652/)
  support unchanged-path findings. Python: C:/Users/alexr/miniconda3/envs/dagi/python.exe -u.
- No full suite, rendered GUI interaction, live provider/Telegram, campaign, converter,
  power-loss or actual multi-parent process-tree termination check. Campaign remains absent
  from this checkout. RPA is research/spike work with implementation still planned; it is
  not claimed shipped or reproposed here. Documentation-only review; no application repairs.

See the [improvement roadmap](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-11.md).
