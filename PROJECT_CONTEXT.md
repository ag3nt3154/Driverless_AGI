# PROJECT_CONTEXT.md

> Last updated: 2026-07-13 | [README](README.md) | [TODO](TODO.md)
> Session 2026-07-13 (bugfix): `explore_files`/memory-query/all `run_subagent()`-spawned subagents were failing with `ModuleNotFoundError: No module named 'agent'`. Root cause: the 2026-07-12 "deprecate cli" commit (`d6f7f25`) moved `cli.py` to `archives/cli.py` but didn't account for Python setting `sys.path[0]` to the script's own directory (`archives/`, not the project root) when spawned as a direct subprocess. Fixed by passing `cwd=str(_DAGI_ROOT)` and `env["PYTHONPATH"]` (prefixed with `_DAGI_ROOT`) in `tools/_subagent_runner.py::run_subagent()`'s `subprocess.Popen()` call.
> Session 2026-07-12 (compose mode hardening, 5 fixes): Hardened `action_toggle_compose` in `tui/app.py` with 5 code-quality fixes applied in a single commit (`a791067`). (1) **Guard**: method returns early if `_worker.is_alive()` and `_pending_ask is None` — compose cannot be entered while agent is running. (2) **Spinner hide**: `#running-indicator` Static's `display` state is saved to `_bar_was_visible` on enter; restored (never blindly shown) on exit — avoids revealing the spinner during compose and then hiding it spuriously on collapse. (3) **Class constant**: `_PROMPT_HEIGHT_COLLAPSED: int = 8` added as class attribute before `CSS`; replaces the hardcoded literal `8` in `action_toggle_compose`. (4) **Blank-enter guard**: `on_prompt_input_submitted` now strips and checks for empty value *before* calling `action_toggle_compose` — a bare Enter in compose mode no longer collapses compose if the buffer is empty. (5) **Dynamic border title**: `inp.border_title` set to `"COMPOSE — Enter to submit · ctrl+o to collapse"` in compose mode, restored to `"ctrl+n = newline · ctrl+o = compose"` on collapse. All 260 tests pass.
> Session 2026-07-12 (compose mode, ctrl+o): Added `ctrl+o` compose mode to `DagiApp` (`tui/app.py`). `_input_expanded: bool = False` state added to `__init__`. `BINDINGS` gains `("ctrl+o", "toggle_compose", "Compose")`. `action_toggle_compose()` hides `ConversationPane` via `conv.display = False` and expands `PromptInput` to `"1fr"` height; restores on second press. `on_prompt_input_submitted` auto-collapses compose mode before processing any submit path. All 260 tests pass. Commit: `f4ac818`.
> Session 2026-07-12 (code-quality, PromptInput tests): Fixed 3 quality issues in `tests/test_prompt_input_multiline.py` and `tui/prompt_input.py`. (1) `test_enter_with_text_submits_and_clears` now drives keyboard input via `for char in "hello": await pilot.press(char)` instead of `widget.load_text("hello")` — `pilot.type()` does not exist in Textual 8.2.7, so per-character `pilot.press()` is the correct simulation approach. (2) `PromptInput` docstring updated to list all three newline bindings. (3) New `test_enter_on_whitespace_only_does_not_submit` added to cover the `if text.strip():` guard — pressing `ctrl+n` then `enter` inserts a bare `\n` which must not submit. All 6 tests pass. Commit: `f252884`.
> Session 2026-07-14 (plan-work-review-resilience, all 9 tasks complete): Gave worker/review subagents a fast-fail escalation channel and gave the main agent a live per-iteration plan status board. **Escalation:** new `tools/escalate_issue.py::EscalateIssueTool` writes a sidecar `<handoff-stem>_escalation.md` file next to the handoff report; `tools/_subagent_runner.py::_poll_until` checks for this sidecar on every 2s poll tick (before the exit-poll check), and on detection terminates the subprocess (`terminate()` → `wait(timeout=5)` → `kill()` fallback on `TimeoutExpired`), cleans up `_active`/task-file state, and returns `{"status": "escalated", "escalation": <content>}`; `tools/spawn_subagent.py::SpawnSubagentTool.run()` surfaces this as `"[{type} escalated]\n\n{escalation}"`. `escalate_issue` is wired into the worker/review subagent tool registries (`agent/tools.py::_tools_from_list`/`build_subagent_registry`, both gained `handoff_path: Path | None = None`) and both `.dagi/subagents/{worker,review}/subagent_config.yaml`; deliberately absent from the `"custom"` dynamic-subagent branch. Both subagent prompts (`.dagi/subagents/{worker,review}/prompt.md`) instruct escalation on blocking ambiguity, ending the turn immediately without a handoff/review report. `.dagi/skills/plan-work-review/SKILL.md` gained an `**If ESCALATED:**` branch in Phase 2 Step 4 (main agent resolves or asks the user, re-spawns the same subagent type via `custom_instructions`, free of charge — no retry attempt consumed) and the retry budget language changed from "3 attempts" to "2 attempts" (1 initial + 1 retry). **Live plan status board:** see the 2026-07-14 Task 6 entry below for the rendering/caching design; Task 7 wired `_refresh_active_plan_tail()` into `AgentLoop.run()`'s main loop (called right after `iteration += 1`, before `on_iteration`) — it is now live. Full suite: 254 passed. Design: `docs/superpowers/specs/2026-07-12-plan-work-review-resilience-design.md`; plan: `docs/superpowers/plans/2026-07-12-plan-work-review-resilience.md`. Commits: `62cd8c8`, `f37c475`, `cc59b6e`, `2a46a8d`, `2b11919`, `d93050d`, `6221ac4`, `41ae140`, `483d751`, `bf25b84`, `0969fc8`, `c40497f`.
> Session 2026-07-14 (Task 6, plan-status-board): `agent/loop.py`'s `_assemble_system_string` now sets `self._system_prefix` (everything before the "Active Plan" pointer) and returns `system_prefix + self._build_active_plan_tail()`. New `_build_active_plan_tail()` renders the existing "## Active Plan" pointer text plus a fresh "## Plan Status" numbered board (built by `_render_plan_status_section()` from `tools/_plan_parser.parse_subtask_statuses()`), returning `""` when no plan is active or `plan_mode` is on. New `_refresh_active_plan_tail()` re-splices `self._messages[0]` from the cached `_system_prefix` + a freshly rendered tail — wired into `run()`'s loop as of Task 7 (2026-07-14). Purpose: keep `cache_prompt`'s large static prefix byte-for-byte stable across iterations while still surfacing live subtask status to the agent. 8 new tests in `tests/test_plan_status_board.py`; full suite 251 passed. Commit `483d751`.
> Session 2026-07-14: Fixed `/wd` TUI command — sidebar now refreshes model name, context window, and reserve tokens when switching project directories. Added `model_id` field to `AgentConfig` so `resolve_model_config` communicates the resolved catalog ID back to callers. `_cmd_wd` in `tui/commands.py` now always refreshes sidebar state after a project switch, and detects when the new project's `default_model` differs from the current model (updating `_model_id`/`_model_name`).
> Session 2026-07-12: Completed all 6 tasks of the DAGI git-workflow plan. `tools/git.py` rewritten to 8 tools (`git_status`, `git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`, `git_commit`, `git_reset`); `git_rollback` removed entirely; `git_commit` requires explicit `git_add` staging first (no implicit `add -A`); `git_add`/`git_commit`/`git_reset` guarded by `_dagi_branch_guard()` to `dagi/*` branches only. `agent/_git_branch.py` auto-creates/checks out `dagi/<slug>_<plan_id>` on `enter_plan_mode` (Task 4, required `task_summary` param). `.dagi/skills/plan-work-review/SKILL.md` updated for per-subtask commits and a merge reminder — DAGI never merges/switches/deletes the task branch itself, the user does that by hand. Accepted limitation: `BashTool` is unsandboxed and can run raw `git` commands, bypassing the `dagi/*` guard entirely — the guard only constrains the dedicated git tools. Spec: `docs/superpowers/specs/2026-07-12-dagi-git-workflow-design.md`; plan: `docs/superpowers/plans/2026-07-12-dagi-git-workflow.md`.
> Session 2026-07-12 (Task 4): `enter_plan_mode` now requires `task_summary`, auto-creates a `dagi/<slug>_<plan_id>` git branch via `agent/_git_branch.create_task_branch()`, and seeds the plan title. Skips silently (no error) outside a git repo. 4 new tests in `tests/test_plan_mode_branch.py`; full suite 228 passed.
> Session 2026-07-11 (review): 6 new findings added to TODO.md (image-read crash, plan_mode_exited regression, grep dotted-dir bug, falsy-zero config, AskUserTool double-timeout, explore_files schema waste); 1 item escalated (Telegram subagent relay, 14d); 0 completed entries archived. Most notable: Fable adversarial code review surfaced 2 crash-on-primary-path bugs.
> Session 2026-07-09 (review): 1 new finding (wiki index system messages accumulate across `run()` calls — token waste); 0 items escalated; 2 completed entries archived (pipe-based subagent, transient API retry). Age counters updated across ~28 items. GNHF dormant 74 days. 209 session logs (last: 2026-07-05). 8 temp files in `.dagi/temp/`. No new CVEs for openai, pyyaml, textual, python-telegram-bot, ddgs.
> Session 2026-07-07 (review): 0 new findings added to TODO.md; 0 items escalated; 0 completed entries archived. All existing items verified still open. Age counters updated across ~28 items. GNHF dormant 72 days. 209 session logs (last: 2026-07-05). 8 temp files in `.dagi/temp/`. No new CVEs for openai, pyyaml, textual, python-telegram-bot, ddgs. LangChain CVE-2026-34070 already noted in TODO (dead dep).
> Session 2026-07-05 (review): 1 new finding (CRLF `write_text()` inconsistency — 10 call sites lack `newline="\n"`); 3 items moved to Completed (python-dotenv CVE, tg/bot.py finish, tg/callbacks.py ask_user — all committed in e39e146); cli.py corrected to 1355 lines (not 1173). GNHF dormant 70 days. 209 session logs. No new CVEs for dependencies.
> Session 2026-07-05 (bugfix): Windows line-ending triple-bug diagnosed and fixed — `EditTool` now normalises `oldText`/`newText` CRLF→LF before matching; `WriteTool`/`EditTool` now write with `newline="\n"` to prevent Windows text-mode CRLF introduction and double-CR corruption. All 184 tests pass.
> Earlier sessions compressed 2026-07-11: 4 sessions from 2026-07-04 to 2026-07-05 — insert-text-block skill (created + hardened), tg/bot.py UnboundLocalError finding, asyncio.get_event_loop() deprecation, 3 uncommitted fixes confirmed. See git log.
> Earlier sessions compressed 2026-07-05: 4 sessions from 2026-06-30 to 2026-07-03 — review-session rework, cli.py line count, python-dotenv CVE, filter_tool_output temp leak, ChatSession.lock dead code, BM25 stale ref, httpx governance risk. See git log.
> Earlier sessions compressed 2026-07-04: 3 sessions from 2026-06-28 to 2026-06-29 — scheduler race, Telegram subagent relay missing, END_OF_RESPONSE relaxation, continue prompt visibility. See git log.
> Earlier sessions compressed 2026-07-03: 4 sessions (2026-06-28 7–8) — tool output filtering, Telegram bot, TUI sidebar overhaul, DAGI_ROOT straggler. See git log.
> Earlier sessions compressed 2026-06-28: 13 sessions (2026-06-26 7 – 2026-06-28 4) — task scheduler, memory-wiki subagents, unified `_assemble_system_string`, plan-work-review, explore_files citation-first.
> Earlier sessions compressed 2026-06-27: 22 sessions (2026-06-17 – 2026-06-26 6) — see git log.


