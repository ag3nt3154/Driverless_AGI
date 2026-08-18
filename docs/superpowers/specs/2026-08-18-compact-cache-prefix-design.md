# Compact Cache Prefix — Design Spec

> 2026-08-18

## Problem

The `compact` subagent currently runs as a fresh subprocess through
`run_subagent(preset="compact")`. It starts a new `AgentLoop` with the compact preset's system
prompt and tool registry, but it never receives the parent's conversation prefix. Its first
provider request therefore cannot reuse the parent's warm prompt cache.

The session-log tree already has the primitives needed to describe inherited context:
`BRANCH_START`, `ContextSpec`, `spec_for_branch()`, and `reconstruct()`. They currently model a
branch created at the parent's latest open step. Compaction needs a retroactive branch whose
logical fork is an earlier completed step, before the recent steps that remain verbose.

## Goals

- Keep compact as an isolated subprocess subagent.
- Fork the compact branch immediately after the last step selected for summarization.
- Reconstruct the exact parent request prefix through that completed step.
- Preserve the parent model, system header, tool schemas, tool order, and prompt-affecting
  request settings so provider-side cache reuse remains possible.
- Produce the cumulative summary as a standard handoff artifact.
- Replace the summarized main-branch surface span with the handoff while leaving the retained
  tail events in place.
- Preserve every original event in the append-only log for audit and replay.
- Make later context construction skip shadowed events and include the summary plus retained and
  newly appended steps.

## Non-goals

- Direct in-process summarization from `AgentLoop.compact()`.
- Physically duplicating retained main-branch events under new step numbers.
- Allowing the compact model to execute any inherited parent tool.
- Wiring inherited context into every other subagent type in this change.
- Changing the tail-size heuristic in `compute_tail_boundary()`.
- Guaranteeing a cache hit. Provider routing, expiry, minimum prefix size, and cache-breakpoint
  behavior remain provider-dependent.

## Core invariants

1. **Completed-step fork.** The compact prefix ends at a `STEP_END`; it never divides an
   assistant message from its tool results.
2. **Append-only history.** Original main-branch events are neither deleted nor copied.
3. **Exact inherited prefix.** The compact request reuses the triggering request's header,
   selected messages, model, tool schemas, tool ordering, and prompt-affecting settings.
4. **No compact-only provider tools.** The compact request does not add `write_handoff` or any
   other schema that was absent from the parent request.
5. **No compact tool execution.** A tool-call response from the compact model is a failed
   compaction and causes no parent-surface mutation.
6. **Atomic acceptance.** The parent changes its active surface only after validating a complete
   handoff against the surface generation from which the branch was created.
7. **Provenance-preserving replacement.** The compaction event cites every shadowed surface node
   in `source_seqs` and records the compact branch that produced it.
8. **In-place synchronization.** Rebuilding `_messages` continues to use slice assignment so
   existing bindings retain the same list object.

## Terminology

- **Summarized span:** Active main-branch steps selected for compression.
- **Retained tail:** Recent complete steps that remain verbatim in the next request.
- **Logical fork:** The completed parent step through which the compact branch inherits context.
- **Physical branch event:** The later `BRANCH_START` append that records the logical fork.
- **Triggering request snapshot:** The immutable provider-request identity captured when the API
  request whose usage triggered compaction was sent.

## Architecture

### 1. Select the summarized span and retained tail

`AgentLoop.compact()` continues to call `compute_tail_boundary()` with active surface steps and
the last prompt-token count. Given main turn 1 steps 1–10 and a tail of steps 9–10:

```text
summarized steps: 1–8
retained steps:   9–10
logical fork:     STEP_END for step 8
```

The implementation resolves three structural values from the log rather than treating a step
index as a message index:

- The `STEP_END.seq` for the final summarized step.
- The first live surface node belonging to the summarized span.
- The last live surface node before the retained tail's first step.

If the summarized span is empty, its final step is incomplete, or either replacement edge is no
longer live, compaction is a no-op.

### 2. Record a retroactive branch

The parent appends `BRANCH_START` when compaction triggers, but the event records the earlier
logical cutoff:

```json
{
  "branch": "compact_ab12cd34",
  "parent_branch": "main",
  "turn": 1,
  "step": 8,
  "parent_cut_seq": 123,
  "parent_surface_generation": 0
}
```

`parent_cut_seq` identifies the completed `STEP_END` after step 8. It is distinct from the
`BRANCH_START` event's own sequence number, which is appended after steps 9–10 already exist.

`reconstruct()` uses `parent_cut_seq` when present and falls back to the physical branch-event
sequence for existing branch records. This preserves the behavior of ordinary subagents while
allowing compaction to fork from earlier history.

`SessionLog.branches` may continue exposing `(parent_branch, turn, step)` for ancestry traversal.
The cutoff and surface generation remain durable fields on the corresponding `BRANCH_START`
event and are read when reconstructing or accepting the branch.

### 3. Reconstruct and serialize the inherited prefix

