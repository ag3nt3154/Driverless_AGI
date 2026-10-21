# Dagi code review — 2026-10-21

## Scope and priorities

Reviewed **main**, revision **ae9eea1a60941112c275fbdc51b4f0ca81b7f0c6**. HEAD is unchanged
since the October 20 review. The checkout contains that run's uncommitted documentation;
this refresh preserves and extends it. All 259 production Python files in the established
review scope and all 26 Python files linked across both reports match `918041c2` after
newline normalization. The October 20 report was edited in place and renamed.
This report contains **25 open findings only**. No finding has a source repair to justify
removal, and no new finding was added. Previously resolved issues remain excluded.
No application code was changed by this review.

Prioritize execution/verification truth and stop ownership (R4/R10/R16/R18/R21/R23/R24/R26),
non-idempotent retries (R25), and Telegram routing/delivery (R11/R12). Protect Settings
writes/drafts with R28/R29, attachment provenance with R30/R33/R35, and improvement-run
outcomes with R31. R32 concerns stale peer callbacks; R34/R35 concern tasks lost during
snapshot setup and upload/post operations crossing a board switch.

October 21 verification: **364 focused contract tests passed**. Re-inspected scheduler
execution/publication, Telegram dispatch/finalization, replay acceptance/retry/cancellation,
code-mode dispatch/output, board adoption/posting/downloads, peer report callbacks,
configuration saves and GUI close. Passing tests do not close the separately reproduced
missing boundary cases. Retained runtime evidence keeps its original date; no historical
probe or Qt suite was rerun today. No live provider, external board/Telegram traffic or
desktop input was used. The expanded board-client test attempt did not complete; see limits.

## R3 — P2: Record scheduler startup failures

**Finding:** Initialization sits outside the per-task error boundary.

**Issue:** [Startup](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:93) constructs the
tracker and loop after a config-only exception handler. October 17's injected loop constructor
failure escaped with zero recorded attempts. The due-task loop has no outer per-job boundary,
so later jobs are interrupted. Tracker construction and finish can also escape by inspection.

**Suggested solution:** Include config, tracker, callbacks and loop construction in one
per-task boundary. Record failed attempts and continue later jobs. Isolate cleanup failures
so they cannot overwrite the original diagnostic. Exercise construction and finish failures
through the real scheduler with fake execution.

## R4 — P1: Confirm execution stopped before finalizing

**Finding:** A scheduler timeout ends the wait while owned execution remains active.

**Issue:** [Timeout handling](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111) joins a
daemon thread, calls finish, then checks liveness. The October 17 controlled-worker probe reproduced
finish while live and a timeout record. The probe released and waited for its worker afterward.
Real task tools can continue writing after finalization or during a later task.

**Suggested solution:** Own unattended execution in a process and confirm bounded termination
of descendants before finalizing or starting another job. Reuse existing process-tree support
where appropriate. Retain partial evidence and report failure to stop explicitly. Test blocked
providers, long tools and descendants; a thread join timeout cannot enforce a deadline.

## R7 — P2: Reduce remaining orchestration complexity behind supported seams

**Finding:** Nine production modules and six functions exceed the review's size thresholds.

**Issue:** October 21's AST inventory selects 259 tracked production Python files under
agent/tools/scheduler/tg/tui/pyside_gui/providers/services/rpa and root entry points,
excluding nested tests. Nine exceed 500 lines: agent/config_editor.py (517), agent/loop.py
(1,117), tools/subagent_main.py (744), tools/read/_reader_controller.py (525),
pyside_gui/agent_session.py (602), pyside_gui/prompt_input.py (635),
pyside_gui/sidebars/settings_view.py (1,032), rpa/drivers/uia.py (518) and
rpa/interpreter.py (524). Six functions exceed 100 lines: config_loader._build_config_from_entry
(110), PySide bridge.build_callbacks (111), SettingsView._build_form (121), TUI
callbacks.build_callbacks (182), rpa.interpreter.run_workflow (160) and
rpa.workflow.parse_workflow (117). Counts include comments/docstrings; cyclomatic complexity
was not measured. Size alone does not establish a behavioral defect. Peer formatting is
already extracted to peers.py, but R32/R33 expose shared delivery state within AgentSession.

