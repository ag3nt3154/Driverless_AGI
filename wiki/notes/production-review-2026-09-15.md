# Production review — 2026-09-15

> **Status:** NOT PRODUCTION-READY. Reviewed commit `9597acc5` (`main`) on 2026-09-15.
> Scope was subagents, the agent loop, PySide GUI, and session-log construction/manipulation.
> Telegram, scheduler, and TUI were excluded except for shared helpers observed as GUI
> dependencies. No production source fixes, commits, or branches were made. These are review
> recommendations, not approved implementation plans.

## Findings

### P1 — R1: Compact fork can mix provider credential and endpoint

**Source:** [`tools/subagent_main.py:539-544`](../../tools/subagent_main.py#L539)  
**Trigger:** An active parent has switched to a provider different from the default config,
then compact fork mode resolves the default credential while inheriting the parent URL/model.
**Impact:** The request can send provider-A credentials to provider-B's endpoint and fail
authentication. **Evidence:** An offline fake-provider probe captured OpenAI construction with
provider-A's key and provider-B's URL; no real credentials or network were used.  
**Proposed fix:** Reuse the matched model/provider credential resolution used by v2 children and
reject a mismatch before client construction.  
**Acceptance:** A cross-provider compact test constructs the client with the matched key and
endpoint, or fails before construction.

### P1 — R2: Model-derived HTML executes in the conversation page

**Source:** [`pyside_gui/markdown_renderer.py:45-54`](../../pyside_gui/markdown_renderer.py#L45),
[`pyside_gui/bridge.py:118-121`](../../pyside_gui/bridge.py#L118),
[`pyside_gui/bridge.py:147-150`](../../pyside_gui/bridge.py#L147),
[`pyside_gui/resources/conversation.js:71-79`](../../pyside_gui/resources/conversation.js#L71) and
`pyside_gui/resources/conversation.js:234-248`.  
**Trigger:** A model/tool answer contains raw HTML or an event attribute and is inserted through
`innerHTML`. **Impact:** Markup executes in the conversation origin and can alter the page.
**Evidence:** An offscreen WebEngine probe used a harmless data-image `onerror` to set
`document.documentElement.dataset.reviewProbe`; the marker became `executed`. External
exfiltration and OS execution were not tested.  
**Proposed fix:** Disable raw HTML or sanitize every untrusted render path; restrict navigation
and add CSP as defense in depth.  
**Acceptance:** Event attributes and active markup remain inert during streaming, handoff, and
question rendering.

### P1 — R3: Restore chooses the first session end

**Source:** [`agent/history.py:89-98`](../../agent/history.py#L89).  
**Trigger:** A session has multiple completed turns. **Impact:** GUI restoration recovers only
the first completed snapshot. **Evidence:** An offline real tracker/loop cycle with three human
turns restored only the first.  
**Proposed fix:** Select the latest valid completed snapshot.  
**Acceptance:** Restoring a three-turn session returns all three turns.

### P1 — R4: GUI submissions reset durable event sequencing and log location

**Source:** [`pyside_gui/_dispatch.py:162-173`](../../pyside_gui/_dispatch.py#L162),
[`agent/loop.py:103-107`](../../agent/loop.py#L103), and the tracker slug rename path.  
**Trigger:** Each GUI submission creates a fresh `AgentLoop`/`SessionLog` while reusing the
tracker. **Impact:** Event sequences repeat and a slug rename can move the human log while the
durability callback still targets the old event path. **Evidence:** The offline three-loop
lifecycle wrote 33 events with only 14 unique sequence values and two resets;
reconstructed messages were duplicated (`first`, `first`, `second`, `first`, `second`, `third`).
Separately, source tracing confirmed that tracker slug renaming can shift the human log path while
the durability callback retains the original event path.

**Confirmed narrower defect and fix (2026-09-18):** `pyside_gui/_dispatch.py` supplied both
`previous._messages` and `previous.log` to the new `AgentLoop` on each prompt. The constructor in
`agent/loop.py` unconditionally seeded `initial_messages` into a supplied log, duplicating the
whole existing conversation, including tool outputs. The constructor now seeds initial messages
only when `_session_log` is absent, leaving a supplied log authoritative. Message-only resume
still seeds and refreshes its header. The regression test
`tests/test_session_log_shadow.py::TestResumeSeeding::test_gui_continuation_preserves_history_once_after_handoff`
passes across three repeated rebuild/run cycles and verifies one new user prompt.

**Status:** The narrow duplication fix is implemented and verified; the broader event sequencing,
stable log-location, and slug-rename concerns remain open. No commit or deployment to the other
machine is recorded here.

**Remaining context limitation:** A user reported that another machine reached approximately
1.2 million context on the next GUI prompt after a successful edit and `write_handoff`; the exact
incident attribution is unconfirmed because no logs are available. The reported provider limit was
1m; configured values were `context_window=200000`, `keep_recent_tokens=20000`,
`max_iterations=20`, and `reserve_tokens=16384`. The sidebar showed 300% total and 200% tools,
but its request-message estimates use characters divided by four and are not exact provider token
counts. The compaction trigger runs after a successful non-handoff tool step using preceding
response usage; handoff short-circuits that path, and there is no pre-request size enforcement.
`context_window` is a compaction trigger, not a hard provider cap. This broader hardening remains
open.

### P1 — R5: Second-level session filenames collide

**Source:** [`agent/session.py:62-72`](../../agent/session.py#L62) and
[`agent/session.py:300-305`](../../agent/session.py#L300).  
**Trigger:** Two sessions or subagents start in one project during the same second. **Impact:**
Both append to one session file. **Evidence:** A fixed-clock real tracker probe wrote two
session-start records to the same file.  
**Proposed fix:** Use a UUID-based atomic unique file identity.  
**Acceptance:** Same-second roots and subagents never share a session file.

### P1 — R6: Pause does not gate post-response tool effects

**Source:** [`agent/loop.py:583-587`](../../agent/loop.py#L583) and
[`agent/_tool_dispatch.py:68-101`](../../agent/_tool_dispatch.py#L68).  
**Trigger:** Pause arrives after the provider request begins or between tool calls. **Impact:**
The GUI reports paused while a tool can still execute; inject-and-resume can also insert user
content mid assistant/tool group. **Evidence:** A threaded offline fake provider was paused while
blocked, then released; a fake write tool still executed with the pause event cleared.  
**Proposed fix:** Gate new tool execution with cooperative pause/cancel checkpoints and announce
paused only after reaching a safe checkpoint; apply the same rule to injection.  
**Acceptance:** Pause during a provider request or between grouped calls prevents subsequent
effects and waits for a safe boundary before injection.

### P1 — R7: Invalid child handoff can be reported as success

**Source:** [`tools/_subagent_runner.py:153-165`](../../tools/_subagent_runner.py#L153) and
[`tools/subagent_main.py:417-430`](../../tools/subagent_main.py#L417).  
**Trigger:** A child exits nonzero but leaves a handoff-shaped file after twice-invalid output.
**Impact:** The parent returns `ok` despite exit code 1, and the wrapper trusts it. **Evidence:**
An invalid report plus exit 1 produced `status='ok'`, `exit_code=1`.  
**Proposed fix:** Require successful exit and validated terminal protocol; retain an invalid file
only as failure evidence.  
**Acceptance:** An invalid-handoff child cannot pass parent validation.

### P1 — R8: Non-inherited pipe children lose their custom system prompt

**Source:** [`tools/subagent_main.py:651-661`](../../tools/subagent_main.py#L651) and
[`agent/loop.py:519-534`](../../agent/loop.py#L519).  
**Trigger:** Direct pipe mode supplies a resolved custom/preset prompt as initial messages.
**Impact:** Seed handling rebuilds the main prompt because `_system_prompt_override` is not
passed, so child-specific instructions disappear. **Evidence:** A mocked real pipe entrypoint
showed the unique child prompt absent and the main prompt present.  
**Proposed fix:** Apply an explicit system override in the direct path.  
**Acceptance:** The first provider request contains the custom/preset instructions; inherited v2
handling remains unchanged.

### P1 — R9: Calls after END_TURN become orphaned

**Source:** [`agent/_tool_dispatch.py:107-110`](../../agent/_tool_dispatch.py#L107) and
[`agent/loop.py:760-778`](../../agent/loop.py#L760).  
**Trigger:** A provider response groups `write_handoff` with another call. **Impact:** Dispatch
returns after handoff while advertised calls are logged but never given results, leaving an
invalid assistant/tool pairing. `parallel_tool_calls=False` does not make this safe to trust.
**Evidence:** A fake `[write_handoff, extra]` response returned only the handoff result and left
the extra call orphaned.  
**Proposed fix:** Normalize the batch before storing it, or fill skipped calls with cancellation
results; never execute calls after termination.  
**Acceptance:** A grouped handoff response remains legal on the next turn and after restore.

### P1 — R10: Historical-session restore can orphan the active GUI worker

**Source:** [`pyside_gui/app.py:313-329`](../../pyside_gui/app.py#L313).  
**Trigger:** History selection occurs while a worker is alive. **Impact:** The active loop
reference is cleared and the view is replaced while the old worker continues with its old config
and shared signal bridge; output contaminates the restored view and Escape cannot reach it.
**Evidence:** A direct GUI handler probe with a live worker cleared the reference and conversation.
**Proposed fix:** Block/serialize restore during work, or cancel and join while invalidating
callbacks before switching.  
**Acceptance:** Restoring while running or paused preserves control isolation and prevents old
output in the restored view.

### P2 — R11: Durable events are ignored during interrupted restore

**Source:** [`agent/history.py:89-98`](../../agent/history.py#L89).  
**Trigger:** A process stops after writing events but before `session_end`. **Impact:** Restore
returns `None` and cannot recover an interrupted turn or distinguish completed tool effects.
**Evidence:** A real loop wrote events and a human turn without finishing; events existed but
restore returned `None`. No production caller of `read_session` outside `session_store` was found
in the supplied review.  
**Proposed fix:** Replay the event stream with explicit interrupted-tool recovery and tolerate a
trailing partial JSONL record.  
**Acceptance:** A crash before finish resumes without repeating completed side effects.

### P2 — R12: Idle GUI compaction violates open-turn invariant

**Source:** [`agent/_compaction.py:258-269`](../../agent/_compaction.py#L258) and
[`pyside_gui/app.py:331-345`](../../pyside_gui/app.py#L331).  
**Trigger:** GUI calls `compact(force=True)` while idle. **Impact:** The surface event append
raises `InvariantError: context/compaction appended outside an open turn`. **Evidence:** An
offline long idle history with a valid mocked summary reproduced the error; the existing success
test manually opens an artificial turn.  
**Proposed fix:** Support a maintenance transaction between turns and serialize it against run.
**Acceptance:** Idle GUI compaction completes and the persisted surface reflects the summary.

### P2 — R13: Malformed tool arguments are repaired only after the projection snapshot

**Source:** [`agent/_tool_dispatch.py:39-47`](../../agent/_tool_dispatch.py#L39) and
[`agent/session_surface.py:77-82`](../../agent/session_surface.py#L77).  
**Trigger:** Dispatch sanitizes malformed arguments by mutating event data after the surface
cache was deep-copied. **Impact:** The next request and durable event retain malformed JSON.
**Evidence:** `tests/test_agent_loop.py::TestToolDispatch::test_malformed_tool_arguments_yield_error_result_and_loop_continues`
fails JSON parsing; the review also confirmed the durable event is not corrected.  
**Proposed fix:** Normalize before logging, or append a durable correction/rebuild the affected
projection.  
**Acceptance:** Request and replay both contain valid JSON and the same repaired history.

### P2 — R14: Timed-out question sink swallows later user input

**Source:** [`pyside_gui/bridge.py:82-100`](../../pyside_gui/bridge.py#L82) and
[`pyside_gui/_dispatch.py:73-90`](../../pyside_gui/_dispatch.py#L73).  
**Trigger:** The bridge wait times out while the worker remains alive. **Impact:** The sink is
still treated as live, so the next user text is written into a stale answer container and lost.
**Evidence:** A timeout-zero bridge/handler probe returned the default and swallowed new text
without dispatch; the outer ask-user timeout can return sooner than the bridge grace period.
**Proposed fix:** Track question identity and lifetime independently of worker liveness and retire
the sink safely on timeout.  
**Acceptance:** A late answer becomes new input rather than disappearing.

### P2 — R15: Clear leaves pending restored history queued

**Source:** [`pyside_gui/app.py:148-149`](../../pyside_gui/app.py#L148) and
[`pyside_gui/_dispatch.py:163-165`](../../pyside_gui/_dispatch.py#L163).  
**Trigger:** A historical session is selected, then `/clear` is used. **Impact:** The next task
seeds the old restored messages and affect state. **Evidence:** GUI handler probes confirmed the
pending history survives clear.  
**Proposed fix:** Clear pending restore state on clear, project switch, and model switch.  
**Acceptance:** Restored-then-cleared starts with fresh history.

### P2 — R16: Observer or log errors stop draining child output

**Source:** [`tools/_subagent_runner.py:75-84`](../../tools/_subagent_runner.py#L75).  
**Trigger:** The event callback, log write, or decode fails inside the drain loop. **Impact:**
Reading stops, the child can fill its pipe and block, and diagnostics are lost. **Evidence:** A
StringIO two-line callback-raises probe captured zero lines and left the second unread.  
**Proposed fix:** Isolate callback/log failures, continue draining, and emit explicit diagnostics.
**Acceptance:** A failing observer plus output beyond pipe capacity completes without deadlock.

### P2 — R17: GUI close has no orderly worker or process-tree shutdown

**Source:** [`pyside_gui/app.py:216-218`](../../pyside_gui/app.py#L216),
[`pyside_gui/_dispatch.py:149-151`](../../pyside_gui/_dispatch.py#L149),
[`pyside_gui/__main__.py:40-42`](../../pyside_gui/__main__.py#L40).  
**Trigger:** The window closes during provider, tool, or subagent work. **Impact:** The daemon
Python worker is abruptly terminated on application exit; independently spawned child/bash
processes may survive and continue modifying files, and the turn may be lost. **Evidence:**
Source trace found no orderly cancellation, join, process-tree cleanup, or guaranteed snapshot.
This was not a real process-kill test.  
**Proposed fix:** Cancel/stop children, bounded-join, persist state, and release UI callbacks
before exit.  
**Acceptance:** Closing during each work phase leaves no owned live workers and recovers state.

### P2 — R18: Post-stream diagnostics are dropped

**Source:** [`pyside_gui/app.py:277-281`](../../pyside_gui/app.py#L277).  
**Trigger:** `_stream_had_content` remains true after a streamed answer and another assistant
message arrives before the next `stream_start`. **Impact:** Output-filter, compaction, and retry
warnings silently disappear. **Evidence:** A handler probe with the content flag set and a
compaction warning appended nothing.  
**Proposed fix:** Separate final-stream deduplication from independent diagnostic messages.
**Acceptance:** Warnings after streamed responses appear exactly once.

### P2 — R19: Preflight failure can leave a turn permanently open

**Source:** [`agent/loop.py:553-575`](../../agent/loop.py#L553).  
**Trigger:** Input materialization, attachment handling, log setup, or tracker rename fails
before the `try/finally` beginning at line 577. **Impact:** The next run on the same loop raises
`turn 1 is already open`. **Evidence:** Fault injection of submission-content preparation
reproduced the retry failure.  
**Proposed fix:** Guard lifecycle state immediately after `TURN_START` and close or mark failed
turns consistently on preflight errors.  
**Acceptance:** A startup/attachment error followed by a valid task succeeds with a closed failed
turn.

## Verification and limits

- Core selection: 375 passed, 4 failed. Three failures reflect changed expectations (session
  format is now version 3; two reload-role expectations are system vs implemented user). The
  fourth is the malformed-arguments failure in R13. A focused core selection separately passed
  195 tests; it overlaps `test_tool_dispatch_extract` and is not a unique total.
- GUI suite with the actual pytest-qt plugin/offscreen: 75 passed, 8 failed, and 9 page-load
  errors in the sandbox. The same nine WebEngine rendering tests passed outside the sandbox;
  those errors are environmental. The eight GUI assertions target removed expression APIs
  (`bridge.expression_changed`, `widget.update_expression`/`_rotate_channel`) and a four-vs-five
  rail count, so they are stale/incomplete tests rather than eight confirmed functional bugs.
- Core probes produced 12 observations; GUI probes produced 5. Together with R13's existing
  failing regression and R17's source trace, these account for all 19 findings. There were no
  live provider calls, exfiltration tests, production soak/load tests, or real interrupted
  OS-process validation.
- Optional local evidence: `C:\Users\alexr\.codex\visualizations\2026\09\15\01a0a543-44ea-79d2-9430-6cb4a6aed102\review_probes.py`,
  `.json`, `review_gui_probes.py`, and `.json` (plain paths only; outside the wiki).

## Prior-review resolutions

Current source evidence supersedes two 2026-09-08 claims: `AgentBridge.stream_ended` now has
`Signal(str, str)` and emits frozen string arguments, so the shared-field read is fixed; and
`conversation.py:158` passes `json.dumps(options)` directly, so append-question double encoding
is fixed. The first-session-end restore defect remains open and is reproduced as R3. The current
session format is version 3 (`agent/session_events.py:18`) and supersedes earlier version-2
architecture facts.
No explicit provider request timeout is configured in `build_openai_client`
(`agent/_model_switch.py:100`); no wall-clock duration was tested.

## Remediation order

Address credential routing and HTML execution first; then pause/shutdown and active-session
isolation; then persistence/recovery; then subagent contracts and compaction. Include regression
tests with fixes, and update stale assertions separately from functional regressions.

[Project wiki](../index.md)
