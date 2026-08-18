# Compact Cache Prefix — Design Spec

> 2026-08-18

## Problem

The `compact` subagent currently runs as a fresh subprocess via `run_subagent(preset="compact")`.
It starts a new `AgentLoop` with only the compact system prompt — it never sees the parent's
conversation messages. This means the LLM provider cannot reuse the KV cache from the parent's
prior API calls, wasting the entire cached prefix on every compaction.

The `context_spec.py` infrastructure (`spec_for_branch`, `reconstruct`) was built to support
subagent context inheritance but is not wired into the compact execution path.

## Solution

Convert the compact subagent from a subprocess to a **direct API call** within the parent
`AgentLoop`. The parent's existing `self.client` and message list provide perfect cache prefix
sharing with zero serialization.

### Why direct call, not subprocess

The compact subagent is already a special case:
- Internal-only (no `main.py` — not model-callable)
- No tools (`tools: []`, only auto-injected `write_handoff`)
- Uses `model_tier: main` (same model as the parent)
- Called synchronously from within the parent loop

A direct API call eliminates subprocess overhead, serialization concerns (base64 list-content),
and the `write_handoff` / `_ensure_handoff` machinery — the summary is extracted directly from
`resp.choices[0].message.content`.

### Cache sharing mechanism

The compact call sends only the **middle** messages (the portion to be summarized), not the
full conversation:

```
[system_prompt, middle_msg1, middle_msg2, ..., middle_msgN, compact_user_message]
```

This is a prefix of the parent's last request:

```
[system_prompt, middle_msg1, ..., middle_msgN, tail_msg1, ..., tail_msgM, last_user_msg]
```

Provider KV caches match on longest common prefix, so the entire middle's KV is reused. The
tail (~`keep_recent_tokens`, typically 20K tokens) is excluded — it doesn't need summarizing,
and the middle (which triggered compaction) is usually much larger.

### Compact prompt composition

The compact instructions and task are combined into a single trailing user message:

```
[rules from .dagi/subagents/compact/prompt.md]

---

Summarize the entire conversation above.

## Output
[default_handoff_spec from subagent_config.yaml]
```

No turn/step coordinates are referenced — the model summarizes everything it sees above the
compact prompt. The prior approach of referencing `turn {T} step {S}` is dropped because those
are internal bookkeeping with no meaning to the model.

## Changes

### `agent/loop.py` — `compact()` method

**Remove:**
- `run_subagent()` call with `preset="compact"` and `parent_log=self.log`
- Task string with turn/step references
- `BRANCH_START` logging (no branch is forked)

**Add:**
- `_load_compact_preset()` helper — reads `prompt.md` and `default_handoff_spec` from
  `.dagi/subagents/compact/`
- Slice `_messages[0:tail_boundary]` to get system prompt + middle messages
- Append a single user message with compact instructions
- Direct `self.client.chat.completions.create()` call with `self._extra_body`
  (preserves `cache_prompt`, reasoning, provider routing settings)
- Extract summary from `resp.choices[0].message.content`
- Feed into existing `_log_compaction()` — unchanged

**Unchanged:**
- `compute_tail_boundary()` — same step-based boundary logic
- `_log_compaction()` — same surface replace-op mechanics
- `_compact_context()` — same try/except wrapper (swallows failures)
- `CompactionResult` — same dataclass
- `_collect_steps()`, `_find_surface_index_for_step()` — same surface queries

### Compact call specifics

- **Non-streaming.** No delta callbacks needed for an internal summarization call.
- **No tool schema.** The compact call sends no `tools` parameter — pure text generation.
- **Error handling.** API errors (timeout, rate limit, empty content) propagate to
  `_compact_context()` which swallows them and returns `_NO_COMPACTION`.
- **Token tracking.** The compact call's usage is not counted in the parent's token
  counters, matching the current subprocess behaviour. `on_compaction(kept, removed)` fires
  as before.

### Files unchanged

- `.dagi/subagents/compact/prompt.md` — still the source of summarization rules
- `.dagi/subagents/compact/subagent_config.yaml` — still the source of `default_handoff_spec`
- `tools/compact/_tail_boundary.py` — boundary computation unchanged
- `tools/compact/__init__.py` — exports unchanged
- `agent/session_surface.py` — surface replace mechanics unchanged
- `agent/context_spec.py` — not used by this change (remains available for future
  subagent context inheritance work)

### Test impact

- `tests/test_compact_subagent.py` — tests that mock `run_subagent` need updating to mock
  `self.client.chat.completions.create` instead
- `tests/test_compact_integration.py` — surface replace-op tests stay the same (they test
  `_log_compaction`, not the API call)
- No new test files needed; existing test structure covers the changed code paths

## Non-goals

- Wiring `spec_for_branch` / `reconstruct` into other subagent types — this change is
  compact-specific.
- Tracking the compact call's token usage in the parent's counters.
- Streaming the compact call's response.
- Changing the compact preset files themselves.
