# DAGI Self Code Review

> **Date:** 2026-08-26 | **Reviewer:** Dagi-chan (self-review) | **Scope:** main working tree, excluding `.claude/worktrees/*`, `archive/`, tests unless noted
> **Mode:** Findings only — no fixes applied.

---

## 1. 🔴 The God Class: `agent/loop.py` (~1,850 lines)

Violates the project's own **500-line file cap by nearly 4×**:

| Method | Span | Size |
|---|---|---|
| `run()` | 1031–1310 | **~280 lines** (cap: 100) |
| `__init__()` | 328–481 | ~153 lines |
| `compact()` | 829–975 | ~146 lines |

`run()` alone handles: `/reload` short-circuit, wiki-index injection, session slug generation, pause checkpoints, dual retry loops (connection errors AND ghost responses, each with its own counter), streaming vs blocking paths, exit-flag string parsing, continuation injection, token accounting, and compaction triggering. Estimated cyclomatic complexity 20+ against a stated limit of 8.

The module mixes at least six responsibilities: config dataclasses, callback dataclasses, prompt formatting, sentinel escaping, wiki index building, and plan-mode lifecycle management.

Mirror image: `tests/test_agent_loop.py` at 1,189 lines — test bloat tracks source bloat.

## 2. 🟠 Constructor With Two Personalities

`AgentLoop.__init__` takes **11 parameters, 7 of them underscore-private** (`_registry`, `_parent_tracker`, `_tracker`, `_subagent_id`, `_bash_tool`, `_system_prompt_override`, `_preserve_request_prefix`). The privates serve the forked-subagent path while dodging the ≤5-positional-param rule — naming convention doing the work an interface split should do. Suggests `AgentLoop.main(...)` vs `AgentLoop.forked(...)` factories.

## 3. 🟠 String-Sentinel Protocol Is Fragile By Design

Control flow hinges on exact substrings: `<<END_OF_RESPONSE>>`, `<<HANDOFF_WRITTEN>>`, plus sentinels scattered across tool modules (`ENTER_PLAN_MODE_SENTINEL`, `RELOAD_SKILLS_SENTINEL`, `parse_switch_sentinel`, …).

- **Duplication drift already happened**: `"## Session Context"` is defined independently in both `agent/dynamic_context.py` and `agent/session_log.py`.
- **Legacy baggage**: `TASK_END_FLAG` kept as legacy alias adds a permanent third branch to every exit check.
- **`_escape_sentinels()`** munging `<<` → `< <` is a text-level bandage; the defense must be applied everywhere output touches history and nothing enforces that.

No single `agent/protocol.py` owns these constants.

## 4. 🟠 `AgentConfig`: A 40-Field Config-State Chimera

Conflates model params, compaction tuning, plan-mode *mutable runtime state* (`plan_file`, `previous_branch`, `active_plan_file`), UI labels (`display_name`), affect knob values, service URLs — and recursively embeds full copies of itself (`worker_config`, `advanced_config`), so every sub-config drags along 40 irrelevant fields. Contains a self-documented dead field (`bash_backend`, "now a no-op").

Candidate decomposition: `ModelConfig` / `CompactionConfig` / `PlanModeState` / `AffectConfig`.

## 5. 🟠 TUI ↔ PySide Duplication (Empirically Costly)

Measured line overlap:
- `tui/commands.py` vs `pyside_gui/commands.py`: **91 identical lines** (~30%)
- `tui/callbacks.py` vs `pyside_gui/bridge.py`: **47 identical lines**

Errors-log evidence of the cost: the **2026-08-23** entry says the `_pending_ask` fix "only covered done/paused, and the TUI never got it." Same bug, fixed twice, one missed. A shared session-controller layer would collapse most of this.

## 6. 🟡 Retry Logic Copy-Pasted Three Ways

Inside `run()`, the connection-error and `APIStatusError` branches contain a **verbatim-duplicated** exhaustion/pause block (~12 lines each). Separately, `tools/subagent_main.py` has `_compact_call_with_retry`. Three hand-rolled retry implementations, no shared policy.

## 7. 🟡 Global Mutable State + Silent Swallows in Subagent Runner

`tools/_subagent_runner.py` uses module-level `_active: dict[int, _SubagentState]` — a process-wide singleton. Two sessions in one process would contend over it; tests become order-dependent. Additionally `_stream_stdout` and `_drain_stdout` end in `except Exception: pass`, violating the repo's own "never swallow exceptions silently" rule. Same pattern recurs in `tui/notifications.py` and `pyside_gui/app.py`.

## 8. 🟡 Inverted Layering: Core Depends Upward on Tools

`agent/loop.py` imports from `tools.subagent_api`, `tools.compact._tail_boundary`, `tools.plan_mode`, `tools.switch_model`, `tools.output_filter`. Meanwhile `tools/subagent_main.py` imports `agent.loop`. Core and plugins are mutually entangled, kept import-safe only by deferred imports inside `__init__`. Sentinels living in tool modules force this — another vote for a bottom-layer protocol/constants module.

## 9. ⚪ Housekeeping

- `.claude/worktrees/*` contains four near-full tree copies (including loop.py ×4) — poisons grep/find with false hits.
- Root-level `hist.py` (113 lines) — cryptic name, unclear ownership.
- Broad `except Exception`: 5× in loop.py, 4× in agent/tools.py — some defensible (dynamic plugin imports), worth an audit.

---

## ✅ What's Good

- Docstrings explain *why*, not just *what* — excellent throughout.
- Idempotent `_close_turn` + `finally` guard is a thoughtful well-formedness net.
- `AgentCallbacks` with no-op defaults keeps headless paths zero-cost — clean observer pattern.
- Event-sourced `SessionLog` design is solid architecture.
- Recent bug fixes show errors-log lessons feeding back into code.

## Priority Order for Fixes

1. Extract `run()`'s retry machinery → one `ApiCallPolicy` (kills #1 + #6 together)
2. Single `protocol.py` for sentinels (#3 + #8)
3. Shared UI controller for TUI/PySide (#5)
4. Split AgentConfig (#4)
5. Instance-owned subagent manager (#7)
