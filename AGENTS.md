# AGENTS.md

> Last updated: 2026-08-30 | [README](README.md) | [TODO](TODO.md)




---

## Overview

Driverless AGI (dagi) is a Python agentic coding assistant. 

## Rules

- Use `DEFAULT_PYTHON_ENV` for all Python scripts and package installs.
- Always update `AGENTS.md` after completing a task.

## Behavioral Guidelines

> This section is stable protocol/standards content — preserve verbatim across
> routine `update-project-context` runs; only edit it when the user gives an
> explicit standing behavioral instruction.

### Coding standards

- Functions: <= 100 lines
- Cyclomatic complexity: <= 8
- Positional parameters: <= 5
- Line length: 100 characters
- Files: <= 500 lines

### Calibrate to Ambiguity

- **High ambiguity** (vague or conceptual): ask clarifying questions before acting
- **Medium ambiguity**: ask targeted questions on gaps, then proceed
- **Low ambiguity**: verify quickly and proceed
- **Trivial changes**: trust user intent — don't over-process obvious requests (e.g. "fix typo", "add tooltip")

### Before Acting

- **State assumptions.** Don't smuggle them. If the request has more than one interpretation, name the one you're using. If it could materially change the answer, ask first.
- **Read before write.** Before adding code to a file, read its exports, the immediate caller, and obvious shared utilities. "Looks orthogonal" is the warning sign.
- **Project consequences.** Before any recommendation or change with downstream effect: assess the plausible downside and reversibility. If material, escalate care.

### During Execution

- **Simplicity first.** Minimum code that solves the problem. Nothing speculative. No abstractions for single-use code. No features beyond what was asked.
- **Surgical scope.** Touch only what the task requires. Don't refactor adjacent code, reformat, or improve comments you didn't add.
- **Match conventions.** Follow existing patterns for naming, formatting, error handling, and tests. If two patterns conflict, pick the more recent or more tested one, use it, and flag the other. Conformance over taste.
- **Model for judgment; code for determinism.** Use the model for classification, drafting, summarization, extraction. Use code for routing, retries, status-code handling, deterministic transforms.
- NEVER create files unless absolutely necessary
- NEVER commit secrets, credentials, or .env files

### Verify Invariants Before Shipping

For non-trivial changes, confirm before shipping:

- [ ]  State ownership and consistency clear?
- [ ]  Feedback / observability in place?
- [ ]  Blast radius understood?
- [ ]  Timing and ordering safe?
- [ ]  Follows existing patterns (or intentionally breaks them)?
- [ ]  Security / obvious risks addressed?

If any are unclear → flag explicitly, ask, or defer.

### After Acting

- **Ground claims.** Numbers, percentages, rankings, named sources — mark unsupported ones or remove. Bounded language over invented specificity.
- **Fail loud.** "Done" is wrong if anything was skipped silently. "Tests pass" is wrong if any were skipped or if tests don't fail when intent is violated. Surface uncertainty — don't hide it.
- **Checkpoint.** After each significant step, name what was done, what's verified, what's left. Don't continue from a state you can't describe back.

### Tests

- Tests must encode **why** behavior matters, not just what it does.
- A test that can't fail when business logic changes is wrong.

### Hard Stops

Stop and flag when:

- State ownership is unclear
- Blast radius is unknown
- Timing or race condition hazards are present
- Security issues are identified
- Complexity debt would be significant

### Memory

- **Memory query:** After receiving a substantive task (anything beyond a greeting or quick factual question), invoke `skill("memory-query")` before taking any action. Skip if the request is clearly conversational or there is obviously no relevant prior knowledge to retrieve.
- **Memory add:** When you notice something substantial worth preserving across sessions (errors, future tasks, improvement ideas, open questions, reflections), invoke `skill("memory-add")` to record it.

### Error handling

- Fail fast with clear, actionable messages
- Never swallow exceptions silently
- Include context (what operation, what input, suggested fix)

## Git Workflow

Use `bash` for Git operations.

- Start with `git status --short` and `git branch --show-current`; never discard existing work.
- If unrelated changes overlap files needed for the task, stop and ask.
- Stay on the current branch for small, low-risk work.
- Use `dagi/<task-name>` for risky, experimental, multi-file, or explicitly isolated work.
- Commit coherent changes with Conventional Commit prefixes.
- Never commit, merge, push, stash, switch branches, or create a branch without user approval.
- At completion, report the branch, changed files, tests, and remaining dirty files.

