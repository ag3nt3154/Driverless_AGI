# Context Overflow and Compaction Audit

Date: 2026-09-18  
Project: Driverless AGI (dagi)  
Baseline: `ce37e29a` — `fix: prevent duplicate context on GUI continuation`

## Summary

The investigation reproduced a GUI bug that duplicated the complete conversation when the user
sent another prompt. That bug is fixed in `ce37e29a`. A follow-up audit confirmed six remaining
issues that can allow oversized requests or prevent compaction from reducing them.

The original incident occurred on another machine, and its logs were unavailable. The findings
below are confirmed local code defects or reproduced limitations; they do not establish the exact
cause of the reported 1.2-million-token request.

Only the duplication fix has been implemented. The remaining remedies are recommendations.

| ID | Priority | Finding | Status |
| --- | --- | --- | --- |
| C0 | P1 | GUI continuation duplicated the complete history | Fixed in `ce37e29a` |
| C1 | P1 | No context budget check before sending a request | Open |
| C2 | P1 | Cache errors allow full oversized tool output into context | Open |
| C3 | P1 | GUI manual compaction fails before compaction starts | Open |
| C4 | P2 | Handoff leaves compaction usage missing or stale | Open |
| C5 | P2 | A step-zero boundary can silently abort compaction | Open |
| C6 | P2 | Recent-history retention uses average size, not actual tail size | Open |

P1 means high priority because the issue permits oversized requests or blocks manual recovery.
P2 means a correctness issue in compaction accounting or selection that weakens context control.

## Reported incident

The user reported the following sequence:

1. A normal edit succeeded.
2. `write_handoff` succeeded and ended the turn.
3. The user sent another prompt in the GUI.
4. Context grew to approximately 1.2 million tokens, exceeding a reported provider limit of
   1 million tokens. The sidebar showed approximately 300% total context and 200% tool content.

Reported project configuration:

```yaml
context_window: 200000
keep_recent_tokens: 20000
max_iterations: 20
reserve_tokens: 16384
```

The sidebar uses approximate character-based counts. Its percentages are not exact provider token
counts. A large handoff output is not required to trigger the confirmed duplication bug.

## C0 — GUI continuation duplicated the complete history

**Status:** Fixed and committed in `ce37e29a`; deployment to the affected machine is unverified.

**Cause:** The GUI constructed a new `AgentLoop` with both the existing session log and messages
derived from that log. The constructor then seeded those messages into the already-populated log.
The API request was built from that log, so it contained duplicate conversation content, including
tool outputs.

```text
Expected: [existing history] [new user prompt]
Actual:   [existing history] [existing history] [new user prompt]
```

Repeated GUI continuations could repeat the duplication. The error occurred during preparation of
the next prompt, rather than requiring abnormal behavior from the preceding edit or handoff.

**Evidence:** The regression reproduction grew seven conversation messages to fourteen during the
first loop rebuild. The committed regression test checks three rebuild/run cycles, unchanged
surface nodes during reconstruction, and the exact history sent to the mocked provider.

**Fix:** Seed `initial_messages` only when `_session_log is None`. When a log is supplied, it remains
the source of truth. Message-only restore still seeds its history.

**Limit:** This prevents new duplication; it does not remove duplicates from existing sessions.

**Sources:** [GUI dispatch](../pyside_gui/_dispatch.py),
[AgentLoop constructor](../agent/loop.py),
[regression test](../tests/test_session_log_shadow.py)
(`TestResumeSeeding.test_gui_continuation_preserves_history_once_after_handoff`).

## C1 — No context budget check before sending a request

**Status:** Open. **Priority:** P1.

**Cause:** `AgentLoop.run` builds and sends the request before checking its size. The compaction
trigger runs after a successful non-handoff tool step, using the preceding response's
`prompt_tokens`. The handoff path returns before that check. Newly appended content is therefore
not protected by a fresh pre-request budget check.

**Evidence:** With `context_window=200000` and `reserve_tokens=16384`, an offline run sent an
840,000-character user prompt to the mocked API. The compaction hook was not called. This verifies
the absence of a guard; character count is not an exact provider-token measurement.

**Impact:** Correct configuration does not guarantee that outgoing requests fit the configured
window. A provider rejection can occur before automatic compaction has a chance to run.