**Suggested solution:** Define terminal outcomes, verification coverage, revision identity,
stop/wait contracts, per-submission report state and serialized configuration writes first.
Extract at supported public boundaries while retaining registry/construction/dispatch/argv
ordering and adapter tests. Avoid splitting files solely to improve counts.

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
selects success from liveness and Python exceptions. The October 17 real-loop probe with mocked null responses
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
tool results. October 17's real loop with these callbacks, fake bot and mocked provider returned
FINAL REPORT with zero send_message calls. The defect is reproduced without Telegram traffic.

**Suggested solution:** Deliver the final outcome and track already delivered text to avoid
duplicates within a known attempt. Retain the result when sending fails. Test tool-only and
text-only completion plus delivery failure. Keep uncertain remote delivery status explicit.

## R12 — P1: Keep Telegram answer dispatch available

**Finding:** A task handler waiting for an answer blocks dispatch of the answer itself.

**Issue:** [Application setup](C:/Users/alexr/Driverless_AGI/tg/bot.py:58) uses sequential
PTB dispatch; [the handler](C:/Users/alexr/Driverless_AGI/tg/bot.py:143) awaits the executor
job. In the October 17 probe through the local PTB update fetcher, a synthetic answer was dispatched only after
the waiting handler was released. Concurrency=1 and a blocking handler were confirmed.
No network calls occurred.

**Suggested solution:** Own per-chat background tasks while leaving dispatch available.
Preserve per-session start guards. Register pending questions before sending, and clear
them in finally. Test answers, two chats, repeated messages, clear, late answers and shutdown
through real dispatch with mocked delivery.

## R13 — P2: Release Telegram busy state on every exit

**Finding:** Failure of optional typing notification leaves the session permanently busy.

**Issue:** [_run_agent_task](C:/Users/alexr/Driverless_AGI/tg/bot.py:150) sets busy and awaits
typing before entering try/finally. The October 17 typing-exception probe left busy=true; current ordering is unchanged. Finish
also precedes the busy reset by source inspection; finish failure was not separately injected.

**Suggested solution:** Cover the full acquired lifetime with outer try/finally and reset
busy even if finalization fails. Treat typing as optional diagnostics, clear pending questions,
and preserve original error context. Test typing, finish and cancellation failures.

## R14 — P2: Include output publication in the scheduler outcome

**Finding:** The scheduler records success before delivering the configured output file.

**Issue:** [record_run](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:127) precedes
[publication](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:129). The October 17 fake successful loop
with an existing directory as output_file produced a success record followed by an
uncaught PermissionError. No requested file was published. Interval advancement and later-job
interruption follow this ordering; no external scheduled task was run.

**Suggested solution:** Separate computation from required delivery, retain the result and
record final status after publication. Use temporary-file replacement where feasible. Expose
export retry with a corrected destination without rerunning tools. Keep later jobs runnable.
Test unwritable destinations, replace failure and successful publication with real temp files.

## R16 — P1: Claim scheduled work before execution

**Finding:** Independent scheduler launches can execute the same due task concurrently.

**Issue:** [main](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:146) reads due times into
each process and starts work without a claim or lock. [RunTracker](C:/Users/alexr/Driverless_AGI/scheduler/tracker.py:38)
knows only completed attempts. On October 17, two actual Python processes invoking the real scheduler against
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

**Issue:** [close_agent](C:/Users/alexr/Driverless_AGI/pyside_gui/agents_controller.py:131)
calls [stop](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:306), removes the session
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
with background sessions. Preserve per-parent child isolation and the standing rule that
ESC pauses only its target, without board posts, wake-ups or closing peers; terminal close
is a separate operation.

## R23 — P1: Require complete, clean replay coverage before verification

**Finding:** Failed or partial replay can earn whole-workflow verification and approval.

**Issue:** [Outcome aggregation](C:/Users/alexr/Driverless_AGI/rpa/interpreter.py:189) tracks only degraded locator
rungs and halts. A step with on_fail=continue returns failed, yet a run with that failed step
and a successful last step returns ok; verify then calls mark_verified. October 17's real
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
loads and hashes the current file at completion. October 17's fake driver's act callback saved
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
October 17's fake-driver probe used retry=1, an approved confirm:once click, and an absent
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
before each item or immediately before act. October 17's gated fake-driver probe entered the first
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

## R28 — P2: Serialize conflict checking and configuration publication

**Finding:** Concurrent saves can lose accepted edits or report success for another writer's bytes.