---

## Project Description

Driverless AGI (dagi) is a self-hosted, OpenAI-compatible agentic coding assistant built entirely in Python. It takes a task from the user, runs a Plan→Act→Observe loop calling tools (read, write, edit, bash, grep, web search, etc.) until the task is complete, and surfaces results via a Rich interactive CLI or single-shot `main.py` entry point. See [README](README.md) for setup and usage.

## Objective / Problem Statement

Build a minimal but production-capable autonomous coding agent that can: work on arbitrary codebases, survive long tasks via context compaction, accumulate persistent knowledge via a wiki memory system, spawn specialist subagents for research/planning, and self-improve over time via the GNHF feedback loop.

Non-goals: cloud hosting, multi-user auth, UI beyond CLI/Rich.

## Environment

- **Language:** Python 3.11+ (conda env `dagi` currently runs 3.14 pre-release — see Notable Points)
- **Runtime:** `conda` environment named `dagi`
- **Install:** `conda run -n dagi pip install -e .`
- **Run (REPL):** `conda run -n dagi python cli.py`
- **Run (TUI):** `conda run -n dagi python tui.py`
- **Config:** `config.yaml` (gitignored) — model catalog, base_url, api_key / api_key_env, max_iterations, null_response_retries, max_continuations, cache_prompt, tools

## Directory Layout

```
Driverless_AGI/
├── agent/              # Core engine — loop, registry, config, session tracking
├── tools/              # Built-in tools (compact, spawn_subagent, extend_timeout, emote, etc.)
├── scripts/            # Utility scripts (dagi_freeze, build_api_tools, etc.)
├── tui/                # Textual TUI package (app, commands, sidebar, callbacks, etc.)
├── tg/                 # Telegram bot package (bot, callbacks, session, utils)
├── benchmarks/         # Benchmark adapters
│   ├── terminal_bench/ # Terminal-bench 2 adapter (TmuxBashTool, DagiAgent)
│   └── harbor/         # Harbor Framework adapter (HarborBashTool, DagiAgent)
├── scheduler/          # Task scheduler package (models, tracker, runner)
├── tests/              # Unit tests
├── .dagi/
│   ├── agents.md       # Behavioral guidelines loaded at every session start
│   ├── prompts/
│   │   ├── main/       # main_system.md — primary agent system prompt
│   │   ├── subagents/  # Per-type prompts (explore_files, web_research, worker, review)
│   │   └── compact/    # compact_system + compact_user prompts
│   ├── skills/         # Skills (memory-*, grill-me, update-project-context, etc.)
│   ├── subagents/      # Per-type subagent_config.yaml (tools list + model_tier)
│   ├── handoffs/       # Subagent handoff documents (generated at runtime)
│   ├── plans/          # Generated plan documents
│   ├── scheduler/      # schedule.yaml (task defs) + runs.jsonl (execution log) + output/
│   ├── logs/           # Session JSONL logs
│   └── self-review/    # Session review reports
├── .dagi/prompts/soul.md # Agent persona / identity
├── tui.py              # TUI entry point (thin launcher)
├── telegram_bot.py     # Telegram bot entry point (thin launcher)
├── cli.py              # Rich REPL entry point
├── config.yaml         # Runtime config (gitignored)
├── benchmarks/config_benchmark.yaml # Benchmark-specific config
├── docs/
│   └── terminal-bench.md # Guide for running Terminal-bench 2
└── README.md           # Full documentation
```

## Architecture

```
tui.py / cli.py / main.py / telegram_bot.py ← entry points (TUI | REPL | one-shot | Telegram)
    │
    tui.py → tui/ package:
        tui/app.py           ← DagiApp (lifecycle, threading)
        tui/commands.py      ← SlashCommandsMixin (_handle_slash + _cmd_*)
        tui/callbacks.py     ← build_callbacks() free function
        tui/conversation.py  ← ConversationPane(RichLog)
        tui/sidebar.py       ← Sidebar(Widget) — top header, 3-column layout
        tui/prompt_input.py  ← PromptInput(TextArea)
        tui/utils.py         ← helpers + _Stats
    │
    └── AgentLoop (agent/loop.py)
            │
            ├── ToolRegistry (agent/registry.py)  ← dispatches tool calls
            ├── SessionTracker (agent/session.py)  ← logs all turns to JSONL
            ├── CompactTool (tools/compact.py)     ← Pi-style context compaction
            ├── SkillLoader (.dagi/skills/)         ← skill guidance docs
            └── AgentCallbacks                     ← rendering hooks (TUI/CLI)
```

**Config:** `config.yaml` → `agent/config_loader.py` → `AgentConfig` dataclass  
**Memory:** `dagi-memory/{raw,wiki,sources}/` + wiki index auto-injection at session start; retrieval via `spawn_memory_query_subagent` (grep + traversal); writing via `spawn_memory_add_subagent`. Wiki is structured as `wiki/projects/{name}/` and `wiki/knowledge/{topic}/`, with `.index.md` files at each level.  
**Subagents:** Pipe-based subprocess spawning (`tools/_subagent_runner.py`). Each subagent type has a `.dagi/subagents/<type>/subagent_config.yaml` (explicit `tools:` list + `model_tier`). Handoff path generated by `SpawnSubagentTool`, written by subagent on exit. Subagent stdout (newline-delimited JSON events) relayed to main TUI `ConversationPane` with `[subagent-type]` label prefix. `run_subagent()` spawns `archives/cli.py` with explicit `cwd=_DAGI_ROOT` and `PYTHONPATH=_DAGI_ROOT` (fixed 2026-07-13 — required because the script lives below the project root, so Python's default `sys.path[0]` for a directly-invoked script doesn't include root-level packages).  
**TUI rendering bridge:** `AgentCallbacks` fire on agent thread → `App.call_from_thread()` → Textual main loop → widget `refresh()`

## Process Flow

1. User calls `cli.py` (REPL) or `main.py` (one-shot) with a task string
2. `resolve_model_config()` reads `config.yaml`, resolves API key, builds `AgentConfig`
3. `AgentLoop.__init__()` loads skills, builds `ToolRegistry`, constructs system prompt
4. `AgentLoop.run(task)` enters `while True` loop:
   - Checks `_pause_event` at top of each iteration — blocks if user pressed ESC (TUI only)
   - Calls the LLM with current `_messages`
   - If tool calls present → dispatch each tool, append results, loop again
   - If no tool calls → check response for termination flags:
     - `<<END_OF_RESPONSE>>` → strip flag, surface response, exit loop (wait for next user turn)
     - `<<TASK_END>>` → strip flag, surface response, call `on_done`, return (legacy alias)
     - Neither → inject continue prompt, loop again (up to `max_continuations`)
