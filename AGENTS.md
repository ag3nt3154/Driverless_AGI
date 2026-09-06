# AGENTS.md

> Last updated: 2026-09-06 | [README](README.md) | [Wiki](wiki/index.md) | [Code review](wiki/notes/broad-review-2026-09-06.md)

---

## Overview

Driverless AGI (dagi) is a Python agentic coding assistant with tool use, subagent delegation,
session persistence, and multi-UI support (TUI, PySide desktop, Telegram). Architecture,
workflows, errors, and notes live in [wiki/](wiki/index.md).

## Rules

- Use `DEFAULT_PYTHON_ENV` (`dagi`) for all Python scripts and package installs.
- Install from the repo root: `python -m pip install -r requirements-core.txt` (core);
  add `-r requirements-gui.txt`, `-r requirements-tui.txt`, or `-r requirements-tools.txt` as needed.
- Always update `AGENTS.md` and `wiki/` after completing a task.
- Architecture, workflows, errors, and project notes belong in the wiki, not AGENTS.md.

## Behavioral Guidelines

> Stable protocol/standards content — preserve verbatim across routine `update-project-context`
> runs; only edit when the user gives an explicit standing behavioral instruction.

### Coding standards

- Functions: ≤ 100 lines | Cyclomatic complexity: ≤ 8 | Positional parameters: ≤ 5
- Line length: 100 characters | Files: ≤ 500 lines

### Calibrate to Ambiguity

- **High ambiguity**: ask clarifying questions before acting
- **Medium ambiguity**: ask targeted questions on gaps, then proceed
- **Low ambiguity**: verify quickly and proceed; **Trivial changes**: trust user intent

### Before Acting

- **State assumptions.** Don't smuggle them.
- **Read before write.** Read exports, immediate caller, obvious shared utilities first.
- **Project consequences.** Assess plausible downside and reversibility before risky changes.

### During Execution

- **Simplicity first.** Minimum code that solves the problem. Nothing speculative.
- **Surgical scope.** Touch only what the task requires. Match conventions over taste.
- NEVER create files unless absolutely necessary. NEVER commit secrets or .env files.

### Verify Invariants Before Shipping

- [ ] State ownership and consistency clear?
- [ ] Feedback / observability in place?
- [ ] Blast radius understood?
- [ ] Timing and ordering safe?
- [ ] Follows existing patterns (or intentionally breaks them)?
- [ ] Security / obvious risks addressed?

### After Acting

- **Ground claims.** Mark unsupported numbers or remove them.
- **Fail loud.** "Done" is wrong if anything was skipped silently.
- **Checkpoint.** Name what was done, what's verified, what's left.

### Tests

- Tests must encode **why** behavior matters, not just what it does.
- A test that can't fail when business logic changes is wrong.

### Hard Stops

Stop and flag when: state ownership unclear, blast radius unknown, timing/race hazards,
security issues, or complexity debt would be significant.

### Error Handling

- Fail fast with clear, actionable messages. Never swallow exceptions silently.

## Git Workflow

- Start with `git status --short` and `git branch --show-current`; never discard existing work.
- Stay on current branch for low-risk work; use `dagi/<task-name>` for risky/multi-file work.
- Commit coherent changes with Conventional Commit prefixes.
- Never commit, merge, push, stash, switch branches, or create a branch without user approval.

## Process Flow

1. Entry point starts `AgentLoop` with config, tools, session state, and UI callbacks.
2. `AgentLoop` assembles system prompt, calls provider, dispatches tools via `ToolRegistry`.
3. `SessionTracker`/`SessionLog` persist conversation, usage, and subagent branch events.
4. Subagents run via `tools/subagent_api.py`; inherited children reuse parent prefix; end via `write_handoff`.
5. TUI, PySide, Telegram, CLI share the same callback/agent-state interface.

## Architecture

- **AgentLoop** (`agent/loop.py`) delegates to `_loop_config/_helpers/_system_prompt/_streaming/_compaction/_tool_dispatch/_reload/_model_switch`.
- **ToolRegistry** dispatches `ToolResult(output, side_effect)` instead of string sentinels.
- **Subagents**: typed presets in `.dagi/subagents/*/`; public API `tools/subagent_api.py`.
- **Wiki**: `wiki/` Git-tracked Markdown; delegated via `wiki_query`/`wiki_add` tools.
- **Personal memory**: `G:/My Drive/black_grimoire/dagi-memory`; explicit user requests only.

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop; re-exports internal `_*` modules |
| `agent/cli_utils.py` | `_cmd_init` — project wiki scaffold creation |
| `agent/_init_templates.py` | `build_init_files` — wiki + AGENTS scaffold content |
| `tools/_wiki_tools.py` | Wiki delegation logic (scope guard, protocol inject, handoff validate) |
| `tools/subagent_api.py` | Public subagent API; `SubagentResult` dataclass |
| `tools/_handoff_format.py` | `format_error_result`, `MISSING_HANDOFF_NOTICE` |
| `.dagi/subagents/wiki-{query,add}/` | Wiki subagent presets (file-tool-only, no nesting) |
| `.dagi/skills/deliver/SKILL.md` | Primary delivery lifecycle orchestration |
| `.dagi/skills/plan/SKILL.md` | Planning lifecycle (spec, explore, approve, wiki-add) |
| `.dagi/prompts/main/main_system.md` | Main agent system prompt template |
| `.dagi/config.yaml` | Tool allowlist, model config, memory root, affect config |
| `tests/test_wiki_tools.py` | Wiki delegation contract tests (33 tests) |
| `tests/test_project_init.py` | Init preservation and scaffold tests |
| `wiki/` | Project knowledge wiki (architecture, workflows, errors, notes) |