**Issue:** [ConfigDocument.save](C:/Users/alexr/Driverless_AGI/agent/config_editor.py:454) checks the disk hash before
writing and gives every writer the same config.yaml.tmp. There is no ownership spanning
the check, temporary write and replace. October 17's first scratch-file probe completed B's save
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

## R30 — P2: Preserve board identity through attachment downloads

**Finding:** Attachment jobs and completions can cross a board switch.

**Issue:** [Submission](C:/Users/alexr/Driverless_AGI/pyside_gui/sidebars/message_board.py:253) queues only an
attachment ID. [The worker](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:391) chooses
`self.runtime.client` when the job starts, so an old-board job delayed in the shared pool
fetches from the newly adopted board. The October 16 gated probe through the real
DownloadPool and _download method reproduced that routing with fake clients.
Separately, [completion](C:/Users/alexr/Driverless_AGI/pyside_gui/sidebars/message_board.py:299) looks up the
current card by post ID without board/generation identity. The real view/future probe
cleared old cards, inserted a new-board card with the same post and attachment IDs, then
completed the old future: the new card received the old path while its own future was
pending. IDs are scoped to individual boards; this collision was constructed, not measured
in real usage. Distinct attachment IDs generally make stale delivery a no-op, but a queued
request can still fetch from the wrong server or fail there. The repaired post/purge/status
generation guards do not cover this attachment path. No network, real files or agent work
were used; pool workers were joined.

**Suggested solution:** Capture board/generation, source client and expected attachment
metadata at submission. Cancel obsolete queued jobs on switch; retain a source client until
its active downloads finish or acknowledge cancellation. Tag completion with generation
and exact card identity, then reject obsolete results before updating widgets. Verify the
downloaded content against the originating card's metadata. Add deterministic queued-job
and late-completion switch regressions, including colliding IDs and normal current delivery.

## R31 — P2: Preserve child failure in self-improvement test runs

**Finding:** The improvement runner exits successfully after a failed child if a log exists.

**Issue:** [run_test_task.run](C:/Users/alexr/Driverless_AGI/.dagi/workflow/improve-yourself/run_test_task.py:45)
captures `subprocess.run`'s return code but checks it only when no new log exists.
It otherwise returns the newest log, and [main](C:/Users/alexr/Driverless_AGI/.dagi/workflow/improve-yourself/run_test_task.py:84)
prints `LOG:` and exits 0. October 17's real CLI probe used a scratch snapshot whose main.py
wrote one session log then exited 7: the wrapper printed `LOG:` and exited 0. The child's
stderr remained visible, but callers cannot distinguish failure from success by exit status.
Steps 6/8 consume that marker, while Step 6 directs error recovery only on wrapper exit 1.
A crash after tracker/log initialization can therefore enter comparison without a failed-run
status. This proves the runner contract defect; no actual improvement was approved or scored.
It is a separate adapter from scheduler/benchmark R10 and from repaired TODO selection.

**Suggested solution:** Retain the log for diagnostics while propagating nonzero child
status or a structured failed-run outcome. Carry exit, terminal reason and log identity into
both baseline and candidate records; missing logs are a separate evidence failure. Update
workflow consumers to classify expected baseline failures separately from infrastructure
failure, and require independent acceptance before a candidate verdict. Cover nonzero-with-log,
nonzero-without-log, zero-with-log and zero-without-log through the actual runner CLI.

## R32 — P2: Bind peer delivery state and callbacks to the originating turn

**Finding:** An older asynchronous report can close or invalidate a newer peer turn.

**Issue:** [_post_report](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:545)
stores the current submission in one shared `_close_for_submission` field. Its worker
queues success/failure callbacks without the originating submission ID. October 18's
controlled actual-method probe queued two completed turns, then delivered only the first
report: [_close_after_done_slot](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:583)
read the second turn's shared marker and requested peer closure while that second report remained
unposted. A second ordering delivered the newer report successfully, then dispatched the
older failure: `_report_failed_slot` overwrote the newer `last_outcome` with `unreported`
and cleared its close marker. Separately, the board-none branch leaves `last_outcome=done`,
which the real eviction predicate accepts despite no delivery. Existing tests cover a newer
turn before a queued close, but not two overlapping report workers. These probes schedule
real report methods with fake worker/GUI queues and a close-request sink; they do not
measure real-world race frequency or terminate a real agent.

