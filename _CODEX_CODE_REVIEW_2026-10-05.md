# Dagi code review — 2026-10-05

## Scope and conclusion

Reviewed working files on **main**, HEAD **6deff1c409f6e7cf692e73952ec9ef8b195ceb7a**.
The index initially contained unresolved merge entries and staged changes. Those entries
cleared during review; HEAD stayed the same, and the tree was clean before report edits.
This automation made no application edits or Git mutations. Findings describe the
inspected working files, rather than the initial unresolved index.

The latest reports were dated October 3, not October 4. Both were renamed to October 5
and overwritten in place; no additional report was created.

The refactor materially improves turn ownership and recovery. R2's pairing defect,
R3's constructor mismatch and R6's normal-path persistence defect are resolved in the
inspected files and focused tests. Remaining risk lies mainly in adapter contracts:
ending a thread is confused with success, waiting is confused with cancellation, and
Telegram does not reliably deliver or receive the conversation.

## Status since October 3

Stable IDs are retained. R10/R13 are newly recorded observations. R11/R12 revalidate
September 6 findings; they are not new discoveries.

| ID | Priority | Current status |
|---|---|---|
| R1/R5 | Historical | Campaign findings remain outside this checkout; package absent |
| R2 | Resolved | First END_TURN wins; every later call gets a skipped result |
| R3 | P2 residual | Public tracker argument fixes construction; initialization failures escape |
| R4 | P1 | Scheduler finalizes and records timeout while its worker is alive |
| R6 | Resolved | Recovery uses persisted revision; atomic rewrite and fixed events path tested |
| R7 | P2 | Turn ownership improved; construction and dispatch still exceed size caps |
| R8 | P2 | Resumed inherited children bypass generation validation |
| R9 | P2 | Log-open and UTF-8 failures terminate output draining |
| R10 | P1 new | Scheduler records a terminal loop error as success |
| R11 | P1 historical | Telegram drops the final handoff |
| R12 | P1 historical | Answers cannot dispatch while Telegram's blocking task handler waits |
| R13 | P2 new | Typing-send failure leaves a Telegram session busy |

Resolution evidence: focused tests cover duplicate handoffs and skipped siblings, public
constructor arguments, error/pause/resume paths, recovery after meaningful work, preservation
of the user's task and disk/live event equivalence. TurnBoundaries now owns normal turn/step
boundaries; RequestExecutor owns request retry outcomes. Event replay in tests does not
establish that a shipped UI restores from the events file; that feature remains deferred.

## R3 — Record scheduler startup failures (residual)

**Finding:** The unsupported constructor argument is fixed, but startup still falls outside
the per-task error boundary.

**Issue:** [Scheduler startup](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:93)
constructs SessionTracker and AgentLoop after the config-only exception handler. Injecting
an AgentLoop initialization failure made it escape with zero recorded runs. The caller
iterates tasks without another boundary, so later due tasks do not run. Signature binding
now accepts the public tracker argument; the original TypeError claim is closed.

**Suggested solution:** Include config, tracker, callback and loop construction in one
per-task startup boundary. Record a failed attempt and continue later due tasks. Protect
cleanup separately so its errors do not replace the original error. Add constructor tests
with provider calls mocked and injected tracker/registry initialization failures.

## R4 — Confirm execution stopped before finalizing

**Finding:** A scheduler timeout still leaves owned execution running.

**Issue:** [Timeout handling](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:111)
joins a daemon thread with a timeout, calls finish before checking liveness, and records
timeout. An event-controlled worker reproduced finalization while alive. It stopped only
when the probe released it. The next due task can overlap the previous task's tools and
writes. The constructor fix makes this path reachable without bypassing R3.

**Suggested solution:** Give unattended jobs an owned process with bounded termination of
descendants, reusing [process-tree support](C:/Users/alexr/Driverless_AGI/agent/_process_kill.py)
where suitable. Finalize and start another job only after stop confirmation. Preserve
partial artifacts and report cancellation failure explicitly. Test provider waits, long
tools and descendants; a thread join timeout cannot enforce an execution deadline.

## R7 — Extend lifecycle contracts before more orchestration growth

**Finding:** Turn ownership improved substantially, while construction and dispatch remain
oversized and adapters still infer terminal semantics.