**Recommended remedy:** Check the complete outgoing request against an explicit input budget,
including system content, tools, history, new content, and output reservation. Use provider-aware
counting where available and a documented conservative estimate otherwise. Compact when possible,
then recheck. If the request still cannot fit, stop with an actionable error before sending it.
The compaction request itself also needs a budget strategy; it must not simply forward an
already-oversized prefix to another provider call.

**Acceptance:** Oversized new prompts, restored histories, accumulated tool outputs, and inherited
requests cannot be sent unchecked. The guard also runs after compaction and on retry paths.

**Source:** [agent/loop.py](../agent/loop.py), request assembly around line 615 and handoff/compaction
ordering around lines 818–833.

## C2 — Cache errors allow full oversized tool output into context

**Status:** Open. **Priority:** P1.

**Cause:** `filter_tool_output` catches an `OSError` while caching a large result and returns the
original, unfiltered result. The caller only emits its truncation warning when filtering changes
the returned object, so this error path produces no warning.

**Evidence:** An injected disk-full `OSError` let a 4,800,000-character tool result enter the second
mocked provider request. No warnings were emitted. Dagi's character-divided-by-four estimator
counts that result as 1,200,000 tokens; this is not an exact provider count.

**Impact:** A filesystem failure disables the very protection intended to keep large tool results
out of context. This can cause a sudden increase even without history duplication.

**Recommended remedy:** Keep the context result bounded even if caching fails. Return a clear
cache-failure notice and, if appropriate, a bounded preview. Do not claim the full result was saved
when it was not.

**Acceptance:** Injected permission, disk-full, and other cache-write failures never put the full
oversized result into provider context and always produce an actionable diagnostic.

**Sources:** [tools/output_filter.py](../tools/output_filter.py), lines 78–81;
[agent/_tool_dispatch.py](../agent/_tool_dispatch.py), `bookkeep_tool_call`.

## C3 — GUI manual compaction fails before compaction starts

**Status:** Open. **Priority:** P1.

**Cause:** `_do_compact` assigns `loop.log.next_turn` without calling it. The resulting method
object is passed as the turn number to `log.append`. That append also occurs outside the worker's
`try` block.

**Evidence:** Reproducing that append raised:

```text
InvariantError: event data is not JSON-serialisable: method
```

**Impact:** The GUI command cannot start compaction through this path, blocking manual recovery.

**Recommended remedy:** Call `next_turn()`, handle transaction setup errors through the GUI error
path, and verify that maintenance compaction cannot overlap a normal run or another maintenance
operation. The concurrency concern was not independently reproduced in this audit.

**Acceptance:** Idle manual compaction starts with a valid integer turn, reports errors through the
GUI, and closes its maintenance turn correctly. Unsafe overlap is prevented.

**Source:** [pyside_gui/app.py](../pyside_gui/app.py), `_do_compact`, lines 360–361.

## C4 — Handoff leaves compaction usage missing or stale

**Status:** Open. **Priority:** P2.

**Cause:** `_last_prompt_tokens` starts at zero and is updated only after the handoff return path.
The tail-boundary calculation keeps everything when this value is zero. Passing `force=True`
does not bypass that condition.

**Evidence:** A fresh loop received a mocked handoff response reporting 210,000 prompt tokens.
Its stored `_last_prompt_tokens` remained zero. Calling `compact(force=True)` directly returned
`did_compact=False`. This reproduction bypassed the separate GUI command failure in C3.

**Impact:** A valid provider usage measurement may be displayed or logged while the compaction
code still acts on zero or stale usage. Forced compaction can silently do nothing.

**Recommended remedy:** Record usage consistently before response-specific exit paths. Define
forced compaction behavior when usage is unavailable, using the current request as evidence rather
than treating zero as proof that no reduction is necessary.

**Acceptance:** Handoff and text-only response paths update compaction accounting. Forced
compaction either reduces eligible history or explains why it cannot proceed.

**Sources:** [agent/loop.py](../agent/loop.py), lines 204 and 818–827;
[tools/compact/_tail_boundary.py](../tools/compact/_tail_boundary.py), line 74;
[agent/_compaction.py](../agent/_compaction.py), `compact`.

## C5 — A step-zero boundary can silently abort compaction

**Status:** Open. **Priority:** P2.