**Suggested solution:** Keep outcome and delivery state per submission. Carry immutable
submission identity into every success, failure and deferred-close callback; reject stale
state changes. Close/evict only when the relevant completed turn has a confirmed delivery
receipt and no newer work. Record pending/offline/failed delivery distinctly from computed
`done`, preserving the report for retry. Add old-success/new-pending, old-failure/new-success,
offline and normal-current-delivery regression cases. Preserve ESC's pause-only semantics.

## R33 — P2: Give every peer handoff immutable attachment bytes

**Finding:** Overlapping reports can publish one turn's preview with another turn's handoff.

**Issue:** The [_post_report worker](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:560)
writes every turn to the same `peers/<handle>/handoff_<handle>.md` before uploading it.
Reports run in independent background threads. October 18's gated probe used actual
AgentSession methods and [BoardSession.post](C:/Users/alexr/Driverless_AGI/agent/board_client.py:367)
with a fake client: report A wrote FIRST and paused before the upload sink read its path;
report B overwrote that path with SECOND and posted; A then posted preview FIRST with
attachment SECOND. Both posts succeeded. The gate models scheduling before the upload
opens/reads the file; no server or external traffic was involved, and the worker was joined.
Per-turn callback guards alone cannot preserve bytes read from a reused filename.

**Suggested solution:** Snapshot each report under a unique submission/attempt path or pass
immutable bytes to the upload layer. Preserve the public attachment name if desired, while
retaining source revision, content hash and delivery receipt per turn. Clean up only after
its own upload completes or its retained retry evidence expires. Add a gated overlapping
upload test asserting that each preview and attachment belong to the same report; cover
upload failure and retry without recomputing the agent's work.

## R34 — P2: Preserve newly accepted peer tasks during snapshot setup

**Finding:** A successful spawn can publish a task that never wakes its peer.

**Issue:** [Board adoption](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:102)
exposes agent board sessions before the asynchronous initial snapshot settles.
[spawn_agent](C:/Users/alexr/Driverless_AGI/pyside_gui/agent_session.py:226) can then register
a peer, post its task and return success. If the pending snapshot includes that task,
[_on_snapshot](C:/Users/alexr/Driverless_AGI/pyside_gui/board_controller.py:335) renders it
without mention delivery, and the stream starts after its ID. October 19's offline probe
ran the actual spawn and snapshot methods against a local in-process board: spawn returned
post #1, the snapshot committed cursor 1, and the peer received zero mentions. The actual
catch-up query after cursor 1 excluded that assignment. A second task posted after snapshot
setup reached the peer through the same real mention hook. Peer creation and stream transport
were stubbed;
this establishes the ordering defect, not its real-world frequency. Slow startup or board
switch snapshot loading exposes the window; preexisting historical mentions intentionally
remain display-only and are not the defect.

**Suggested solution:** Establish a board-generation admission watermark before exposing
task submission, or queue newly accepted assignments until snapshot/listener readiness.
Preserve and deduplicate current-session assignments by board/post identity so they deliver
once even if included in the snapshot. Distinguish posted from peer-accepted in spawn status.
Keep historical snapshot mentions quiet and ordinary live mentions uncapped. Add pending-
snapshot spawn, switch-time task, delayed snapshot and duplicate-delivery regression cases.

## R35 — P2: Bind upload and publication to one board connection

**Finding:** A board switch can split one post's uploads and final publication across servers.

**Issue:** [BoardSession.post](C:/Users/alexr/Driverless_AGI/agent/board_client.py:367)
reads mutable `self.client` for each upload and again for the final post, while
[rebind](C:/Users/alexr/Driverless_AGI/agent/board_client.py:351) replaces it during a GUI
board switch. Post does not share the read/rebind lock or capture one operation-bound client.
October 19's gated worker uploaded a handoff to in-process board A, paused before returning
the upload ID, then rebound the actual session to independent board B. On release, the
actual post went to B and failed with UNKNOWN_ATTACHMENT; A retained the unposted upload.
A control upload/post with the stable B connection succeeded. Multiple files can likewise
be distributed across clients by inspection. This affects normal board tool posts and
automatic peer task/result attachments. It is separate from R30's downloads and R33's
shared handoff filename. No external board or user artifact was changed; the worker joined.

**Suggested solution:** Capture board/generation and a client lease once per post operation;
use it for all uploads, reply references and publication. Keep the old client alive until
its operations finish or acknowledge cancellation. Do not hold a network-duration lock on
the GUI thread or silently move an in-flight operation to another board. Record the actual
destination and retain undelivered bytes for an explicit retry with fresh target-scoped IDs.
Add gated rebind tests for single/multiple attachments, source retirement, failure and retry.