**Issue:** The AST inventory covered 180 production Python files across agent, tools,
scheduler, PySide, TUI and Telegram, excluding nested test directories. Five files exceed
500 lines and seven functions exceed 100 source lines. [AgentLoop.run](C:/Users/alexr/Driverless_AGI/agent/loop.py:700)
fell from 351 lines in the October 3 inventory to 39; its file remains 1,043 lines.
Its constructor is 168 lines, [dispatch_tool_calls](C:/Users/alexr/Driverless_AGI/agent/_tool_dispatch.py:79)
126 and [create_tool_registry](C:/Users/alexr/Driverless_AGI/agent/tools.py:115) 158.
Counts include comments/docstrings; cyclomatic complexity was not measured. R10–R12 show
that core-loop contracts alone do not guarantee correct frontend behavior.

**Suggested solution:** Extend the public surface with explicit terminal outcome and owned
stop/wait semantics. Keep one owner for state transitions. Then split construction and
per-call side-effect routing along tested seams, preserving END_TURN, pause, solo-tool,
malformed-JSON and image behavior. Extend the existing dispatch-refactor backlog.

## R8 — Preserve inherited context across child resume

**Finding:** A timed-out inherited child can return an accepted result after its parent
context becomes stale.

**Issue:** [Initial completion](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:381)
validates captured generation, but [PID resume](C:/Users/alexr/Driverless_AGI/tools/subagent_api.py:395)
only rebuilds a result. The public-API probe captured generation 4, returned timeout,
advanced the parent to 5 and resumed with status=ok, old handoff text and branch_id=None.
Immediate completion under the same mismatch returned stale.

**Suggested solution:** Retain a child handle with branch identity, captured generation,
parent-generation accessor and diagnostics through repeated waits. Use one finalizer for
immediate and resumed completion, rejecting stale results and releasing metadata on every
terminal path. Test changed/unchanged generations, repeated timeout and parent closure.
The reproduction mocked subprocess execution; no actual child model ran.

## R9 — Drain output independently of optional logging

**Finding:** Log-opening or decoding failure still stops child stdout draining silently.

**Issue:** [_tee_stdout](C:/Users/alexr/Driverless_AGI/tools/_subagent_runner.py:61)
opens its log before consuming stdout and discards exceptions around the whole operation.
The subprocess reader still uses strict UTF-8. Reprobes captured zero lines on log-open
PermissionError, leaving both input lines unread, and zero lines from a stream containing
an invalid byte. Per-line callback/write isolation is already present. A verbose child
could block on a full pipe; real pipe-capacity backpressure was not stress-tested.
This remains residual September 15 R16.

**Suggested solution:** Drain into the bounded tail even if logging is unavailable. Decode
diagnostics with an explicit tolerant policy and expose logging degradation in results.
Keep protocol validation separate. Add bounded real-process tests for invalid bytes,
unavailable log files and output beyond pipe capacity.

## R10 — Propagate terminal failure instead of inferring success

**Finding:** The scheduler reports success when AgentLoop exits with a recorded error.

**Issue:** [Worker execution](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:102)
ignores run's return and [status selection](C:/Users/alexr/Driverless_AGI/scheduler/runner.py:124)
uses only thread liveness and exceptions. The real loop's ghost-response exhaustion
returns an error string and records a TURN_END error without raising. With mocked provider
responses, the real scheduler recorded success and an empty summary while the terminal
reason was error. Its callbacks do not retain on_error diagnostics.
[Benchmark execution](C:/Users/alexr/Driverless_AGI/benchmarks/dagi_eval/harness.py:179)
also ignores the return; that adapter was inspected, not independently reproduced.

**Suggested solution:** Return or expose a typed outcome containing terminal reason, final
text and diagnostics. Make scheduler and benchmark adapters consume it. Distinguish
completion, failure, exhaustion and cancellation; textual completion should not certify
acceptance commands. Cover ghost exhaustion, continuation limit, handoff and exceptions.
Avoid classifying outcomes by an Error text prefix.

## R11 — Deliver Telegram's final handoff

**Finding:** A completed handoff produces no Telegram message.

**Issue:** [Telegram callbacks](C:/Users/alexr/Driverless_AGI/tg/callbacks.py:88)
discard on_done and tool results. The real loop with Telegram callbacks, a fake bot and a
mocked write_handoff response returned FINAL REPORT; send_message count was zero.
Intermediate text does not substitute for the deliverable. This reproduces September 6.

