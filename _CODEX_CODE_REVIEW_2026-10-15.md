# Dagi code review — 2026-10-15

## Scope and priorities

Reviewed **main**, revision **6b5b5a9534ce8fbd9af864b4d362cd6774bfc593**, from a clean checkout.
The October 14 reports were edited in place and renamed to October 15. This report contains
**23 open findings only**: all 21 previous findings remain open after source/diff inspection;
R28 adds reproduced concurrent configuration-save corruption, and R29 records the shipped
Settings editor's unguarded loss of drafts on quit. No listed repair was verified, so none
was removed. Previously resolved findings remain absent.

Changes since the prior reviewed revision db8dde97 include the comment-preserving Settings
editor, tool-catalog checks, welcome videos/maximized launch and board full-handle warnings.
These are shipped capabilities. The spawned-agent mention symptom now has a documented cause
and repair (2027e1f): malformed/bare handles were ignored; tools now warn and list handles.
It is separate from still-open R22's queued old-board events after switching.

Prioritize execution/verification truth and stop ownership (R4/R10/R16/R18/R21/R23/R24/R26),
non-idempotent retries (R25), Telegram routing/delivery (R11/R12), and board provenance (R22).
Protect Settings writes/drafts with R28/R29. R27 remains an intake-contract gap in the existing
self-improvement workflow. Today's offline probes reproduce all five R23–R26 assertions and
two R28 save races; controlled fake drivers and scratch YAML perform no real desktop input.
Tests and dated historical evidence are distinguished below.

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

**Finding:** Nine production modules and six functions exceed the review's size thresholds.

**Issue:** Today's AST inventory selects 252 tracked production Python files under
agent/tools/scheduler/tg/tui/pyside_gui/providers/services/rpa and root entry points,
excluding nested tests. Nine exceed 500 lines: agent/config_editor.py (770), agent/loop.py
(1,117), tools/subagent_main.py (744), tools/read/_reader_controller.py (525),
pyside_gui/prompt_input.py (635), pyside_gui/board_runtime.py (556),
pyside_gui/sidebars/settings_view.py (1,033), rpa/drivers/uia.py (518) and rpa/interpreter.py
(524). Six functions exceed 100 lines: config_loader._build_config_from_entry (108),
PySide bridge.build_callbacks (105), SettingsView._build_form (121), TUI callbacks.build_callbacks
(178), rpa.interpreter.run_workflow (160) and rpa.workflow.parse_workflow (117).
Counts include comments/docstrings; selection matches yesterday's roots. Cyclomatic
complexity was not measured. R23–R26 and R28 show ownership/acceptance contracts needing
attention before more extraction; size alone does not establish a behavioral defect.

**Suggested solution:** Define terminal outcomes, verification coverage, revision identity,
stop/wait contracts and serialized configuration writes first. Extract at supported public
boundaries while retaining registry/construction/dispatch/argv ordering and adapter tests.
Avoid splitting files solely to improve counts.

## R8 — P2 residual: Release abandoned child metadata

**Finding:** Public child identity can outlive confirmed force-kill or parent closure.

**Issue:** [_pending_children](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:62) retains
the fork and parent provider until terminal resume or PID overwrite. The runner's
[force-kill cleanup](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:253) clears its
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
wrong block; their assignment logic remains unchanged. The requested second task's content was absent. Existing tests allow
partial-name lookup but do not protect an exact match later in the plan. No model call is needed
to reproduce incorrect delegation.

**Suggested solution:** Parse numbered task headings and prefer an exact normalized task name
or stable task number. If partial-name lookup remains supported, allow only a unique match and
report ambiguity. Reject duplicate identities or missing matches before delegation. Test exact
names that are substrings of earlier titles, ambiguous fragments and unrelated level-three headings.

## R18 — P1: Give code-mode execution one cancellation and deadline owner

**Finding:** Killing the script does not reliably prevent parent-side tool execution.

**Issue:** [_serve](C:/Users/alexr/Driverless_AGI/tools/code/_code.py:193) runs each
proxied call synchronously in the parent and checks its deadline only when waiting for an
RPC line. On October 9, a real nested bash sleeping two seconds kept a one-second code call alive for
2.18 seconds. This overrun is documented in the design, but the execution budget remains
unenforced during nested tools. More seriously,
[force_kill](C:/Users/alexr/Driverless_AGI/tools/code/_code.py:157)
sets a flag and kills only the runner tree; the flag is not checked before dispatching a
selected call. A controlled gate between RPC selection and actual dispatch demonstrated
a real temporary-file write after force_kill returned true, followed by a killed result.
The positional-argument repair does not change cancellation admission.
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