## Verification and limits

- October 21: **364 tests passed in 8.04s**, using the documented `dagi` interpreter.
  The focused run covers scheduler models/history/tools, replay interpreter/store, active-plan
  association, plan parsing/writer examples, improvement TODO intake, child-owner isolation,
  configuration editing/validation and peer helpers. Command: `python -u -m pytest -q
  --tb=short -p no:pytest-qt -p no:cacheprovider --basetemp <writable-scratch>
  tests/test_scheduler.py tests/rpa/test_interpreter.py tests/rpa/test_store.py
  tests/test_active_plan.py tests/test_plan_parser.py tests/test_workflow_plan_template.py
  tests/test_improve_yourself_intake.py tests/test_subagent_owner.py
  tests/test_config_editor.py tests/test_peers.py` with plugin autoload disabled,
  `PYTHONUTF8=1` and `PYTHONDONTWRITEBYTECODE=1`. RPA uses fake drivers;
  desktop tests/global hooks remained disabled. Existing contracts do not exercise every
  open failure case; runtime admission, cancellation and verification gaps remain open.
- An earlier expanded selection additionally included board-client/download tests. It stopped
  progressing with the first board-client test's scratch directory as the latest created
  test directory, and was interrupted without a completed pytest summary. Captured output
  was unavailable after interruption; no pass count or application failure is inferred.
  The completed focused run above excludes those two files. Board-client/download and Qt
  runtime behavior therefore have no completed fresh test result this run.
- Fresh source/AST audit: HEAD is unchanged since October 20. All **259 production Python
  files** in the established scope and **26 linked Python files across both reports**
  (22 in this review) match `918041c2` after newline normalization. Inventory remains nine
  modules over 500 lines and six functions over 100. Size is a maintainability signal;
  no cyclomatic-complexity or retained-heap measurement was performed.
- Historical runtime evidence, not rerun October 21: R3/R4/R10/R11/R12/R13/R14/R16/
  R23–R26/R28/R31 use October 17; R18/R19 October 9; R21 October 10; R30 October 16;
  R32/R33 October 18; R34/R35 October 19. Source comparison supports retention, not a
  claim of fresh runtime reproduction. October 20's 188 tests, October 19's 234,
  October 18's 472 and October 17's 390 are historical and excluded from today's 364.
- Current evidence: [source/AST comparison](C:/Users/alexr/.codex/visualizations/2026/10/21/01a15bf6-efb3-7f53-99d0-51c2e76d3e5f/source_audit.json),
  [passing contract log](C:/Users/alexr/.codex/visualizations/2026/10/21/01a15bf6-efb3-7f53-99d0-51c2e76d3e5f/verification-contracts.log),
  [exact test command](C:/Users/alexr/.codex/visualizations/2026/10/21/01a15bf6-efb3-7f53-99d0-51c2e76d3e5f/test_run.json) and
  [interrupted-attempt note](C:/Users/alexr/.codex/visualizations/2026/10/21/01a15bf6-efb3-7f53-99d0-51c2e76d3e5f/interrupted_attempt.json).
  Retained [board-boundary results](C:/Users/alexr/.codex/visualizations/2026/10/19/01a154aa-60bd-7760-9ec1-7a7c4cacde39/board_boundary_results.json),
  [peer-report results](C:/Users/alexr/.codex/visualizations/2026/10/18/01a14c89-816a-7cd3-8b0e-c7a49008ee44/peer_report_results.json)
  and [October 17 evidence](C:/Users/alexr/.codex/visualizations/2026/10/17/01a14762-55a6-7d40-81ec-501147369932/)
  keep their original dates.
- No full suite, completed board-client/download suite, Qt runtime/rendered GUI/WebEngine,
  live provider/Telegram, external board, converter, power-loss, desktop input/hooks or
  cross-app repair checks this run. No application repair, configuration edit, improvement
  experiment, install, staging, commit or push. Documentation remains uncommitted.

- Independent Luna medium review: **PASS**. Structural validation confirms 25 complete
  finding triples, 17 unchanged proposal blocks, existing absolute links and valid line
  bounds, exactly two current reports, unchanged behavioral guidelines and HEAD,
  no staged files and clean `git diff --check`. Prior uncommitted documentation is retained.

See the [improvement roadmap](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-21.md).