After recording the branch, the parent builds `spec_for_branch(log, branch_id)` and calls
`reconstruct()`. The compact branch has no branch-local surface events yet, so reconstruction
returns:

```text
parent system header
active parent messages through the logical fork
```

Prior compaction summaries in that prefix are included, while the raw events they shadow remain
excluded by the simulated surface.

The parent writes a short-lived fork-context JSON file with format version 1:

```json
{
  "version": 1,
  "branch": {
    "id": "compact_ab12cd34",
    "parent_cut_seq": 123,
    "parent_surface_generation": 0
  },
  "request": {
    "model": "provider/model-id",
    "active_tier": "default",
    "base_url": "https://provider.example/v1",
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "..."}
    ],
    "tools": [],
    "parallel_tool_calls": false,
    "extra_body": {}
  }
}
```

The context file must not contain API keys or other credentials. The child resolves credentials
through the existing configuration/environment path and validates that the resulting model and
base URL match the triggering request snapshot. The runner retains the context file while a
timed-out child remains resumable, then deletes it with the task file on every terminal success,
failure, or forced-kill path.

The snapshot comes from the provider request that produced the usage triggering compaction. It
must not be rebuilt from mutable `self.config`, because a tool in the retained step may switch
the active model after that request returns.

### 4. Run the compact branch subprocess

`run_subagent()` remains the public entry point and continues to return `SubagentResult`. The
compact call supplies the fork-context path in addition to the preset and handoff path. The
generic runner forwards it to `tools.subagent_main` through a dedicated CLI argument.

The compact subprocess uses a specialized forked-context execution path:

1. Read and validate the fork-context version and required fields.
2. Resolve the inherited model configuration. Compact uses `model_tier: inherit`; it must not
   fall through to the worker configuration.
3. Load `prompt.md` and `default_handoff_spec` with the existing project-first preset resolution.
4. Append one user message containing the compact instructions and output contract.
5. Make a non-streaming provider call with the inherited model, prefix, tool schemas, tool order,
   `parallel_tool_calls`, and prompt-affecting extra-body settings.
6. Apply the normal bounded transient-error and ghost-response retry policy.
7. Reject responses with tool calls, missing text, or a truncation finish reason.
8. Write the validated assistant text to the standard handoff path.
9. Return normal subprocess status and usage/cache metadata to the parent.

The provider-visible tool schemas are inherited only to preserve the rendered prompt prefix.
The compact execution allowlist is empty. The child never dispatches an inherited tool.

The existing automatic `write_handoff` injection is disabled only for this forked compact mode.
Adding that compact-only schema would change the provider prefix. The subprocess harness writes
the final assistant text as the handoff instead, preserving the handoff contract without asking
the model to call a new tool.

The compact task is appended after the inherited prefix:

```text
[rules from .dagi/subagents/compact/prompt.md]

---

Summarize the entire conversation above.

## Output
[default_handoff_spec from subagent_config.yaml]
```

No turn or step coordinates appear in the model instruction; the reconstructed input already
defines the complete scope.

### 5. Validate and install the handoff

The parent does not mutate its surface merely because the subprocess exited successfully. It
first verifies:

- `SubagentResult.is_ok` is true.
- The handoff is non-empty and verified.
- The child returned no tool call or truncated response.
- The branch's recorded surface generation still matches the parent surface generation.
- Every replacement source node is still live and the replacement edges still bound the same
  summarized span.

On success, the parent increments `_compaction_generation`, wraps the handoff in the existing
context-summary header, and appends `CONTEXT_COMPACTION`:

```json
{
  "summary": "[CONTEXT SUMMARY ...]",
  "removed": 8,
  "generation": 1,
  "branch": "compact_ab12cd34",
  "handoff": ".dagi/handoffs/compact_ab12cd34.md"
}
```

The event uses:

```text
surface_op = ("replace", first_summarized_seq, last_summarized_seq)
source_seqs = every live surface node in the summarized span
```

The replacement appears at the summarized span's former surface position. The retained tail
already follows it, so no tail events need to be appended again. `_sync_messages()` then rebuilds
the parent message cache in place.

The parent emits `on_compaction(kept, removed)` and records child prompt, completion, reasoning,
cache-read, cache-write, model, provider, branch, and generation metadata without replacing
`_last_prompt_tokens` with the compact request's usage.

On child error, timeout, empty/unverified handoff, stale generation, or invalid replacement span,
the main surface remains unchanged. The failed branch record and child logs remain available for
diagnosis.

### 6. Construct later main-branch context

The raw log after the example remains:

```text
turn 1 steps 1–10: original immutable events
branch/start: compact branch logically forked after step 8
context/compaction: handoff replacing the active surface span for steps 1–8
```

The next model-facing context is:

```text
turn 0: system/header
context summary: handoff covering steps 1–8
original turn 1 step 9
original turn 1 step 10
next action: turn 1 step 11
```

The retained steps are logical replays in the newly derived request, not duplicated raw events.
This avoids duplicate tool-call IDs, duplicate side effects, and ambiguous provenance.