**Issue:** [Capture](C:/Users/alexr/Driverless_AGI/tools/code/_runner.py:111) replaces
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
with background sessions. Preserve the repaired per-parent child isolation in this path.

## R22 — P1: Reject queued events from the previous board at GUI delivery

**Finding:** Board switching can admit an old request and apply an old purge to the new board.

**Issue:** The [listener callbacks](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:306)
check generation before emitting, but posts, status and the newly added purge signal carry
no board identity. The [post slot](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:324)
does not recheck generation; [purges connect directly to the view](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:67).
The October 14 probe queued old-board post #99 and an all-history purge through #500 from
a worker, completed the real switch to a fake new client, and seeded new-board card #7.
Processing real Qt events displayed #99 and called the mention hook while tools were bound
to the new board; the real remove_purged method then removed #7 from the view's card identity
storage. Clients, snapshot and card storage were fake; controller, queued delivery and purge
logic were real. No real cards, board traffic, agent work or provider calls were used.
That October 14 reproduction extends the October 11 post probe to purges; the affected code is unchanged today. Old
attachment cards also resolve via the current client by inspection; downloads were not probed.

**Suggested solution:** Carry generation and board/runtime identity with snapshots, posts,
purges and status, then reject obsolete events in GUI slots immediately before rendering,
removing cards or waking agents. Commit snapshot baseline/posts on the GUI thread under
that identity. Preserve attachment provenance or invalidate obsolete cards. Add deterministic
queued-post and queued-purge switch regressions asserting no display, wake, removal or
new-board fetch. Pre-emit generation checks alone cannot retract an already queued event.

## R23 — P1: Require complete, clean replay coverage before verification

**Finding:** Failed or partial replay can earn whole-workflow verification and approval.

**Issue:** [Outcome aggregation](C:/Users/alexr/Driverless_AGI/rpa/interpreter.py:189) tracks only degraded locator
rungs and halts. A step with on_fail=continue returns failed, yet a run with that failed step
and a successful last step returns ok; verify then calls mark_verified. Today's real
interpreter/store probe produced step statuses failed/ok, run ok, and successful approval.
A second probe set start_at to the last step: only that step executed, but verify recorded
the whole workflow and approve succeeded. [The existing continuation test](C:/Users/alexr/Driverless_AGI/tests/rpa/test_interpreter.py:338)
even asserts overall ok after failure. rpa_patch exposes from_step with verify=True, making
partial verification reachable through the shipped repair flow. No live workflow was run.

**Suggested solution:** Separate continued execution from clean acceptance. Aggregate failed,
skipped and executed step/item coverage explicitly; reserve whole-workflow verification for
the defined complete acceptance contract. A resumed suffix should produce partial evidence,
or combine with validated prior coverage for the same revision, not approve unexecuted steps.
Update continuation tests and add failed-step/partial-verify approval regressions.

## R24 — P1: Verify the workflow revision that actually ran

**Finding:** Editing workflow.yaml during replay can verify and approve unexecuted content.

**Issue:** Replay loads a workflow once, but [mark_verified](C:/Users/alexr/Driverless_AGI/rpa/store.py:119)
loads and hashes the current file at completion. Today's fake driver's act callback saved
a different workflow while the real interpreter executed its previously loaded step. The
recorded verified_hash matched the replacement, not the executed original; store.approve
then pre-approved the replacement's unexecuted confirm:once step. This is a controlled
interleaving with temporary files; no real desktop action or edit frequency was measured.
run.json also omits the executed workflow hash, weakening later repair attribution.

**Suggested solution:** Capture the immutable parsed workflow and its content hash at run
admission. Persist that hash in evidence and pass it to verification recording. Refuse to
publish a current-content verification receipt when the stored revision changed, using an
atomic compare/update or serialized store ownership. Bind approval prompts/receipts to the
reviewed hash too. Test a concurrent patch during execution and a change while approval waits.

## R25 — P1: Do not repeat an executed action after an expectation timeout

**Finding:** A post-action timeout retries the action itself without proving it is safe to repeat.

**Issue:** [The retry loop](C:/Users/alexr/Driverless_AGI/rpa/interpreter.py:385) wraps resolve, confirm,
driver.act and the expectation check in one boundary. _ExpectTimeout is retryable, so the
next attempt calls driver.act again even though the first call returned successfully.
Today's fake-driver probe used retry=1, an approved confirm:once click, and an absent
expect.present condition with timeout=0: two clicks executed, then the run halted. Once
approval is reused on both attempts. In a real submit/payment/send workflow, a slow or
incorrect expectation could therefore duplicate an external operation; no such external
operation was performed in the probe. Existing retry tests cover pre-action locator failure.