5. Context compaction triggers mid-loop if token count exceeds threshold
6. Session ends; `SessionTracker.finish()` writes summary to `.dagi/logs/`

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, `AgentConfig`, `AgentCallbacks`, termination flags; `_assemble_system_string(dagi_root)` is the single system-prompt assembly entry point (sets `self._system_prefix`, returns prefix + `_build_active_plan_tail()`); `_build_active_plan_tail()`/`_render_plan_status_section()`/`_refresh_active_plan_tail()` render the live "## Plan Status" board without touching the cached prefix; `_build_wiki_index_context()` injects wiki index as system message before first user turn |
| `agent/config_loader.py` | Reads `config.yaml`; resolves `api_key`; `resolve_model_config(project_path=...)` merges `{project_path}/.dagi/config.yaml` over root |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; `build_subagent_registry()` accepts `memory_root: Path | None` |
| `agent/prompts.py` | `load_main_system_prompt(dagi_root, project_path)` and `load_soul(dagi_root, project_path)` — project-local first, dagi-root fallback |
| `agent/__init__.py` | `DAGI_ROOT = Path(__file__).parent.parent` — the single canonical root definition |
| `.dagi/subagents/memory-query/` | Wiki retrieval subagent: grep + index traversal; citations handoff; restricted to memory_root |
| `.dagi/subagents/memory-add/` | Wiki write subagent: Step 0.5 TODO detection → `wiki/user-todo.md`; 5-field frontmatter nodes; updates `.index.md` |
| `scheduler/models.py` | `ScheduledTask` dataclass, `parse_interval()`, `load_schedule()` / `save_schedule()` |
| `scheduler/tracker.py` | `RunTracker` — loads `runs.jsonl` at init, `is_due(task)`, `record_run(...)` |
| `scheduler/runner.py` | Entry point (`python -m scheduler.runner`); runs due tasks via `AgentLoop` with autonomous config |
| `tools/schedule_tools.py` | `ScheduleTaskTool`, `ListScheduledTasksTool`, `RemoveScheduledTaskTool` — interactive sessions only |
| `tools/output_filter.py` | `filter_tool_output(result, reserve_tokens, temp_dir)` — truncates large tool results before LLM context entry |
| `tools/_subagent_runner.py` | Pipe-based subagent runner; `run_subagent()` + `resume_subagent()`; `_active` dict keyed by PID |
| `tools/extend_timeout.py` | `ExtendSubagentTimeoutTool` — extends deadline on in-flight subagent |
| `tools/spawn_subagent.py` | `SpawnSubagentTool` — generates handoff path, calls `run_subagent()` |
| `tools/compact.py` | Pi-style context compaction |
| `tools/ask_user.py` | Blocking user-input tool with optional timeout |
| `tools/escalate_issue.py` | `EscalateIssueTool` — writes `<handoff-stem>_escalation.md` sidecar; detected by `_subagent_runner.py`'s poll loop, surfaced by `spawn_subagent.py` as `[{type} escalated]` |
| `tg/bot.py` | `TelegramBot` — handlers, `_run_agent_task()` async/sync bridge via `run_in_executor` |
| `tg/callbacks.py` | `build_callbacks(bot, chat_id, session, event_loop)` — bridges sync callbacks to async Telegram sends |
| `tg/session.py` | `ChatSession` (per-chat state) + `SessionManager` (dict[chat_id, ChatSession]) |
| `tui/app.py` | `DagiApp(SlashCommandsMixin, App[None])` — lifecycle, dispatch, callbacks wiring (~180 lines) |
| `tui/commands.py` | `SlashCommandsMixin` — all `_cmd_*` methods mixed into `DagiApp` via MRO |
| `tui/sidebar.py` | `Sidebar(Widget)` — fixed top header; 3-column Rich Table: left=emote+paths, center=tokens, right=plan |
| `tui/callbacks.py` | `build_callbacks(app, loop_ref) → AgentCallbacks` free function; `TYPE_CHECKING` guard for circular import |
| `cli.py` | Rich REPL with threaded/sync modes, plan mode, slash commands |
| `benchmarks/config_benchmark.yaml` | Benchmark config: `bash_backend: subprocess` (no-op), raised `max_continuations`, Harbor preamble, `harbor_bash` tools list |
| `tests/conftest.py` | RAM watchdog pytest plugin — auto-use fixture; fails at 70%, hard-kills at 90% |
| `agent/_git_branch.py` | `create_task_branch(cwd, task_summary, plan_id) -> str \| None` — slugifies task_summary, `git checkout -b dagi/<slug>_<plan_id>`; returns `None` (not an error) if `cwd` isn't a git repo; raises `RuntimeError` on real git failures (e.g. branch already exists) |
| `tools/git.py` | 8 tool classes: `GitStatusTool`, `GitDiffTool`, `GitLogTool`, `GitBranchTool`, `GitCheckoutTool`, `GitAddTool`, `GitCommitTool`, `GitResetTool`. `_dagi_branch_guard(cwd)` restricts `GitAddTool`/`GitCommitTool`/`GitResetTool` to `dagi/*` branches; status/diff/log/branch/checkout are unrestricted. `GitCommitTool` requires prior explicit `git_add` — no implicit `add -A`. |
| `.dagi/skills/plan-work-review/SKILL.md` | Per-subtask commit workflow (git_add + git_commit after each subtask review passes) and explicit merge reminder — DAGI never merges, switches off, or deletes the `dagi/*` task branch; that step is left to the user |
| `tools/plan_mode.py` | `EnterPlanModeTool`/`ExitPlanModeTool` — LLM-facing schemas returning sentinel strings; actual work happens in `agent/loop.py`'s `_handle_enter_plan_mode`/`_handle_exit_plan_mode` |
| `agent/session.py` | Append-only JSONL session logging with token/cost tracking |
| `tools/_plan_parser.py` | `extract_global_sections`, `extract_subtask`, `parse_subtask_statuses` |
| `run_scheduler.bat` | Windows trigger; wire into Task Scheduler |
| `.dagi/skills/insert-text-block/SKILL.md` | Document editing skill: resolves `[...]` markers (text blocks or editorial comments) with plan-first confirmation before implementation |
| `.dagi/skills/review-session/SKILL.md` | Self-review skill: free-text session selection → single running report `.dagi/self-review/review_{run-datetime}.md`, dedup via tag-accumulation, once-at-the-end cross-session synthesis (plan mode) |
| `.dagi/skills/review-session/parse_jsonl_logs.py` | Per-session log simplifier (merges tool_start/end, truncates, `--stats` → `fits_in_context`) |
| `.dagi/skills/review-session/chunk_session.py` | `--list` (session discovery/metadata), `--info`, windowed chunked reading for oversized sessions |

## Encountered Errors & Solutions

- **2026-05-29 Error**: `api_key` in config.yaml silently ignored; fell back to OpenAI env vars.
  **Cause**: `_build_config_from_entry()` only read `api_key_env`, never a direct `api_key` literal.
  **Fix**: Added direct-key check first; falls back to `api_key_env` only when empty.

- **2026-05-29 Error**: DAGI didn't return `<<WAIT_FOR_USER_RESPONSE>>` on greetings/casual replies, triggering auto-continue.
  **Cause**: Flag listed only for "clarifying questions / intermediate results" — model excluded greetings.
  **Fix**: Rewrote flag section to make the rule unconditional — every no-tool-call response must carry a flag.

- **2026-05-29 Error**: Questions/intermediate results triggered auto-continue injection.
  **Cause**: Only two exit conditions — `<<TASK_END>>` or inject "continue".
  **Fix**: Added `<<WAIT_FOR_USER_RESPONSE>>` as third flag, exits cleanly while preserving history.

- **2026-05-30 Note**: `conda run -n dagi python -c "..."` with multi-line strings fails on Windows (`NotImplementedError`). Write multi-line scripts to a temp file instead.

- **2026-05-31 Change**: Renamed `<<AWAIT_USER_RESPONSE>>` → `<<END_OF_RESPONSE>>`. Models omitted the old flag on greetings; new name semantically means "I am done with my turn." Rewrote instruction block with examples and bold header.

- **2026-05-31 Bug**: `_continuation_count` never reset between `run()` calls — silently eroded budget.
  **Fix**: Added `self._continuation_count = 0` at top of `run()`.

- **2026-05-31 Bug**: Ghost-response cascade — null API response triggered 10 silent continuations.
  **Cause**: DeepSeek v4 Flash returned HTTP 200 with `content=None`; appended to history causing all subsequent calls to also return null.
  **Fix**: Inner ghost-response retry loop (up to `null_response_retries`, default 3). Ghost = `content=None` AND `prompt_tokens==0`. Discards response, does NOT append to `_messages`.

- **2026-05-31 Bug**: `plan_mode_exited` was dead code — never set `True`. Removed the field and its unreachable check block.

- **2026-05-31 Feature**: ESC pause button. `AgentLoop._pause_event: threading.Event`; checked at top of each loop iteration. `pause()` clears; `inject_and_resume(message)` appends message then sets event.

- **2026-05-31 Refactor**: Skill slash commands now produce `"Invoke the \`skill-name\` skill."` — LLM calls `skill()` itself. Both slash commands and mid-task invocations now unified through `SkillTool`.

- **2026-06-05 Fix**: Compaction summary never written to JSONL session log.
  **Fix**: Added `_on_summary: Callable[[str], None]` callback to `CompactTool`; all 4 `compact_tool.bind()` sites pass `on_summary=self.tracker.record_user`.

- **2026-06-06 Refactor**: Subagent architecture rewritten from IPC+terminal-window to pipe-based subprocess.
  **Deleted**: `agent/ipc.py`, `tools/_terminal_subagent.py`. New `tools/_subagent_runner.py` uses `stdout=PIPE`; daemon thread reads newline-delimited JSON events; `tools/extend_timeout.py` added; each subagent type declares tools explicitly in `subagent_config.yaml`.

- **2026-06-08 Feature**: Transient API error retry with exponential backoff. Catches `APIConnectionError`, `APITimeoutError`, and `APIStatusError` (429, 500, 502, 503). `2^attempt` seconds, capped at 60s; up to `api_error_retries` (default 3). Non-transient errors propagate immediately.