## Errors Log

- **2026-09-05**: pytest-qt entry point name is `pytest-qt` not `qt`; `-p no:pytest-qt` required → documented in wiki/errors/index.md and wiki/workflows.md.
- **2026-09-05**: 4 PySide GUI bugs (sidebar bg, emote timing, thinking duplication, status lines) → all fixed; details in wiki/errors/index.md.
- **2026-09-05**: 7 deliver-workflow integration failures (stale tool names, dynamic plan read, etc.) → all fixed; details in wiki/errors/index.md.
- **2026-09-05**: Plan mode removed → `/plan` skill + `create_plan` tool; `AgentConfig` plan fields removed.
- **2026-08-30**: Typed turn termination left `main_system.md` requiring `<<END_OF_RESPONSE>>` → `write_handoff` sole final action.
- **2026-08-29**: Toasts fail in restricted sandboxes → verify outside sandbox.
- **2026-08-26**: RAM-watchdog errors every long test (≥70% RAM) → `--noconftest -p no:pytest-qt` for isolated runs.
- **2026-08-26**: stale `ask_user` sink swallowed next message in TUI and PySide → fixed with `_ask_is_live` + `finally` retirement.
- **2026-08-26**: DeepSeek cache plateaued due to ephemeral Session Context board → board deleted entirely.
- **2026-08-23**: `pyside_gui/app.py` file cap stale (547+ lines vs ≤500 assertion) → open; raise cap or split module.

## Notes & Terms

- **pytest-qt entry point**: name is `pytest-qt` (not `qt`); use `-p "no:pytest-qt"` to disable.
- **Sentinel display sanitization**: escape loop sentinels (`<<` → `< <`) before showing; byte-check source before editing.
- **agent/_* loop modules**: white-box test patches must target owning module (e.g. `agent._compaction`).
- **Prompt-cache boundary**: entire prior provider input must prefix next request; no dynamic board.
- **Termination**: main and child turns end through `write_handoff`; bare assistant text triggers corrective continuation.
- **Tool filtering**: `config.yaml` `tools:` restricts main agent; mandatory `write_handoff` always injected.
- **Subagent API**: import `tools/subagent_api.py`; never private `_subagent_runner.py`.
- **Windows / conda**: `conda run -n dagi python`; hooks use `envs/dagi/python.exe` (conda run drops stdin).
- **Plan UI location**: active-plan panel in PySide left sidebar, 4th rail view (`PlanView`); `LeftSidebar.update_plan()`.
- **Wiki subagents**: tool allowlists are `[read,grep,find]` (query) or `+[write,edit]` (add); no shell/delegation.

## Wiki Use

Only the main agent delegates wiki operations. Personal `memory-*` for explicit user requests only.

- **Before each overall substantive task**: call `wiki_query`. Empty wiki permits investigation;
  missing wiki requires `/init`. Chained skills share the lookup.
- **After plan approval**: select approved decisions/user choices → `wiki_add`. Retry once;
  failure blocks implementation.
- **After completion and verification**: select actual results/completion → `wiki_add`. Retry once;
  failure leaves workflow incomplete.
- **Discretionary**: query substantial questions; add bugs, fixes, findings. Report optional failures.
- **Workers**: receive wiki findings, return `Wiki requests` in handoffs. Never delegate themselves.
- **`wiki-refresh`**: explicit, main-agent-only; inspects project evidence and asks user when needed.
- **`/init`**: code-based scaffold at project root; preserves all existing files; no knowledge population.

---

## User Insights

### User Tendencies

- Prefers adversarial design review (/grill) before implementation on major features.
- Runs dagi on Windows with conda; comfortable with direct env paths when conda run has limitations.
- Approves plans before implementation; expects wiki-add for approvals and completions.
- Tight on test discipline: only tests that can actually fail on broken logic are acceptable.
- Keeps AGENTS.md compact intentionally; durable knowledge belongs in the wiki.

### Project Shortcomings

- Provider call has no timeout — worker can block silently for up to ~30 min (open issue).
- `pyside_gui/app.py` file cap assertion is stale (547+ lines vs ≤500 cap test).
- PySide6 QtCore DLL fails to load without full conda env activation (Windows DLL chain issue).
- No parallel subagent dispatch support despite earlier plan for `spawn_parallel_subagents`.
- Wiki is new (2026-09-05); no project-specific knowledge accumulated yet beyond scaffold and contract.

### Potential Areas of Exploration

- Config-backed `request_timeout` for the OpenAI client to surface stalls as retryable errors.
- Split `pyside_gui/app.py` to bring it under the 500-line cap.
- Parallel subagent dispatch (`spawn_parallel_subagents` / `wait_subagents` tools).
- Automated wiki health checks (stale dates, broken links) triggered on commit or session start.
- Provider cost/usage dashboard surfaced in the sidebar.
