# Code Review — 2026-09-08

> **Scope:** All Python source excluding `tg/`, `tui/`, `scheduler/`, `snapshots/`,
> worktrees, and `archive/`.
>
> **Reviewed areas:** `agent/`, `tools/`, `pyside_gui/`, root scripts, `.dagi/` tools
> and skills, `tests/`.

---

## Critical — Fix First

### C1. Cross-thread read of bridge state

| | |
|---|---|
| **File** | `pyside_gui/app.py` lines 340-341 |
| **Category** | Correctness / thread safety |

`_on_stream_ended` runs on the **Qt main thread** (it's a `@Slot`) but reads
`self._bridge._stream_text` and `self._bridge._stream_reasoning` — fields that
`bridge.py` itself documents (lines 57-58) as:

> *"written and read exclusively on the agent worker thread. Never read them from
> the Qt main thread."*

This is a data race. It works today only because CPython's GIL serializes most
single-attribute reads, but it violates the code's own stated invariant and would
break under any future threading model change.

**Fix:** Have `stream_ended` carry the final text and reasoning as signal arguments
(`Signal(str, bool)`) so the worker emits them at signal-fire time — no cross-thread
field access needed.

---

### C2. Double JSON-encoding in `append_question`

| | |
|---|---|
| **File** | `pyside_gui/conversation.py` lines 102-103 |
| **Category** | Correctness / data encoding |

`_js_str` calls `json.dumps(text)`. Line 103 passes `json.dumps(options)` *into*
`_js_str`, producing `json.dumps(json.dumps(options))` — a double-encoded JSON
string. The JS side receives a string literal where it expects an array.

```python
# Current (broken)
f"{self._js_str(json.dumps(options))}, "

# Correct
f"{json.dumps(options)}, "
```

**Fix:** Pass `json.dumps(options)` directly (not wrapped in `_js_str`), since it's
already JSON.

---

### C3. Latent `ImportError` in dead stub

| | |
|---|---|
| **File** | `agent/loop.py` lines 805-815 |
| **Category** | Dead code / latent crash |

`_handle_write_handoff` imports `handle_write_handoff` from `agent._tool_dispatch` —
but that function was renamed to `handle_end_turn`. If ever called, this crashes at
runtime. No current caller exists, making it dead code *and* a landmine.

**Fix:** Delete the method entirely.

---

## Dead Code — Safe Deletes

### D1. Copied helpers in `_loop_helpers.py`

| | |
|---|---|
| **File** | `agent/_loop_helpers.py` lines 26-54, 89-112 |

`_format_tools_and_skills`, `_SafePlaceholder`, and `_SafeDict` are copy-duplicates
of the live versions in `agent/_system_prompt.py`. Nothing imports them from
`_loop_helpers`. The canonical versions live in `_system_prompt.py`.

---

### D2. `format_skills_for_prompt` never called

| | |
|---|---|
| **File** | `agent/skills.py` lines 136-151 |

Dead since at least June 2026. The actual skill formatting is done by
`_format_tools_and_skills` in `_system_prompt.py`.

---

### D3. Module-level `registry` singleton

| | |
|---|---|
| **File** | `agent/registry.py` line 57 |

A bare `ToolRegistry()` instance is created at import time. Nothing imports or uses
`agent.registry.registry` — every caller uses `create_tool_registry()` in `tools.py`.

---

### D4. `_root_tracker` never called

| | |
|---|---|
| **File** | `agent/session.py` lines 316-319 |

Defined but never called. The same logic is inlined in `finish()` (lines 240-242).

---

### D5. Affect controller remnants

| | |
|---|---|
| **File** | `agent/session.py` lines 100-112 |

`_affect_controller`, `bind_affect_controller`, `owns_affect_controller`, and the
`affect_controller` property are all orphaned. The affect system was replaced by
`ExpressionController` (`lifecycle.py` / `bind_expression_controller`). No call sites
remain.

---

### D6. Plan mode shim — entire file

| | |
|---|---|
| **File** | `agent/_plan_mode.py` (whole file) |

Contains only a one-line re-export for removed plan mode. Zero imports across the
codebase.

---

### D7. `AskUserDialog` — ~107 lines of dead widget

| | |
|---|---|
| **File** | `pyside_gui/overlays.py` lines 68-174 |

Never instantiated anywhere. The actual ask-user flow is handled entirely through
`ConversationView.append_question` (JS-side), `AgentBridge.ask_user_requested`, and
the `PromptInput` submission path. Several CSS selectors in `_OVERLAY_CSS` only apply
to this dead class.

---

### D8. `expression_changed` signal — never connected

| | |
|---|---|
| **File** | `pyside_gui/bridge.py` line 47, 176-177, 204 |

Declared and emitted but never connected in `app.py`. Only `process_state_changed`
is connected.

---

### D9. `plan_shown` signal — never connected

| | |
|---|---|
| **File** | `pyside_gui/bridge.py` line 50, 173-174, 210 |

Same issue as D8. Plan polling is done by a timer in `_poll_plan`, so this signal
is unused.

---

### D10. `_resolve_inherited_model` — zero callers

| | |
|---|---|
| **File** | `tools/subagent_main.py` lines 182-194 |

Grep confirms no caller outside one test. Residual from v1-to-v2 fork-context
migration. Remove the function and its test.

---

### D11. Redundant `import json` inside function body

| | |
|---|---|
| **File** | `tools/subagent_main.py` line 537 |

`json` is already imported at module level (line 11). The local re-import is
redundant.

---

### D12. `--base-url` argument accepted but value never consumed

| | |
|---|---|
| **File** | `main.py` line 22 |

`args.base_url` is only checked for truthiness to print a deprecation warning
(line 27). The value itself is never passed anywhere. Either remove the argument
or convert to `deprecated=True` (Python 3.12+).

---

## Bloat — Functions Exceeding Size / Complexity Limits

### B1. `AgentLoop.run()` — ~270 lines, nested retry loop

| | |
|---|---|
| **File** | `agent/loop.py` lines 515-781 |
| **Inner retry** | lines 566-662 (~100 lines, 4 break/continue exits) |

The inner `while True` retry loop handles API calls with three distinct exception
handlers plus ghost-response handling. Control flow is hard to trace with nested
break/continue exits.

**Fix:** Extract `_call_api_with_retry(request, create_kwargs) -> tuple[response, bool]`
returning `(response, paused_on_error)`. This isolates the retry policy and makes it
unit-testable.

---

### B2. `compact()` — 167 lines

| | |
|---|---|
| **File** | `agent/_compaction.py` lines 107-273 |

Four distinct phases inlined: compute boundary, locate structural data, build fork
context, validate and accept result.

**Fix:** Extract `_find_compact_boundary()` and `_accept_compaction_result()`.

---

### B3. `create_tool_registry()` — 150 lines, deep nesting

| | |
|---|---|
| **File** | `agent/tools.py` lines 113-262 |

Registers ~20 tool types with heterogeneous conditionals interleaved. Cyclomatic
complexity is high.

**Fix:** Split into `_register_core_tools()`, `_register_subagent_tools()`, etc.

---

### B4. `subagent_main.py` — 739-line file, three modes in one module

| | |
|---|---|
| **File** | `tools/subagent_main.py` |

Three execution modes (pipe, compact-fork, inherited-fork) in a single module.

**Fix:** Consider splitting into `subagent_main_pipe.py`,
`subagent_main_compact.py`, `subagent_main_inherited.py` with a thin dispatcher.

---

### B5. `run_subagent()` — 15 parameters

| | |
|---|---|
| **File** | `tools/subagent_api.py` lines 258-275 |
| **Limit** | Project rule caps positional parameters at 5 |

**Fix:** Group into `SubagentOptions` and `ForkOptions` dataclasses. Move
mutual-exclusion guard logic into `ForkOptions.__post_init__`.

---

### B6. Double disk read of `soul.md` and `AGENTS.md`

| | |
|---|---|
| **File** | `agent/_system_prompt.py` lines 78-153 |

`build_preamble()` and `assemble_system_string()` both read `soul.md` and both
`AGENTS.md` files from disk. The content is read twice per system-prompt assembly.

**Fix:** Read once, pass the loaded content between functions.

---

### B7. `simplify()` — 149 lines

| | |
|---|---|
| **File** | `.dagi/skills/review-session/parse_jsonl_logs.py` lines 64-213 |

Six `elif rtype ==` branches, each with substantial logic.

**Fix:** Extract per-type helpers (`_simplify_message`, `_simplify_tool_end`,
`_simplify_subagent`).

---

### B8. `_render_tool()` — 115 lines

| | |
|---|---|
| **File** | `scripts/build_api_tools.py` lines 218-333 |

**Fix:** Split into `_render_header`, `_render_auth`, `_render_body`.

---

### B9. `_on_input_submitted()` — 44 lines, cyclomatic complexity ~8

| | |
|---|---|
| **File** | `pyside_gui/app.py` lines 193-237 |

Three distinct branches (pending-ask reply, inject-and-resume while paused, normal
dispatch) stacked with interleaved early returns.

**Fix:** Extract `_handle_pending_ask(text) -> bool` and
`_handle_paused_inject(text) -> bool`, each returning `True` if they consumed the
input.

---

## Improvement Opportunities

### I1. `EmoteTool` guard always passes

| | |
|---|---|
| **File** | `agent/tools.py` lines 181-184 |
| **Severity** | Medium — logic bug |

The guard checks `on_message_board_post is not None`, but the default in
`AgentCallbacks` is a no-op lambda (always truthy). `EmoteTool` is always registered,
even when no actual board is wired up.

**Fix:** Add `enable_message_board: bool = False` sentinel to `AgentCallbacks`.

---

### I2. Near-identical `_apply_worker_config` / `_apply_advanced_config`

| | |
|---|---|
| **File** | `tools/subagent_main.py` lines 35-68 |
| **Severity** | Medium — 34 lines duplicated |

Both functions do the same `replace(config, model=X.model, ...)` dance with 9 fields,
differing only in which sub-config they read.

**Fix:** Collapse to `_apply_tier_config(config, tier)`.

---

### I3. Private attribute access on `ToolRegistry`

| | |
|---|---|
| **File** | `agent/_tool_dispatch.py` line 49 |
| **Severity** | Low |

Accesses `loop.registry._tools.get(name)`. `ToolRegistry` has a public `get(name)`
method.

---

### I4. `_extract_reasoning` called twice for same message

| | |
|---|---|
| **File** | `agent/loop.py` lines 667, 680 |
| **Severity** | Low |

Store once, reuse.

---

### I5. Token aggregation duplicated in `finish()`

| | |
|---|---|
| **File** | `agent/session.py` lines 237-302 |
| **Severity** | Low |

Child and root paths both use the same list-comprehension pattern. Extract
`_aggregate_tokens(nodes)`.

---

### I6. Fragile header-swap trick in `wtf.py`

| | |
|---|---|
| **File** | `agent/wtf.py` lines 74-78 |
| **Severity** | Medium |

Mutates `loop._messages[0]` directly with no comment explaining the invariant.
Relies on `_sync_messages` always resetting `_messages[0]` to the system header.

**Fix:** Use `_log_user_message_no_sync` variant or document the invariant.

---

### I7. No type validation in `_build_config_from_entry`

| | |
|---|---|
| **File** | `agent/config_loader.py` lines 142-201 |
| **Severity** | Low |

`context_window`, `reserve_tokens`, etc. are read with no validation — a string value
would propagate silently.

---

### I8. `TelegramConfig` in core config loader

| | |
|---|---|
| **File** | `agent/config_loader.py` lines 66-84 |
| **Severity** | Low |

Telegram-specific definitions live in the core config module. Should be in `tg/`.

---

### I9. Schema/code contract mismatch in `confidence_decay`

| | |
|---|---|
| **File** | `.dagi/tools/confidence_decay.py` lines 56, 67 |
| **Severity** | Low |

`decay_rate` is `required` in the JSON schema but has a Python default of `0.005`.

---

### I10. Generated HTTPError handler can dereference `None`

| | |
|---|---|
| **File** | `scripts/build_api_tools.py` lines 325-329 |
| **Severity** | Medium |

```python
body_preview = exc.response.text[:500] if exc.response is not None else ''
return f"HTTP {exc.response.status_code}: {body_preview}"
#           ^^^^^^^^^^^^^^^^^^^ can be None if response is None
```

The `status_code` access on the next line is unguarded.

---

### I11. `build_fork_context` (v1) — last v1 consumer + false-pass test

| | |
|---|---|
| **File** | `tools/subagent_api.py` lines 83-110 |
| **Severity** | Low |

Migration target. Also: a test asserts `build_fork_context_v2` is re-exported from
`subagent_api` — it isn't. The test passes because it imports from
`agent.parent_context` directly in the same file.

---

### I12. `_system_breakdown` recomputes on every context update

| | |
|---|---|
| **File** | `pyside_gui/right_sidebar.py` lines 229-255 |
| **Severity** | Low |

Reads and tokenises files from disk on every `update_context` call. Should cache
and invalidate on path change.

---

### I13. `sim_nodes.index()` is O(n) per call inside a loop

| | |
|---|---|
| **File** | `agent/context_spec.py` lines 88-89 |
| **Severity** | Low |

For long sessions (thousands of surface events), `index()` is a linear scan per
replace operation. Use a dict-backed index.

---

## Recommended Priority Order

1. **C1-C3** — Cross-thread race, double-encoding bug, dead stub with latent crash
2. **D7, D5, D6, D1-D2** — Biggest dead-code cleanups (AskUserDialog, affect
   remnants, plan mode shim, copied helpers)
3. **B1** — Extract retry loop from `run()` (highest-impact readability win)
4. **I1** — Fix EmoteTool guard (logic bug silently defeats the check)
5. **B2-B3** — Decompose `compact()` and `create_tool_registry()`
6. **Remaining D, I, B items** — in any convenient order during normal development

---

## Summary Counts

| Category | Count |
|----------|-------|
| Critical | 3 |
| Dead code | 12 |
| Bloat | 9 |
| Improvements | 13 |
| **Total** | **37** |