- **2026-06-11 Feature**: Error-pause on exhausted transient retries (TUI). `supports_pause: bool` on `AgentCallbacks`; TUI sets `True`. Exhausted retries pause loop (blocking `_pause_event.wait()`) rather than raising — context preserved. CLI/subagents keep `supports_pause=False`. `_active_loop = loop` moved to before `loop.run()` so context is always preserved.

- **2026-06-12 Error**: `ValueError: Dataset terminal-bench-core@head not found` in Harbor.
  **Fix**: Updated all bat files to `terminal-bench/terminal-bench-2@latest` (OCI package registry, slash-separated format).

- **2026-06-12 Bug**: `/clear` left stale plan subtasks in sidebar.
  **Fix**: Added `self._current_loop_ref = []` reset and `sidebar.update_plan([], "")` call; guard rejects `/clear` while `_worker.is_alive()`.

- **2026-06-13 Batch** (per-project config, benchmarks, bash tools, test infra — ~20 fixes):
  - **Per-project prompts**: `load_main_system_prompt(dagi_root, project_path)` and `load_soul(dagi_root, project_path)` added (`agent/prompts.py`). `AgentConfig.system_prompt` now lazy-loaded (defaults `""`; loaded from disk in `__init__`). `resolve_model_config` accepts `project_path`. Lazy-load guard added to both `_rebuild_for_*` methods. All 5 call sites updated to pass `project_path=` directly. `dagi_root` dead-code parameter in fallback path fixed.
  - **Benchmark infrastructure**: `config_benchmark.yaml` created (moved to `benchmarks/` 2026-06-14). Harbor `DagiAgent.project_path` changed to `tempfile.mkdtemp()` (was wrong Harbor log dir). `system_prompt_preamble` added to `AgentConfig`; injected at all 3 build sites. `run_harbor.bat`: `PYTHONUTF8=1` added (CP1252 UnicodeEncodeError); `harbor_bash` added to tools list (was silently using Windows host bash). `/init` now creates `logs/` directory.
  - **Bash tool architecture**: `BashTool` always registered; injected `bash_tool` additionally registered. `HarborBashTool.name` renamed `"bash"` → `"harbor_bash"`. `TmuxBashTool` promoted to `tools/tmux_bash.py` (first-class). `emote_tool` boolean config flag removed (now controlled by `tools:` list only). `bash_backend` marked as no-op.
  - **Test infra**: `[tool.pytest.ini_options]` with `pythonpath = ["."]` added to `pyproject.toml`. MagicMock+`yaml.safe_load` OOM root cause: `determine_encoding` infinite loop (see Notable Points). `_FakeBashTool` made to subclass `BaseTool`. Stale `docs/terminal-bench.md` integration description updated.

- **2026-06-17 Bug**: `/compact` TUI command froze Textual (sync API call on main event loop thread).
  **Fix**: Moved compact operation to background daemon thread; main thread shows "⏳ Compacting…" and returns. Result posted back via `call_from_thread`.

- **2026-06-17 A1 Bug**: TUI never produced `session_end` JSONL record — token totals and cost silently dropped.
  **Cause**: `_agent_work()` finally block never called `loop.finish()`.
  **Fix**: Added `if loop_ref: loop_ref[0].finish()` in finally block, wrapped in `try/except`.

- **2026-06-17 A2 Bug**: soul.md and agents.md dropped from system prompt after any plan-mode transition.
  **Fix**: Extracted `_build_preamble(dagi_root)` — full preamble stack (preamble + soul + dagi agents.md + project agents.md) called from all 3 build sites.

- **2026-06-18 Bug**: `AttributeError: 'AgentLoop' object has no attribute 'config'` on startup.
  **Cause**: `self.config = config` assigned 25 lines after `_build_preamble()` call.
  **Fix**: Moved `self.config = config` to immediately before `_build_preamble`. Also re-added missing `soul_text`/`dagi_agents`/`project_agents` vars deleted by the preamble refactor.

- **2026-06-21 A1 Bug**: Compaction failure crashed the entire session.
  **Fix**: `_compact_context()` now catches all exceptions from `compact_tool.compact()`, emits warning via `on_assistant_text`, returns `_NO_COMPACTION` — session continues.

- **2026-06-21 Bug**: Worker/review subagents never spawned — main agent implemented directly.
  **Cause**: Skill instructions compacted away before Phase 2; Active Plan injection competed with absent skill text.
  **Fix**: `## Execution Protocol` section written into every `plan.md` (compaction-immune). Active Plan injection now instructs agent to read plan file before implementing.

- **2026-06-21 A3 Bug**: `provider_order` leaked across tier switches — default tier kept plan tier's routing.
  **Fix**: Added `provider_order` as 6th field in `_base_config_snapshot`; restored in default branch; applied from `tier_cfg` in apply branch.

- **2026-06-26 Security Fix**: `tempfile.mktemp()` TOCTOU race at 3 sites.
  **Fix**: Replaced with `fd, _tmp = tempfile.mkstemp(...)` + `os.close(fd)` + `Path(_tmp).write_text(...)`. Files: `tools/_subagent_runner.py:96`, `tools/cli_subagent.py:70,73`.

- **2026-06-26 Security Fix 2**: Temp file leak on subagent timeout — lost `task_file` path when `_poll_until` returned `"timeout"`.
  **Fix**: Added `task_file: Path` to `_SubagentState`; cleanup moved into the `ret is not None` branch — fires exactly once regardless of which caller drives the final poll.

- **2026-06-26 Fix**: `SpawnCliSubagentTool` pipe buffer deadlock and missing TUI relay.
  **Fix**: Migrated to `run_subagent()`; prompt file via `extra_argv`; `on_event_factory`/`tracker` wired through constructor; full feature parity with `SpawnSubagentTool`.

- **2026-06-26 Fix**: `_rebuild_for_normal_mode` missing `memory_root=` in `create_tool_registry`. After plan→normal transition, `SkillTool` silently reverted to default `project_path / "dagi-memory"`.

- **2026-06-27 Fix**: Subagent discovery only scanned project path. `_discover_subagent_tools()` now scans `DAGI_ROOT/.dagi/subagents` first, then `cwd/.dagi/subagents` (override on name collision).

- **2026-06-27 Fix**: `build_subagent_registry` crashed for non-DAGI projects. `_load_subagent_config` now tries `project_path` first, then `_DAGI_ROOT` as fallback.

- **2026-06-27 Fix**: `json.loads(tc.function.arguments)` parsed 4 times per tool call. Now parsed once at line 547; all dispatch branches reuse `args`.

- **2026-06-27 Fix**: `_rebuild_for_reload` silently reset autonomous plan mode — passed `interactive=True` (default), flipping `AskUserTool` timeout from 60s to infinite. Fix: derive `interactive = self.config.plan_mode_initiated_by == "user"` before calling.

- **2026-06-27 Fix**: 3-site system-prompt divergence (4 confirmed bugs). Extracted `_assemble_system_string(dagi_root)` — all 8 prompt-assembly steps in one method; call sites only handle `_messages` assignment.

- **2026-06-27 Fix**: Plan skeleton missing `## Execution Protocol` heading. `_handle_enter_plan_mode` now writes the heading into the scaffold so the plan is self-contained regardless of compaction timing.

- **2026-07-03 Bug**: `loop.finish()` and `session.messages` skipped on exception in `tg/bot.py`.
  **Cause**: Both were inside `try` block; any exception from `loop.run()` bypassed them.
  **Fix**: Moved to `finally` block, guarded by `if loop:`.

- **2026-07-03 Bug**: `ask_user` in `tg/callbacks.py` hung forever when `timeout=None`.
  **Cause**: `Event.wait(None)` blocks indefinitely; Telegram has no escape hatch.
  **Fix**: `safety = (timeout + 60) if timeout is not None else 600`. 10-minute ceiling, then returns recommended option.

- **2026-07-03 Design change**: `review-session` skill's old per-session isolation was identified as the actual blocker to a real self-improvement signal — the same recurring issue got written up N separate times instead of surfacing as one cross-session pattern.
  **Fix**: Full rewrite. Two-stage pipeline: deterministic per-session extraction (unchanged `parse_jsonl_logs.py`/`chunk_session.py`) feeds a single running report; cross-session shortcomings/improvement synthesis runs once, at the end, in plan mode, citing evidence session IDs.

- **2026-07-05 Bug (causal chain)**: `EditTool` silently failed to match `oldText` on Windows — "oldText not found" even when the LLM had just read the file.
  **Cause**: Three interconnected bugs: (1) `write_text()` in both `EditTool` and `WriteTool` used Python's default text mode on Windows, which translates every `\n` → `\r\n` on disk. (2) `EditTool.run()` read the file with `read_text()` (universal newlines: CRLF→LF) but never normalised the incoming `oldText` — so if the LLM had copied CRLF bytes from `bash`/`grep` tool output into `oldText`, `content.count(CRLF_oldText)` returned 0. (3) If `newText` already contained `\r\n`, `write_text()`'s `\n`→`\r\n` translation doubled it to `\r\r\n` on disk, which normalises to `\n\n` on next read (phantom blank line).
  **Fix**: `EditTool.run()` now normalises `oldText` and `newText` via `.replace("\r\n","\n").replace("\r","\n")` before matching and replacing. Both `EditTool` and `WriteTool` now pass `newline="\n"` to `write_text()` (Python 3.10+), preventing Windows CRLF introduction entirely. All files written by DAGI now use LF on disk.