`_collect_steps()` continues reading only live surface events. Shadowed steps 1–8 therefore do
not participate in later boundary calculations. The coordinate-free compaction summary remains
in scope, retained steps 9–10 keep their original coordinates, and new steps are appended
normally.

A later compact branch receives the prior cumulative summary plus whichever retained and new
steps fall into its summarized span. Accepting that handoff replaces the prior summary and those
newly summarized nodes with the next cumulative summary.

## Failure handling

| Failure | Parent behavior |
| --- | --- |
| No completed middle | Return `_NO_COMPACTION`; do not create a branch. |
| Fork reconstruction fails | Record the warning; leave the surface unchanged. |
| Child config does not match the request snapshot | Fail the branch before inference. |
| Transient provider error | Retry within the configured bound, then fail unchanged. |
| Tool-call response | Reject it; never dispatch the tool. |
| Empty or truncated response | Reject it; leave the surface unchanged. |
| Timeout | Preserve resumable child state; do not install a handoff yet. |
| Unverified fallback handoff | Reject it for compaction. |
| Parent surface generation changed | Reject the stale handoff. |
| Replacement source is no longer live | Raise the invariant error; keep the surface unchanged. |

## Files affected

- `agent/loop.py` — request snapshot capture, compact orchestration, handoff acceptance, metrics.
- `agent/context_spec.py` — honor retroactive `parent_cut_seq` during reconstruction.
- `agent/session_log.py` — validate and expose retroactive branch metadata as needed.
- `tools/subagent_api.py` — build/pass the compact fork context and preserve branch provenance.
- `tools/_subagent_runner.py` — forward and clean up the fork-context file.
- `tools/subagent_main.py` — inherited compact mode, model-tier handling, handoff writing.
- `.dagi/subagents/compact/subagent_config.yaml` — change the compact tier to `inherit`.
- `tests/test_context_spec.py` — retroactive fork reconstruction and safe-cut coverage.
- `tests/test_subagent_api.py` — fork-context serialization, secret exclusion, and cleanup.
- `tests/test_subagent_runner.py` — CLI forwarding and timeout lifecycle.
- `tests/test_subagent_main.py` — inherited request identity and handoff behavior.
- `tests/test_compact_subagent.py` — compact orchestration, validation, callbacks, and usage.
- `tests/test_compact_integration.py` — summary-plus-original-tail and repeated compaction.

The compact prompt remains the source of summarization rules. `tools/compact/_tail_boundary.py`,
`tools/compact/__init__.py`, and the surface projection format remain unchanged unless tests expose
a missing structural query.

## Test requirements

### Context reconstruction

- A branch physically appended after step 10 with `parent_cut_seq` at step 8 reconstructs only
  the active parent prefix through step 8.
- Existing branch records without `parent_cut_seq` retain current behavior.
- Prior compaction replacements are honored inside the reconstructed prefix.
- A cutoff cannot split an assistant tool call from any of its tool results.

### Cache-compatible request construction

- The compact request prefix equals the triggering parent request prefix through the logical
  fork, including byte-identical message dictionaries.
- Model id, tool schema content, tool order, `parallel_tool_calls`, reasoning, caching, and
  provider-routing settings match the triggering request snapshot.
- The inherited prefix excludes the ephemeral board and retained tail.
- The compact instructions are the first provider-visible difference after the shared prefix.
- No `write_handoff` schema is added.

### Subprocess and handoff

- Fork-context files contain no API key and are removed on all terminal paths.
- `model_tier: inherit` resolves the triggering parent model rather than the worker model.
- Final assistant text is written as a verified handoff.
- Tool-call, empty, truncated, and exhausted-retry responses produce a failed result.
- Inherited tool calls are never dispatched.

### Parent surface integration

- Successful compaction produces `summary -> original retained tail` in the derived messages.
- Raw summarized and retained events remain present exactly once in the append-only log.
- The compaction event cites every shadowed node and the producing compact branch.
- A failure or stale surface generation leaves nodes, messages, and generation unchanged.
- `_messages` retains its list identity after synchronization.
- A second compaction includes the prior summary and skips its shadowed source events.
- Cache and token metrics are attributed to the compact branch without changing the main
  compaction threshold's prompt-token value.

## Acceptance criteria

1. Compact still executes as a subprocess and returns `SubagentResult` with a verified handoff.
2. Its first provider request is cache-compatible with the triggering parent request through the
   chosen completed-step fork.
3. The child receives none of the retained tail and cannot execute parent tools.
4. Successful installation yields summary plus the untouched retained tail in the next main
   request.
5. No original log event is deleted or duplicated.
6. Later context construction excludes shadowed sources and carries the cumulative summary
   forward.
7. Every failure before handoff acceptance leaves the parent surface unchanged.
8. Tests cover retroactive reconstruction, request identity, subprocess handoff behavior,
   replacement provenance, failure atomicity, and repeated compaction.