**Suggested solution:** Separate pre-action resolution retries from post-action observation.
Once an action is issued, retry bounded expectation polling or stop with an uncertain outcome.
Repeat the mutation only under an explicit idempotency/reconciliation contract and applicable
confirmation. Test delayed success, absent expectations and approved sensitive steps; each
must execute at most one action by default while retaining evidence for recovery.

## R26 — P1: Hold desktop ownership until cancelled execution has stopped

**Finding:** Cancel releases the desktop lock while replay is live, and for_each can continue acting.

**Issue:** [cancel](C:/Users/alexr/Driverless_AGI/tools/ui/_tools.py:330) sets the session flag and immediately
calls end_turn, which releases DesktopLock. The interpreter checks cancellation before an
outer step and during sleep, but [the item loop](C:/Users/alexr/Driverless_AGI/rpa/interpreter.py:154) has no check
before each item or immediately before act. Today's gated fake-driver probe entered the first
of three items with a real temporary desktop lock, called the actual cancellation method,
and acquired the same lock as agent B while A's worker was still inside act. After B released
and the gate opened, A executed all three items and returned ok with the cancellation flag
still set. Worker resources were joined afterward. This proves admission/ownership ordering,
not actual simultaneous OS input or cancellation latency in a real driver.

**Suggested solution:** Make cancellation a stop request; let the execution owner release the
lock only after acknowledged action completion/termination. Check the same run cancellation
identity before every item, retry, launch and mutation, including after confirmation waits.
Coordinate cancellation with action admission so a stale selected call cannot start afterward.
Report stopping/uncertain activity until acknowledged, and preserve cancelled as the outcome.
Add the gated two-owner lock test and zero-wait for_each cancellation regression. Do not
clear a live run's cancellation flag merely because another tool entry begins.

## R27 — P2: Align self-improvement intake with the current TODO format

**Finding:** The shipped improvement workflow cannot find its documented work queue here.

**Issue:** [Step 1](C:/Users/alexr/Driverless_AGI/.dagi/workflow/improve-yourself/workflow.md:31)
instructs the agent to scan `## Work Queue` and prioritize `review-item`, `priority:high` and
`Source:` plan links. The current [TODO](C:/Users/alexr/Driverless_AGI/TODO.md) has no Work Queue
section or entries with those fields; it uses In progress and prose follow-ups. The workflow
does not define an empty/missing-queue branch. Review-session synthesis writes its own
report/plan, but its current instructions do not populate this queue either. An invocation
therefore needs the model to invent an intake rule or stop before choosing a candidate.
This is a source-inspected instruction/data contract mismatch, not a reproduced provider
failure or a claim that the baseline/candidate workflow is absent.

**Suggested solution:** Make selection consume the maintained TODO shape, or establish a
minimal explicit queue shared by review synthesis and improvement intake. Specify a clear
no-candidate outcome and stable source identity. Verify examples from the actual TODO and
empty queue before any candidate run. Preserve user selection/normal implementation approval;
review publication alone must not authorize editing or applying candidate changes.

## R28 — P2: Serialize conflict checking and configuration publication

**Finding:** Concurrent saves can lose accepted edits or report success for another writer's bytes.

**Issue:** [ConfigDocument.save](C:/Users/alexr/Driverless_AGI/agent/config_editor.py:460) checks the disk hash before
writing and gives every writer the same config.yaml.tmp. There is no ownership spanning
the check, temporary write and replace. Today's first scratch-file probe completed B's save
after A read the old hash: A also succeeded and silently restored the old model, losing B's
accepted change. A second probe used two real writer threads gated just before replace.
B overwrote the shared temporary file; A then published B's bytes, returned its own payload
hash, and B failed with FileNotFoundError. A's successful hash did not match the disk.
The [GUI save path](C:/Users/alexr/Driverless_AGI/pyside_gui/sidebars/settings_view.py:887) clears dirty state after
save returns. Multiple GUI processes share this root configuration; no overlapping real
GUI saves or user configuration changes were performed. The controlled interleavings
prove ordering defects, not their frequency. The public save_config(force=True) path also
uses this writer; a forced conflict override cannot make shared temporary files safe.

**Suggested solution:** Use a unique temporary file per save and serialize writers across
processes for the entire final hash-check/write/replace section. Keep expected-hash conflict
semantics inside that boundary; make deliberate overwrites explicit. Clean up only the
current writer's temporary file and publish/record its exact bytes. Test both interleavings,
independent-process writers, failed replacement and conflict recovery. A unique filename
alone fixes collisions but leaves the stale-check lost update.

## R29 — P2: Guard unsaved Settings edits before quitting