**Cause:** History selection includes step-zero entries for user messages and seeded history.
Compaction requires a matching `STEP_END` for its final summarized step. Such a record need not
exist for a step-zero entry, so selecting that boundary returns without compacting.

**Evidence:** Restored history followed by one handoff produced these coordinates:

```text
(0, 0) — seeded history
(1, 0) — new user message
(1, 1) — completed handoff step
```

With usage explicitly set to 190,000 tokens and a 20,000-token tail budget, selection chose
`(1, 0)` as the last step to summarize. No matching `STEP_END` existed. Forced compaction returned
false and the summarizer was never called. Explicitly setting usage isolated this issue from C4.

**Impact:** Compaction can skip otherwise eligible history at early turn boundaries. This does not
mean all restored sessions are permanently uncompactionable; later real steps can make the chosen
boundary eligible.

**Recommended remedy:** Define valid compaction boundaries for seeded history and user-message
entries. Select a completed structural boundary while preserving assistant/tool pairing, and make
an inability to select one observable.

**Acceptance:** Restored-history and early-turn scenarios compact correctly without missing or
duplicating messages. Summaries and retained tool calls/results remain structurally valid.

**Sources:** [agent/_compaction.py](../agent/_compaction.py), step collection and line 159;
[agent/loop.py](../agent/loop.py), seed coordinates around lines 497 and 529.

## C6 — Recent-history retention uses average size, not actual tail size

**Status:** Open. **Priority:** P2.

**Cause:** The tail selector divides total prompt tokens by the number of steps, then uses that
average to determine how many recent steps to retain. Recent steps can be much larger than older
ones, so the retained tail can greatly exceed `keep_recent_tokens`.

**Evidence:** A synthetic history had 90 steps of 100 tokens and 10 steps of 10,000 tokens:

```text
Total:                  109,000 tokens
Configured recent tail:  20,000 tokens
Selected tail:              18 steps
Actual example tail:    100,800 tokens
```

The selection helper was exercised directly. These are synthetic step sizes, not measurements
from the user's session or a live tokenizer.

**Impact:** Successful compaction can retain far more content than intended, leaving little room
for the summary or subsequent work.

**Recommended remedy:** Accumulate sizes backward over complete steps, accounting for the summary
and fixed request overhead. Define explicit behavior when one complete step alone exceeds the
budget. Verify the final request using C1's guard.

**Acceptance:** Uneven step sizes respect the intended tail budget, or yield an explicit oversized
step outcome. Tool-call/result pairs are never split.

**Source:** [tools/compact/_tail_boundary.py](../tools/compact/_tail_boundary.py), lines 82–85.

## Verification and limits

- The committed duplication regression failed before the fix and passed afterward.
- The relevant loop/session suites produced 79 passes and four failures. All four failures were
  reproduced with the original constructor behavior; they were not introduced by C0's fix.
- The existing failures were `reload_notice_reaches_the_log`,
  `large_handoff_result_gets_filtered`, `deferred_system_messages_land_after_all_tool_results`,
  and `pause_during_tool_suppresses_post_tool_thinking`. The last left a live thread that required
  interruption. The suite was not fully green.
- Follow-up findings used offline probes in the `dagi` Python environment with mocked provider
  calls. No live LLM API requests were made. These probes are not committed regression tests.
- The restore code inspected loads the last `session_end.raw_messages`, rather than rebuilding
  provider context from full tool audit records. No further duplication was found in that path.
- The shared inherited-agent loop has the same missing request guard; no separate subagent
  duplication defect was established.
- Existing duplicated sessions were not repaired. Deployment to the affected machine was not
  performed or verified. Exact attribution of the original incident remains unconfirmed.

## Recommended order

1. Add the pre-request guard and bounded cache-error handling: C1 and C2.
2. Restore reliable manual and automatic compaction: C3, C4, and C5.
3. Replace average-based tail selection and verify final request size: C6.
4. Add regression coverage for each failure mode before considering context protection complete.

These recommendations are not an approved implementation plan. This report adds no runtime fixes
beyond the previously committed C0 change.

## Related records

- [Investigation and audit evidence](../wiki/notes/gui-context-duplication-2026-09-18.md)
- [Earlier production review](../wiki/notes/production-review-2026-09-15.md)