**Suggested solution:** Route final handoff through a delivery callback, tracking already
delivered text to avoid duplicates. Drive the real loop in tests and assert exactly one
final delivery for tool-only completion, text-only exhaustion and delivery failure with
retained diagnostic evidence.

## R12 — Keep Telegram's answer dispatcher available

**Finding:** Telegram cannot process an answer while an agent task is awaiting it.

**Issue:** [Application construction](C:/Users/alexr/Driverless_AGI/tg/bot.py:58)
uses PTB's sequential default and [the text handler](C:/Users/alexr/Driverless_AGI/tg/bot.py:143)
awaits the full executor task. [ask_user](C:/Users/alexr/Driverless_AGI/tg/callbacks.py:66)
waits for an event a later update must set. Installed-SDK introspection confirmed
max_concurrent_updates=1 and a blocking handler. Through PTB's real update fetcher, a
synthetic answer update reached its handler only after the first task was released.
No Telegram network requests were made. This revalidates the September 6 finding.

**Suggested solution:** Dispatch owned per-chat background tasks while keeping answers
available; preserve per-session guards against duplicate starts. Register pending questions
before sending, clear them in finally and prevent late answers becoming new tasks.
Verify question/answer, two chats, repeat submissions, clear and shutdown through dispatch.

## R13 — Release Telegram busy state on every exit

**Finding:** A typing notification failure leaves the chat unable to start another task.

**Issue:** [_run_agent_task](C:/Users/alexr/Driverless_AGI/tg/bot.py:150)
sets busy before awaiting send_chat_action, outside try/finally. An injected typing-send
failure reproduced busy=true after the exception. Later tasks and clear are refused.
Additionally, finish can raise before the busy reset; this path was found in source,
not separately injected.

**Suggested solution:** Cover the entire acquired session lifetime with try/finally and
reset busy in outer cleanup that survives finalization failure. Treat typing notifications
as optional diagnostics. Clear pending questions and retain original error context. Test
typing-send failure, finalizer failure and cancellation during a running task.

## Verification and limitations

- Core/lifecycle suite: **179 passed in 2.09s**, across run contracts, END_TURN, request
  executor, public loop API, turn boundaries, subagent API/runner, scheduler models,
  session store/revision and inherited-subagent integration.
- Broader loop/frontend suite: **263 passed, 2 setup errors in 6.74s**, across agent loop,
  streaming, continuation, subagent main, output filter, shadow log, TUI revision/WTF,
  GUI commands and steering. Both errors were WebEngine fixtures reporting
  Conversation page failed to load.
- Those same two tests passed outside the sandbox: **2 passed in 2.51s**. This supports a
  sandbox-sensitive setup limitation; it does not establish a GUI regression. The selected
  444 tests ultimately passed, with those two requiring the unsandboxed rerun.
- Used C:/Users/alexr/miniconda3/envs/dagi/python.exe, unbuffered output, cache disabled
  and distinct writable basetemp paths. GUI conftest re-registers pytest-qt after DLL
  bootstrap even though its global plugin is disabled.
- [Probe source](C:/Users/alexr/.codex/visualizations/2026/10/05/01a10c43-8580-7252-bae3-bc88485cb0cd/review_probes.py)
  and [results](C:/Users/alexr/.codex/visualizations/2026/10/05/01a10c43-8580-7252-bae3-bc88485cb0cd/review_probe_results.json)
  retain controlled reproductions and inventory. Probe assertions confirm current defects;
  they do not demonstrate the proposed fixes.
- Scheduler tests cover schedules, tools and tracking rather than runtime _run_task.
- No full suite, live provider/Telegram, real process-tree cancellation, pipe-capacity
  stress, converter integration or power-loss test. Campaign was not executed.
- Consulted [October running review](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/code-review-2026-10-02.md>)
  (previously updated October 3) and [September review](<G:/My Drive/black_grimoire/wiki/projects/driverless-agi/broad-review-2026-09-06.md>)
  (updated September 6). Historical sections remain historical.

Prioritize R4/R10 for unattended work and R11/R12 for usability, then R8/R9 and cleanup.
Use those repairs to extend R7's contracts. See the
[updated roadmap](C:/Users/alexr/Driverless_AGI/_CODEX_SUGGESTIONS_2026-10-05.md).