- **2026-07-14 Bug**: `/wd` TUI command didn't refresh sidebar model display after switching project directories.
  **Cause**: `_cmd_wd` called `resolve_model_config(self._model_id, project_path=new)` but never updated `_model_id`/`_model_name` when the new project's `default_model` differed, and never refreshed `sidebar._context_window`/`sidebar._reserve_tokens`. Additionally, `AgentConfig` had no field to communicate the resolved model ID back to callers.
  **Fix**: Added `model_id: str = ""` to `AgentConfig` dataclass; `_build_config_from_entry` now accepts and passes `model_id`; all three call sites in `resolve_model_config` pass the resolved ID. `_cmd_wd` now always refreshes sidebar state, and detects model ID changes (e.g. when `_model_id` was `None` and the new project's `default_model` kicks in), updating `_model_id`/`_model_name` accordingly. (Task 4 of 6-task git-workflow plan). `EnterPlanModeTool._parameters` gained required `task_summary` (kebab-case slug). `_handle_enter_plan_mode` now: (1) returns an error string if `task_summary` is missing/blank — no plan created; (2) seeds `plan.md`'s `# Plan: {task_summary}` title; (3) calls `agent/_git_branch.create_task_branch(project_path, task_summary, plan_dir.name)`, which checks out `dagi/<slug>_<plan_id>` from HEAD; (4) if not a git repo, `create_task_branch` returns `None` and the tool proceeds normally with a "no git repository detected" note in its response (not an error); (5) if it IS a repo but branch creation fails (e.g. name collision), the `RuntimeError` is caught and surfaced via `on_assistant_text` without aborting plan-mode entry.

- **2026-07-12 Feature (Tasks 2-3, git toolkit rewrite)**: `tools/git.py` expanded from `git_status`/`git_commit`/`git_rollback` (3 tools) to 8 tools: `git_status`, `git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`, `git_commit`, `git_reset`. `git_rollback` removed — no equivalent tool exists; recovery is via `git_reset` + `git_checkout` on `dagi/*` branches only. `git_commit` rewritten to require prior explicit `git_add` staging (previously implicit `git add -A` before every commit, which could silently stage unrelated dirty files). New `_dagi_branch_guard(cwd)` helper returns an error string (not exception) when the current branch doesn't start with `dagi/`; called at the top of `GitAddTool`/`GitCommitTool`/`GitResetTool` only — `git_status`/`git_diff`/`git_log`/`git_branch`/`git_checkout` remain usable on any branch (read-only or navigation, not mutating). All 8 tools wired into `agent/tools.py`'s registry (Task 3).

- **2026-07-12 Feature (Task 5, plan-work-review skill)**: `.dagi/skills/plan-work-review/SKILL.md` updated so each subtask, once its review passes, is staged (`git_add`) and committed (`git_commit`) individually rather than one commit at the end of the whole plan — keeps history reviewable per-subtask. Skill text also gained an explicit reminder that DAGI must never merge the `dagi/*` task branch back into `main`, switch off it, or delete it — the branch is left checked out and untouched at plan completion; merging/cleanup is a manual user action.

- **2026-07-12 Docs (Task 6)**: README.md architecture tree updated to list all 8 git tools (was the stale 3-tool `git_status, git_commit, git_rollback` line) plus a one-line note on the `dagi/*` guard and auto-branch-on-plan-mode behavior; added `agent/_git_branch.py` to the `agent/` tree listing (was missing).

- **2026-07-12 Feature**: Added `ctrl+n` and `ctrl+enter` as additional newline bindings in `PromptInput` (`tui/prompt_input.py`). Root cause: Windows Terminal sends identical bytes for `shift+enter` and regular `enter`, making `shift+enter` an unreliable multi-line key on that platform. Fix: collapsed `shift+enter`, `ctrl+n`, `ctrl+enter` into a single `elif event.key in (...)` branch. New tests: `tests/test_prompt_input_multiline.py` (5 Textual pilot tests, all passing). Gotcha: `Pilot.focus()` does not exist in Textual 8.2.7 — use `app.set_focus(widget)` + `await pilot.pause()` to focus a widget in tests.

- **2026-07-12 Fix (compose mode hardening)**: `action_toggle_compose` had 5 quality issues: (1) could be invoked while agent was running, hiding the ConversationPane mid-response; (2) toggling into compose hid the spinner but exit unconditionally left it hidden even if agent was still running; (3) hardcoded literal `8` for collapsed prompt height instead of a named constant; (4) blank Enter in compose mode would collapse it before the empty-value guard ran, disrupting compose flow; (5) no visual feedback that compose mode was active.
  **Cause**: Initial implementation kept the feature minimal; edge cases around the running-agent state were not considered.
  **Fix**: Commit `a791067` — guard (`_worker.is_alive() and _pending_ask is None` → early return); `_bar_was_visible` save/restore for spinner; `_PROMPT_HEIGHT_COLLAPSED` class constant; moved empty-check before `action_toggle_compose()` call in `on_prompt_input_submitted`; dynamic border title.

- **2026-07-12 Test fix**: `test_enter_with_text_submits_and_clears` replaced `widget.load_text("hello")` with `for char in "hello": await pilot.press(char)` to simulate real keyboard input. `pilot.type()` method does not exist in Textual 8.2.7 (added in a later version) — per-character `pilot.press()` is the correct approach. Added `test_enter_on_whitespace_only_does_not_submit`: pressing `ctrl+n` then `enter` inserts `"\n"` which must not submit because `"\n".strip() == ""`. Updated `PromptInput` docstring to list all three newline bindings. All 6 tests pass. Commit: `f252884`.

## Notable Points

- **Flag ordering**: `AWAIT_USER_FLAG` (`<<END_OF_RESPONSE>>`) is checked *before* `TASK_END_FLAG`. If both appear, `<<END_OF_RESPONSE>>` wins.
- **`<<END_OF_RESPONSE>>` can appear anywhere**: Detection uses `in result` (substring check); stripped via `.replace(_exit_flag, "").strip()`. Prompt gives mid-response "correct" example to encourage early placement.
- **`on_continue_injected(cur, max)` callback**: Fires in `agent/loop.py` after `CONTINUE_PROMPT` appended. TUI wires to `↩ No exit flag — continue prompt injected (N/max)` — previously invisible.
- **`api_key` vs `api_key_env`**: Direct `api_key` in config.yaml overrides env var. Empty `""` still falls through to env var. Security: prefer `api_key_env` for production.
- **Multi-turn history**: CLI passes `loop._messages` as `conversation_msgs` into next `_run_task()` call.
- **`null_response_retries` is per-API-call** — inner retry loop resets for every new LLM call. Independent of `max_continuations`.
- **`supports_pause` gates error-pause behavior**: Default `False`. TUI's `build_callbacks()` sets `True`. Explicit boolean — checking `on_pause is not lambda: None` would be fragile.
- **`_active_loop` set before `loop.run()`**: Even non-transient raises (401, 403) preserve `_messages` for the next task.
- **`_extra_body` unifies all OpenRouter extensions**: `reasoning` effort dict + `cache_prompt: True` + `provider: {order: [...]}`. `_handle_switch_model` rebuilds from `self.config` after each tier switch. To add a new extension: add field to `AgentConfig`, read in `config_loader`, add to `_base_config_snapshot`, restore in `"default"` branch, copy in `tier_cfg` branch, merge into `_extra_body` in `_handle_switch_model`.
- **`provider_order` is per-model, not top-level**: Read from per-model catalog entry because provider routing is model-specific. Slugs are OpenRouter's internal identifiers. Silently dropped by non-OpenRouter endpoints.
- **`api_error_retries` is per-iteration** — `_error_retries` resets at start of each loop iteration.
- **`max_continuations` is per-`run()` call** — `_continuation_count` resets to 0 at start of each `run()`.
- **Subagents use pipe-based IPC**: `Popen(stdout=PIPE, stderr=STDOUT)` — cross-platform. Drain thread reads each stdout line as newline-delimited JSON event → `on_subagent_event_factory` → `ConversationPane` with `[bold cyan][{subagent_type}][/bold cyan]` prefix.
- **Handoff path owned by the tool**: `SpawnSubagentTool.run()` generates `.dagi/handoffs/{type}_{uuid8}.md`; parent receives path only after subagent finishes.
- **`subagent_config.yaml` replaces `config.yaml`**: Explicit `tools:` list per subagent. `_tools_from_list()` maps name strings to instances.
- **`extend_subagent_timeout` is the resume path**: On timeout, `SpawnSubagentTool` returns `{"status": "timeout", "pid": <pid>}`; subprocess still alive in `_active[pid]`. Agent calls `extend_subagent_timeout(pid, extra_seconds)` to resume without re-spawning.
- **`pyproject.toml` is incomplete**: `typer`, `rich`, `textual` missing from declared deps. `pip install -e .` fails on clean env for CLI/TUI use.
- **TUI thread safety**: `AgentLoop` runs on daemon `threading.Thread`. All widget mutations use `App.call_from_thread()`. Sidebar uses instance attributes + `self.refresh()` — NOT Textual `reactive` — because reactive equality check on dicts misses updates when dict reference changes but content matches. Always use `dict(buckets)` (copy) when updating `_buckets`.
- **Sidebar is a top header**: Yielded first in `DagiApp.compose()` with CSS `height: 12; border-bottom: solid $panel`. `render()` returns 3-column `rich.table.Table(expand=True, box=None)` with `ratio=1` columns: left=emote+paths, center=tokens, right=plan. `_status_col()` returns `Group(face_text, info_grid)`.
- **`SlashCommandsMixin` accesses `DagiApp` state freely**: Methods reference `self._active_loop`, `self.query_one(...)`, etc. — resolved via Python MRO. No `__init__` needed.
- **`build_callbacks` circular import guard**: `tui/callbacks.py` imports `DagiApp` only inside `if TYPE_CHECKING:`.
- **TUI pause state**: ESC pauses at end-of-iteration. `action_pause()` guards: idle, pending `ask_user`, already paused. Resume requires explicit user input.
- **`PromptInput` replaces `Input`**: Custom `TextArea` subclass; `enter` = submit (clears via `load_text("")`); `shift+enter` / `ctrl+n` / `ctrl+enter` = insert `"\n"`. Added `ctrl+n` (ASCII 0x0E) and `ctrl+enter` as reliable newline aliases because Windows Terminal sends identical bytes for `shift+enter` and `enter`, making `shift+enter` unreliable on that terminal. `TextArea` has no `.placeholder` attribute. Tests: `tests/test_prompt_input_multiline.py` (6 Textual pilot tests; uses `asyncio.run()` wrapper — no `pytest-asyncio`; `Pilot.focus()` absent in Textual 8.2.7 — use `app.set_focus(widget)` + `await pilot.pause()` instead; `pilot.type()` also absent in Textual 8.2.7 — use `for char in text: await pilot.press(char)` to simulate keyboard typing). Submit guard is `if text.strip()` — whitespace-only input (e.g. bare `\n` from `ctrl+n`) does NOT submit.
- **Plan subtask status format**: `### Subtask N: [marker] name`. Four markers: `[ ]` pending, `[~]` in-progress, `[x]` complete, `[!]` failed. `[~]` is not auto-reset on session resume — user or agent must inspect.
- **TUI plan panel poll**: `DagiApp` runs 2 s `set_interval` poll reading `loop.config.plan_file`. Python GIL makes read safe without explicit lock.
- **`agents.md` is behavior-only**: Coding Standards, Behavioral Guidelines, Memory protocol, Error handling — 74 lines. Opens with pointer to PROJECT_CONTEXT.md.
- **`grill-me` skill is universal**: Phase 1: silent context gather. Phase 2: Mode A (decision-tree interrogation) or Mode B (Socratic). Phase 3: writes closing summary to PROJECT_CONTEXT.md + memory-wiki.
- **`explore_files` prompt uses citation-first output**: `## Summary` (≤80 words) + `## Citations` (`path:line_start-line_end — description`) + `## Notes` (≤5 bullets). Inspired by FastContext — citation-only output reduces main-agent token consumption by 60%+.
- **Memory subagents use `task` as the single parameter name**: `SpawnSubagentTool._compose_task()` has fallback `return kwargs.get("task", "")`. Both `memory-query` and `memory-add` declare `task:`. Using any other name produces empty task string.
- **Wiki index injected once per `run()`**: `_build_wiki_index_context()` called before first user message append — one unconditional injection, not gated on `iteration == 1`.
- **`root: memory_root` is a generic sentinel**: Any subagent config declaring it gets memory-root-restricted file access. No hardcoded type allowlist.
- **Wiki uses `.index.md` (dot-prefixed)**: Obsidian compatibility — dot-prefixed files are hidden from main note list.
- **Plan mode revision loop**: `show_plan` shows plan, asks for modifications, returns either "Plan approved" or "Modifications requested — revise and call `show_plan` again."
- **Execution Protocol is in plan.md, not conversation**: Written by plan-work-review skill into every `plan.md`. Survives context compaction. Active Plan system prompt instructs agent to re-read plan if unclear.
- **Running indicator lifecycle**: 1-line `Static` widget (`#running-indicator`), shown/hidden by `_show_running_indicator()` / `_hide_running_indicator()`. Braille spinner advanced by `set_interval(0.1, _tick_spinner)`.
- **Compose mode (`ctrl+o`)**: `DagiApp._input_expanded` bool tracks state. `action_toggle_compose()` hides `ConversationPane` (`conv.display = False`) and expands `PromptInput` to `"1fr"` (full remaining height) — or restores to `height=_PROMPT_HEIGHT_COLLAPSED` (8) / `conv.display=True` on second press. Guard at top: returns immediately if `_worker.is_alive()` and `_pending_ask is None` — compose cannot be toggled while the agent is actively running. `#running-indicator` display is saved to `_bar_was_visible` on enter and restored (not unconditionally shown) on collapse — spinner stays hidden during compose and reappears only if it was visible before. `on_prompt_input_submitted` checks for blank/whitespace-only input *before* calling `action_toggle_compose()` — bare Enter in compose mode does NOT collapse it. Border title changes to `"COMPOSE — Enter to submit · ctrl+o to collapse"` in compose mode, restored on collapse. `_PROMPT_HEIGHT_COLLAPSED: int = 8` is a class constant (must match CSS `#prompt { height: 8 }`).
- **`/clear` resets all session state**: Resets `_active_loop`, `_current_loop_ref`, `_stats`, sidebar stats and plan. Guards against running agent.
- **`/hist` in TUI writes to hidden buffer**: `console.print()` writes to a Rich console behind Textual's canvas. Known limitation.
- **`DAGI_ROOT` defined in `agent/__init__.py:3`**: The single canonical definition. Always `from agent import DAGI_ROOT`; never recompute `Path(__file__).parent.parent` at call sites.
- **Compaction failure is handled**: `_compact_context()` catches all exceptions, emits warning via `on_assistant_text`, returns `_NO_COMPACTION` — session continues.
- **Compaction dumps base64 image data into summarization prompt**: `str(msg["content"])` on list-typed content produces Python repr with raw base64 (~32K tokens of noise per image). Still unresolved.
- **`thinking_tokens` not in JSONL**: `SessionTracker.record_assistant()` captures `prompt_tokens` and `completion_tokens` but not `reasoning_tokens`. For extended-thinking models, reasoning can be 50%+ of completion budget.
- **`_parse_frontmatter` is duplicated verbatim** between `agent/skills.py:30-42` and `agent/workflows.py:30-42`. Should be extracted to `agent/_frontmatter.py`.
- **`ToolRegistry.dispatch()` swallows system-level exceptions**: `except Exception as e: return f"Error: {e}"` catches `MemoryError` and `RecursionError`. Fix: re-raise `(MemoryError, RecursionError)` before the general catch.
- **`WebFetchTool` silently upgrades HTTP to HTTPS** for non-localhost private IPs (`192.168.*`, `10.*`, etc.), causing connection failures on local dev servers.
- **`__list__:` encoding for multimodal results**: `agent/loop.py:555` encodes non-string tool results as `"__list__:" + json.dumps(result)`. Downstream consumers must know this prefix.
- **`session_end` dumps full `raw_messages` including base64 images**: A session with 5 images produces a 160KB+ `session_end` record.
- **`filter_tool_output` wiring in `agent/loop.py`**: After dispatch and sentinel chain, `filter_tool_output(result, config.reserve_tokens, self._filter_temp)` runs. `self._filter_temp` hoisted to `__init__`. `context_result` → `_messages` and `on_tool_end` (TUI display); `full_str` → `tracker.record_tool_end` (JSONL). LLM always sees safe-sized preview; logs remain forensically complete.
- **`filter_tool_output` uses `_CHARS_PER_TOKEN = 4` heuristic**: Zero/negative `reserve_tokens` disables filtering. Temp files written to `DAGI_ROOT/.dagi/temp/` (never cleaned up — see TODO).
- **`tempfile.mkstemp` bypasses `builtins.open`**: OS-level `open(2)` syscall is not intercepted by `patch("builtins.open", ...)`. Mock target for write-failure tests is `tools.output_filter.Path.write_text`.
- **Scheduler interval unit is seconds (float only)**: `parse_interval()` accepts only `float | int`. Minimum 60s.
- **Scheduler safety**: `schedule_task`, `list_scheduled_tasks`, `remove_scheduled_task` registered only when `plan_mode_initiated_by == "user"` — invisible to autonomous tasks.
- **Scheduler timeout uses abandoned daemon thread**: `daemon=True` thread joined with timeout; abandoned on expiry (Python has no `Thread.kill()`). OS reclaims on process exit.
- **`ask_user_timeout` on `AgentConfig`**: Makes scheduler autonomy configurable. Runner sets 60s; interactive sessions get default (300s via `None`).
- **Telegram `tg/` avoids shadowing `telegram` library**: `python-telegram-bot` installs as `telegram` — naming the package `telegram/` would cause circular import.
- **Telegram async/sync bridge**: `run_in_executor(None, loop.run, task)` dispatches sync `AgentLoop`. `run_coroutine_threadsafe(bot.send_message(...), event_loop).result(timeout=30)` sends from sync callback thread. Same patterns as Harbor adapter.
- **Telegram `ask_user`**: `(threading.Event(), [])` pattern; 600s floor safety prevents indefinite blocking. Numeric answers resolved to option labels.
- **RAM watchdog is CPython-specific**: Uses `ctypes.pythonapi.PyThreadState_SetAsyncExc`. Fires during test setup if system RAM ≥ 70% at process start — not a test bug, just a machine RAM issue.
- **MagicMock + `yaml.safe_load` = infinite loop**: `Reader.determine_encoding()` loops while `len(raw_buffer) < 2` and `not eof`. MagicMock satisfies both forever → unbounded allocation → OOM. Always set `project_path = Path(".").resolve()` in test mocks.
- **ANSI `[blue]` renders as purple**: Rich's `[blue]` maps to ANSI color 4 (violet on most terminals). Use hex (`[#4da6ff]`) or `[bright_blue]`.
- **`AgentConfig.system_prompt` lazy-loaded**: Defaults to `""`. Non-empty value used as-is (test injection, subagent overrides); empty triggers `load_main_system_prompt(dagi_root, config.project_path)`.
- **Dual filesystem in Harbor**: File tools operate on Windows host; only `harbor_bash` routes to Docker container. Always use `bash("cat /app/file.txt")` for container file access.
- **Benchmark config in `benchmarks/`**: `config_benchmark.yaml` at `benchmarks/config_benchmark.yaml`. Resolved via `Path(__file__).parent.parent / "config_benchmark.yaml"` in adapters. Do not recreate at project root.
- **`soul.md` at `.dagi/prompts/soul.md`**: Moved from repo root. `tui/utils.py:_system_breakdown()` still references old `dagi_root / "soul.md"` — sidebar's "sys-prompt" token count understates by ~150–300 tokens.
- **`SkillTool.run()` reloads all skills from disk on every invocation**: No reference to pre-loaded `AgentLoop.skills`. Fix: pass pre-loaded list at construction time.
- **`_estimate_tokens` base64 `str()` inflates token counts**: `compact.py:45-52` calls `str(msg["content"])` on list-typed content, producing Python repr with base64 data. Causes premature compaction.
- **Subagent discovery scans DAGI root then project**: `_discover_subagent_tools()` scans `DAGI_ROOT/.dagi/subagents` first (built-in), then `cwd/.dagi/subagents` (project, name collision wins). `cwd == DAGI_ROOT` skips duplicate scan.
- **`config.example.yaml` documents 22 tool names**: All commented out — omitting `tools:` enables everything. `switch_model` requires `advanced_model`/`worker_model`; `tmux_bash` requires injected `_bash_tool` at runtime.
- **Harbor smoke test done 2026-06-12**: 1 trial, 0 exceptions, reward 0.0 (Gemma 4, expected). Async/sync bridge worked correctly.
- **Stale test directory**: `C:UsersalexrDriverless_AGItests` at repo root — Windows path mangling artifact, harmless.
- **`review-session` selection is free-text, no parameter grammar**: DAGI interprets the user's description itself using `find` (explicit folders/files) and `chunk_session.py --list` (recency/date-based queries) — no fixed session-ID/`latest`/count/min-length syntax to remember. Default with no description: cursor off the most recent `review_*.md`'s embedded run-datetime, or the 5 most recent sessions if no prior report exists.
- **`review-session` output is one running report per invocation, not per-session**: `.dagi/self-review/review_{run-datetime}.md` accumulates findings across all sessions in the run. Repeated findings are merged as tag-accumulation (`[session-id, session-id, ...]`) on the existing bullet rather than duplicated — this tag count is the evidence signal for the end-of-run synthesis step. `parse_jsonl_logs.py`/`chunk_session.py` unchanged; old `review_{session-id}.md` files left untouched on disk but no longer produced.
- **`review-session` no longer writes to TODO.md**: The auto-append step was dropped intentionally (2026-07-03) — the skill's scope ends at the report; turning findings into TODO items is a separate manual decision.
- **`EditTool` and `WriteTool` always write LF on disk**: Both tools now use `newline="\n"` in `write_text()` (requires Python 3.10+) and normalise `\r\n`/`\r` → `\n` before writing. Files written by DAGI will always have Unix LF endings regardless of OS. `oldText` passed to `EditTool` is also normalised before matching — CRLF copied from bash/grep tool results no longer silently fails.
- **`write_text()` default on Windows translates `\n`→`\r\n`**: Python text mode on Windows (`newline=None`) adds `\r` to every newline on write, and any existing `\r\n` in the string becomes `\r\r\n` (double CR). Reading it back normalises `\r\r\n` → `\n\n`, producing a phantom blank line. Always pass `newline="\n"` when writing source files on Windows.
- **`dagi/*` branch guard only covers the dedicated git tools**: `_dagi_branch_guard()` in `tools/git.py` blocks `git_add`/`git_commit`/`git_reset` outside `dagi/*` branches, but `BashTool` can run raw `git add`/`git commit`/`git push` etc. unguarded — the restriction is a nudge for the intended tool-use path, not a hard security boundary.
- **DAGI never merges its own task branch**: `plan-work-review` skill commits per-subtask on the `dagi/<slug>_<plan_id>` branch but leaves it checked out at plan completion — merging into `main`, deleting, or switching branches is always a manual user action, never automated.
- **Escalation is a sidecar file, not a live IPC channel**: `EscalateIssueTool` writes `<handoff-stem>_escalation.md` next to the handoff report instead of streaming a message through the subagent's stdout pipe — this keeps the subagent's normal event stream untouched and lets `_subagent_runner.py`'s existing 2s poll loop (already scanning for the handoff file) pick it up with a single extra `Path.exists()` check per tick, no new subprocess IPC needed. Escalation detection intentionally runs *before* the handoff-file exit check on each tick, so a subagent that writes both files in the same tick (shouldn't happen, but isn't assumed impossible) is treated as escalated, not completed.
- **Escalations are free, retries are not**: Per `.dagi/skills/plan-work-review/SKILL.md`'s Phase 2 Step 4, resolving an escalation and re-spawning the same subagent does not consume one of the 2 retry attempts — only a FAIL verdict from a completed review does. This is deliberate: escalations exist so subagents surface genuine ambiguity instead of guessing, and penalizing that behavior with the retry budget would incentivize guessing instead.
- **`escalate_issue` requires `handoff_path` to construct**: `agent/tools.py::_tools_from_list` special-cases `escalate_issue` in its "unknown tool name" branch — if `handoff_path` wasn't provided by the caller (e.g. the `"custom"` dynamic-subagent branch), it prints a clarifying warning rather than a misleading "unknown tool" message, since the tool name is valid but the construction dependency is missing.
- **System-prompt prefix is cached separately from the live plan tail**: `AgentLoop._system_prefix` holds everything up to (not including) the "## Active Plan" pointer, set once by `_assemble_system_string()`. `_build_active_plan_tail()` renders the pointer + a "## Plan Status" numbered board (`[x]`/`[~]`/`[ ]`/`[!]`/`[?]` markers from `parse_subtask_statuses()`) fresh each time it's called. `_refresh_active_plan_tail()` re-splices `_messages[0] = _system_prefix + tail` without ever mutating `_system_prefix` itself — this is what preserves `cache_prompt`'s hit rate on the large static prefix even as subtask statuses change iteration-to-iteration. As of 2026-07-14 (Task 7), `_refresh_active_plan_tail()` is called at the top of every `run()` iteration (right after `iteration += 1`, before `on_iteration`).

## Terms & Language

- **TASK_END / `<<TASK_END>>`**: Legacy sentinel; kept as alias for `<<END_OF_RESPONSE>>`.
- **END_OF_RESPONSE / `<<END_OF_RESPONSE>>`**: Primary exit sentinel; can appear anywhere in response; stripped via substring check. Formerly `<<AWAIT_USER_RESPONSE>>`.
- **continuation**: Harness injecting a `"continue"` user message when agent stops without a termination flag.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds token budget, preserving system prompt and recent tail.
- **tier**: One of `default`, `worker`, `plan` — three model slots in `config.yaml`. Loop switches via `switch_model`.
- **TUI**: Textual-based terminal UI (`tui.py`). Fixed-canvas multi-pane layout. Requires `textual>=0.80.0`.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow. Notes at `.dagi/gnhf/notes.md`.
- **BM25**: Sparse keyword ranking; removed 2026-06-27. Replaced by grep + wiki traversal via `memory-query` subagent.
- **memory-query subagent**: Grep + wiki index traversal; returns synthesised answer with citations in handoff file; restricted to memory_root.
- **memory-add subagent**: Classifies content as project (`wiki/projects/{name}/`) or general (`wiki/knowledge/{topic}/`); writes 5-field frontmatter nodes; updates `.index.md` hierarchy.
- **`root: memory_root` sentinel**: In `subagent_config.yaml` — restricts all file tools' `cwd` and `allowed_roots` to memory_root.
- **wiki index auto-injection**: `_build_wiki_index_context()` reads `wiki/.index.md` + `projects/.index.md` + `knowledge/.index.md`; injects as system message before first user turn.
- **scheduler**: `scheduler/` package. Tasks in `.dagi/scheduler/schedule.yaml` (interval in **seconds**); log in `.dagi/scheduler/runs.jsonl`. Runner sets `plan_mode_initiated_by="dagi"` and `ask_user_timeout=60`.
- **ScheduledTask**: Fields: `name`, `prompt`, `interval: float` (seconds), `project_path`, `model`, `timeout_minutes` (default 30), `output_file`, `enabled`.
- **RunTracker**: Loads `runs.jsonl` at init; `is_due(task)` and `record_run(...)`. In-memory cache avoids repeated disk reads.
- **user-todo.md**: `wiki/user-todo.md` — Admiral's personal intentions. Entries numbered `[TODO-NNN]`; append-only. Populated by memory-add subagent's Step 0.5 TODO detection.
- **5-field wiki frontmatter**: `type`, `topic`, `description`, `date_added`, `tags`. Replaced old 8-field schema.
- **tool output filter**: `tools/output_filter.py` — `filter_tool_output(result, reserve_tokens, temp_dir)` → `(context_result, full_str)`. LLM sees truncated preview + file pointer; JSONL logs get full output.
- **IPC**: Now pipe-based (stdout JSON events) via `tools/_subagent_runner.py`. Old `agent/ipc.py` deleted.
- **Terminal-bench 2**: 89 real-world terminal tasks in Docker containers. Top scores ~60–65% as of 2026-06.
- **Harbor Framework**: Successor to Terminal-bench 2. `async run(instruction, environment, context)` interface. Shell via `await environment.exec(command)`. Adapter in `benchmarks/harbor/`.
- **emote**: One of five named expressions (`default`, `confused`, `happy`, `serious`, `funny`). Plain-text `.md` files in `.dagi/emotes/`; switched via `EmoteTool`.
- **bash_backend**: `AgentConfig` field, kept for config-file backwards compatibility only. No-op since 2026-06-13 — `BashTool` always registered regardless of value.
- **`dagi/*` branch**: Naming convention `dagi/<slug>_<plan_id>` for branches auto-created on `enter_plan_mode`. The only branch prefix on which `git_add`/`git_commit`/`git_reset` are permitted (`_dagi_branch_guard`).
- **git toolkit**: `tools/git.py`'s 8 tools — `git_status`, `git_diff`, `git_log`, `git_branch`, `git_checkout` (unrestricted, any branch) and `git_add`, `git_commit`, `git_reset` (restricted to `dagi/*` branches). Replaces the older 3-tool set (`git_status`, `git_commit`, `git_rollback`); `git_rollback` has no replacement tool.

---

## Claude's Insights

> Independent observations — not highlighted by the user.

### User Tendencies

- Invests in structural cleanup proactively once a module exceeds ~800 lines. Refactors are purely organizational — behaviour preserved exactly.
- **Review velocity outpacing fix velocity** (observed 2026-06-26, updated 2026-07-11): 18 reviews accumulated ~35 persisting items, 1 commit in **16 days** (e39e146 fixed 3 items). ~1–2 new items/review vs. 0.2 fixes applied. A focused sprint on the 12 XS-effort items (~4 hours) would halve the persist table. GNHF loop dormant **76 days** despite 209 unanalysed session logs — largest gap between stated goal ("self-improving agent") and current trajectory. **2026-07-03**: reworked `review-session` (free-text selection + single cross-session report, see Notable Points) directly targets this — closes the tooling gap that made per-session review low-signal, but the loop is still dormant until someone actually invokes it against the backlog.
- Ships incrementally and tests at each step; does not batch large refactors.
- Strong preference for backward compatibility — new features are additive (`cli.py` kept alongside `tui.py`).
- Works directly on `main` rather than feature branches.
- README and TODO kept scrupulously up-to-date.
- Prefers explicit, non-magical configuration (env var pointers in yaml). Prefers pause semantics preserving agent context (inject & resume) over cancel-and-restart.
- Prefers behavioral unification over performance micro-optimisation — accepted one extra LLM round-trip per slash command to eliminate divergent code paths.
- Follows strict TDD for infrastructure: writes all failing tests before a single line of implementation.
- Actively prunes redundant config flags once a general mechanism covers them.
- Engages deeply in design grilling before implementation; responds well to adversarial questioning. Does not leave design open-ended.
- Naturally gravitates toward Dependency Inversion; accepted `_bash_tool: BaseTool | None` generalization immediately.
- Invests heavily in skill design: treats skills as behavioral specifications, not code.
- Will accept dead-code cleanup when shown evidence.

### Project Shortcomings

- **`filter_tool_output` Task 3 pending**: Tool output filtering wired and tested (2026-06-30). TUI `on_tool_end` callback threading (Task 3) still pending — tool panel shows filtered string, not full output.
- **Session cost tracking almost always blank**: `record_assistant()` reads `usage.cost`; most providers (including OpenRouter) don't populate it. `$—` in sidebar; `total_cost: null` in JSONL.
- **`/hist` TUI broken**: Writes to a `rich.Console` behind Textual's canvas. Needs reimplementing to write to `ConversationPane`.
- **`ask_user` UX in TUI**: Returns verbatim free text (no option resolution). `PromptInput` has no placeholder — no visual cue distinguishing `ask_user` from normal prompt while cursor is idle.
- **Dependency split**: `requirements.txt` (23 packages, pip freeze) vs. `pyproject.toml` (~10 more). Neither alone produces a working install.
- **BashTool is unsandboxed**: No command blacklist, no process group kill on timeout. An agent could run destructive bash commands — including raw `git` commands that bypass the new `dagi/*` branch guard (2026-07-12) on `git_add`/`git_commit`/`git_reset` entirely. The guard was accepted as a nudge, not a security boundary, when the git-workflow plan was implemented.
- **No pause during subagent execution**: ESC pauses parent loop; child subprocess continues unaffected.
- **`harbor_bash` name must match tools list**: After any `HarborBashTool.name` change, `config_benchmark.yaml` `tools:` must be updated. Silent failure (host bash used instead).
- **`run_harbor.bat` requires `PYTHONUTF8=1`**: CP1252 encoding fails on Unicode box-drawing chars in Harbor output.
- **Harbor dual-filesystem mismatch**: File tools (read/write/find/grep) operate on Windows host; weaker models try these on container paths and get stuck.
- **RAM watchdog is fragile**: Threshold hardcoded at 70%; no env-var override. On a 31 GB machine with IDE+browser, idle RAM sits at 72–73% — watchdog fires during test startup and fails all tests.
- **Base64 image data in compaction prompt**: `_format_messages_for_summary()` calls `str(msg["content"])` on list-typed content → ~32K tokens of base64 noise per image in summarization call.
- **`thinking_tokens` not in JSONL session logs**: `SessionTracker.record_assistant()` misses `reasoning_tokens`. For extended-thinking models, reasoning can be 50%+ of completion budget.
- **No integration tests**: All tests are unit tests with mocked LLM clients.
- **Stale scratch files at root**: `temp_system_prompt.txt`, `temp_test.ipynb`, `plan.md` — should be cleaned up.
- **`_parse_frontmatter` duplicated verbatim** in `agent/skills.py:30-42` and `agent/workflows.py:30-42`. Extract to `agent/_frontmatter.py`.
- **`ToolRegistry.dispatch()` swallows `MemoryError`/`RecursionError`**: Broad `except Exception` catch.
- **`WebFetchTool` silently upgrades private IPs to HTTPS**: `192.168.*`, `10.*`, etc. fail on local dev servers.
- **`__list__:` encoding undocumented**: Non-string tool results encoded as `"__list__:" + json.dumps(result)` — stored in JSONL logs and callbacks. Consumers must know this convention.
- **`session_end` dumps full `raw_messages` with base64**: Second copy of all tool results (including images) serialized into one JSONL line. 160KB+ per image-heavy session.
- **Tool result content not truncated in JSONL**: `record_tool_end` writes full result string. Filter protects the LLM context but JSONL logs are unbounded. 208 accumulated logs are primary disk consumer.
- **`SkillTool.run()` reloads all skills on every invocation**: Rescans disk, rereads every SKILL.md, rebuilds map on every `skill("name")` call.
- **`_estimate_tokens` base64 inflation**: `str(msg["content"])` on vision-format content inflates token estimate → premature compaction.

### Assumptions to Challenge

- **Single-user, single-session**: no locking on `config.yaml` or session logs; two simultaneous dagi instances could corrupt state.
- **OpenAI-compatible API contract**: assumes provider's `/chat/completions` response schema matches exactly. Providers diverge (`reasoning_content` is non-standard).
- **English-only tasks**: system prompt and skill docs are English-only.

### Dependencies & Risks

- **OpenRouter** is the primary API gateway for most catalog models. A rate limit, outage, or pricing change affects all non-OpenAI models simultaneously.
- **`ddgs` (DuckDuckGo search)**: unofficial wrapper, no SLA, can break on site changes.
- **`crawl4ai`**: heavy Playwright-based dependency, pinned at `>=0.8.7` (raised from `>=0.4` to patch 3 critical CVEs — SSRF, JWT auth bypass, path traversal).
- **Python 3.14** in the `dagi` conda env — pre-release. Some packages may lack wheels.
- **`httpx`**: maintainer closed all issues Feb 2026 — governance risk flagged in 2026-07-02 review.

### Potential Areas of Exploration

- **Fix `/hist` in TUI**: reimplement `_cmd_hist()` to write session history to `ConversationPane`.
- **`ask_user` UX**: indicator (highlighted label or border colour) distinguishing `ask_user` prompt from normal input.
- **Cache hit visibility**: read `usage.prompt_tokens_details.cached_tokens` and display cached vs. non-cached in sidebar.
- **Streaming responses**: per-token sidebar updates and incremental `ConversationPane` streaming.
- **Structured output / tool-call validation**: schema-level validator at registry layer.
- **Session replay / dry-run mode**: JSONL log has everything needed for deterministic replay — useful for debugging and regression testing.
- **Parallel subagent dispatch**: `spawn_*` called multiple times; agent polls each via `extend_subagent_timeout`. No architectural change needed.
- **Emote animation**: `_status_col()` runs on every `refresh()` — animate on `self._status == "running"` with no new state.
- **Fix RAM watchdog threshold**: add `RAM_WARN_PCT = int(os.getenv("DAGI_RAM_WARN_PCT", "70"))` to eliminate false test failures on memory-constrained machines.
- **`thinking_tokens` in JSONL**: extend `record_assistant()` to capture `completion_tokens_details.reasoning_tokens`.
- **No full benchmark run yet**: Smoke test only (1 task). Full 89-task Terminal-bench 2 / Harbor run not performed.
- **GNHF self-review dormant 76 days**: 209 unanalysed session logs (last: 2026-07-05). `review-session` was reworked 2026-07-03 (free-text selection + single cross-session report) specifically to make a batch run high-signal instead of N repetitive per-session write-ups — the tooling gap is closed, but no bootstrap run has been invoked yet. See TODO.md Work Queue / Self-Improvement Queue for the pending "review the 10 most recent sessions" action.