## Process Flow

1. An entry point starts `AgentLoop` with configuration, tools, session state, and UI callbacks.
2. `AgentLoop` assembles stable instructions plus dynamic context, calls the provider, and dispatches tool requests through `ToolRegistry`.
3. `SessionTracker` and `SessionLog` persist conversation, usage, and subagent
   branch events.
4. Subagents run through `tools/subagent_api.py`; inherited children reuse the captured parent request prefix and finish through `write_handoff`.
5. TUI, PySide, Telegram, and CLI entry points translate the same callbacks and agent state; the Electron/`dagi_gui` frontend is archived.

## Errors Log (recent)

- **2026-08-30**: Typed turn termination left `main_system.md` requiring `<<END_OF_RESPONSE>>`, causing a corrective continuation after every text-only reply → make `write_handoff` the prompt's sole final action and regression-test the contract.
- **2026-08-30**: Random-expression migration left stale VAD tests,
  archived `dagi_gui` tests in the active suite, and subagent reads of removed
  `affect_*` fields → archive unsupported tests, migrate active coverage, and
  flatten `expression_interval` only.
- **2026-08-29**: Toasts fail in restricted sandboxes despite working on host → verify outside sandbox.
- **2026-08-29**: Malformed tool-argument JSON orphaned the assistant `tool_calls` message, making the next provider request fail with HTTP 400 → convert `JSONDecodeError` into a normally-bookkept tool error result.
- **2026-08-26**: RAM-watchdog `tests/conftest.py` errors every long test at setup when ambient machine RAM ≥70% (hardcoded warn threshold) → gate runs need `--noconftest`.
- **2026-08-26**: The 08-23 `_pending_ask` fix only covered done/paused, and the TUI never got it → both UIs now ignore a stale sink at submit time (`_ask_is_live`) and retire it in `_agent_work`'s `finally`.
- **2026-08-26**: DeepSeek cache hits plateaued because the ephemeral Session Context board breaks the growing request prefix → board removed entirely: `dynamic_context.py` deleted, `PLAN_WRITE` event removed, `_board`/`_refresh_dynamic_context`/`_build_dynamic_context` stripped from `AgentLoop` (2026-08-27).
- **2026-08-25**: PySide `/clear` retained old token totals → reset `AgentBridge` stats with the session.
- **2026-08-24**: PySide `/wd` and `/model` updated handler-only state → propagate config changes to `DagiWindow`.
- **2026-08-24**: `pytestqt` cannot load `PySide6.QtCore` in the `dagi` environment → run Qt tests directly with Python.

## Notes & Terms

- **Sentinel display sanitization**: agent tool-output views escape loop sentinels (`<<` → `< <`) before showing them; byte-check source before any sentinel-related edit — displayed strings lie.
- **agent/_\* loop modules**: `loop.py` delegates to internal modules (`_loop_config`, `_loop_helpers`, `_system_prompt`, `_plan_mode`, `_model_switch`, `_streaming`, `_compaction`, `_tool_dispatch`) re-exported via `agent.loop`; white-box test patches must target the owning module (e.g. `agent._compaction.run_subagent`).
- **Prompt-cache boundary**: the entire prior provider input must prefix the next request; ignoring a trailing dynamic board is not cache-safe.
- **Expression media**: expression rotation uses `RandomEmoteLibrary` and `ExpressionController`; VAD vectors are no longer part of the display path.
- **Termination**: main and child turns end through `write_handoff`; bare assistant text triggers the corrective continuation prompt.
- **Tool filtering**: `config.yaml` removes tools outside `tools:` except mandatory `write_handoff`.
- **Subagent API**: import `tools/subagent_api.py`, never private `_subagent_runner.py`.
- **Windows / conda**: use `conda run -n dagi python`; hooks use `envs/dagi/python.exe` because `conda run` drops stdin.
- **PySide6 imports**: add the package directory with `os.add_dll_directory` before importing PySide6.
- **Qt threading**: background work reaches widgets only through queued signals or `QMetaObject.invokeMethod`.