**Finding:** Closing the application discards unsaved configuration drafts without a decision.

**Issue:** [closeEvent](C:/Users/alexr/Driverless_AGI/pyside_gui/app.py:328) closes board/pet resources and accepts
the normal window close without consulting SettingsView.is_dirty(). Draft changes live only
in the editor until Save; reopening reloads the unchanged file. The sidebar's dirty tooltip
and Settings dot expose state but provide no quit guard or draft recovery. This is already
acknowledged in the [Settings follow-up](C:/Users/alexr/Driverless_AGI/wiki/todo-settings-unsaved-prompt.md).
The close path and draft ownership were source-inspected today; no real user window was
closed. Collapsing the panel retains its existing SettingsView and is not itself data loss.

**Suggested solution:** Before resource teardown, offer Save / Discard / Cancel when a draft
is dirty. Save must finish validation/conflict handling successfully before allowing close;
Cancel, invalid YAML, conflicts and write errors must preserve both draft and live window.
Include text fields not yet committed on editingFinished. Test clean close, each decision,
pending text, malformed raw YAML, conflicts and failed saves with scratch configuration.

## Verification and limits

- October 15 focused configuration editor/resolution, tool-registry, board tools, plan-format
  and browser-harness checks: **3 failed, 263 passed, 2 skipped, 67 warnings in 45.99s**. The three missing-template failures
  remain R15. The previously reported viewer collision fixture passed today.
  Focused offscreen Qt Settings/sidebar/mentions/agents/board-controller checks:
  **131 passed in 12.52s**. These are focused selections, not a full-suite result.
- Project interpreter: C:/Users/alexr/miniconda3/envs/dagi/python.exe. Runs disabled unrelated
  pytest plugin autoload and pytest-qt/cache on the CLI; the GUI conftest registers its
  required plugin after DLL bootstrap. All completed selections ran outside the sandbox
  with dedicated scratch basetemp directories. The initial sandboxed core selection stalled
  after partial progress and was interrupted; it is excluded from totals. An initial Qt
  command named a nonexistent test file and collected nothing; the corrected command passed.
- R23–R26: all five October 14 assertions reproduced October 15 using the real interpreter,
  store and temporary lock with FakeDriver. Workers were released/joined. R28's two controlled
  saves use real ConfigDocument and scratch YAML; all writer threads were joined. R7's AST
  inventory is fresh. R27/R29 are source-inspected contracts, not provider or live-quit tests.
- The viewer identity-collision fixture, previously recorded in
  [the test follow-up](C:/Users/alexr/Driverless_AGI/wiki/todo-preexisting-failing-tests.md), passed today.
  That failure is not reproduced in this run; passing once does not establish a repaired
  cause. Clean-install/network fixtures remain opt-in skips. No notepad/clipboard checks
  were selected.
- Earlier reproductions retain their actual dates: R3/R4/R10–R14/R16 October 8;
  R17–R19 October 8/9; R21 October 10; R22 posts/purges October 14. Affected sources are
  unchanged since yesterday, apart from unrelated welcome rendering in agent_session.py.
  R8 remains source-inspected abandoned metadata debt. No old runtime claim is relabeled fresh.
- Today's evidence: [RPA/AST probe](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/review_probes.py),
  [RPA/AST results](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/review_probe_results.json),
  [configuration save probe](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/config_save_probes.py),
  [configuration save results](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/config_save_results.json),
  [core test log](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/verification-core-outside.log),
  [Qt test log](C:/Users/alexr/.codex/visualizations/2026/10/15/01a13f5a-19f1-7461-9e3f-f162eba00e3d/verification-qt.log).
  The [October 14 archive](C:/Users/alexr/.codex/visualizations/2026/10/14/01a13a2e-5379-7132-8195-5f595075ddad/)
  retains R22 queued delivery and the earlier RPA evidence. The
  [October 8 archive](C:/Users/alexr/.codex/visualizations/2026/10/08/01a11b73-16a4-7810-b1e8-4e890c34d652/),
  [October 9 results](C:/Users/alexr/.codex/visualizations/2026/10/09/01a12093-68e8-7b40-98a4-9682ae3fc5c0/review_probe_results.json)
  and [October 10 results](C:/Users/alexr/.codex/visualizations/2026/10/10/01a1236a-9530-7a20-9210-07bdb703de16/review_probe_results.json)
  retain older evidence.
- No full suite, live Telegram/provider, converter, power-loss, OS input/hook, real user
  board moderation or cross-app repair check. Campaign remains absent. Application code,
  configuration and HEAD are unchanged; documentation changes remain uncommitted.

See the [improvement roadmap](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-15.md).
