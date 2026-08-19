# AGENTS.md

> Last updated: 2026-08-19 (Task 8: compact cache prefix feature complete — fork_context_path wired end-to-end) | [README](README.md) | [TODO](TODO.md)


---

## Overview

Driverless AGI (dagi) is a self-hosted Python agentic coding assistant: Plan → Act → Observe loop with tools (read, write, edit, bash, grep, etc). 

## Rules

- Use `DEFAULT_PYTHON_ENV` for all Python scripts and package installs.
- Never invoke `benchmarks/dagi_eval` against a real model without explicit authorization — `--solver` defaults to `"agent"`, always pass `naive`/`gold` unless authorized.
- DAGI never merges, switches off, or deletes its own `dagi/*` task branch — the user handles that.
- Always update `AGENTS.md` after completing a task.

## Git Workflow

All git operations use `bash`. Follow this workflow at the start of every task:

1. **Check state** — run `git status` and `git branch --show-current`. If there are uncommitted or unstaged changes, or you are not on the intended base branch, **ask the user**: stash, commit, or checkout a different base?
2. **Create branch** — `git checkout -b dagi/<task-name>` from the confirmed base.
3. **Commit discipline** — 1 commit per subtask completion + 1 commit after updating project context. Use [Conventional Commits](https://www.conventionalcommits.org/) format: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`.
4. **On task end** — stay on `dagi/*` branch. Ask the user if they want to merge back to the previous branch. **Never merge unilaterally.**

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

### Token Budgets

- Per-task: 4,000 tokens. Per-session: 30,000 tokens.
- If approaching budget: summarize and start fresh. Surface the breach — do not silently overrun.

### Memory

- **Memory query:** After receiving a substantive task (anything beyond a greeting or quick factual question), invoke `skill("memory-query")` before taking any action. Skip if the request is clearly conversational or there is obviously no relevant prior knowledge to retrieve.
- **Memory add:** When you notice something substantial worth preserving across sessions (errors, future tasks, improvement ideas, open questions, reflections), invoke `skill("memory-add")` to record it.

### Error handling

- Fail fast with clear, actionable messages
- Never swallow exceptions silently
- Include context (what operation, what input, suggested fix)

## Process Flow

1. Entry point (`tui.py`/`telegram_bot.py`/`main.py`) receives task string.
2. `resolve_model_config()` reads `config.yaml` (+ per-project `.dagi/config.yaml`) → `AgentConfig`.
3. `AgentLoop.__init__()` loads skills, builds `ToolRegistry`, assembles system prompt (including AGENTS.md).
4. `AgentLoop.run(task)` loops: check pause (TUI) → call LLM → dispatch tools or check termination (`<<END_OF_RESPONSE>>` / `<<TASK_END>>`) → inject continue prompt up to `max_continuations`.
5. Context compaction triggers mid-loop when token count exceeds threshold.
6. `SessionTracker.finish()` writes session summary to `.dagi/logs/`.

## Architecture

```
tui.py / telegram_bot.py / main.py / dagi_gui/__main__.py
    │
    tui.py → tui/ (app, commands, callbacks, conversation, sidebar, prompt_input, streaming)
    │
    dagi_gui/__main__.py → dagi_gui/ (protocol, interaction, callbacks, session, catalog, history, server, plan_monitor)
    │   Python sidecar: reads NDJSON commands on stdin, emits NDJSON events on stdout.
    │   dagi_gui/server.py drives AgentLoop; dagi_gui/plan_monitor.py watches PLAN.md.
    │   Paired with Electron frontend (desktop/) over stdio NDJSON pipe.
    │
    desktop/ (Electron 33 + React 18 + TypeScript + Vite, three build contexts)
    │   main/main.ts         — BrowserWindow, PythonSupervisor, IPC routing
    │   main/python-supervisor.ts — spawns sidecar, line-splits NDJSON, crash restarts
    │   main/preload.ts      — channel-whitelisted contextBridge (SEND/RECV sets)
    │   renderer/App.tsx     — useReducer(dagiReducer), IPC subscription, slash dispatch
    │   renderer/state.ts    — pure dagiReducer (no Redux); AppState + Action union
    │   renderer/components/ — Conversation, ToolCard, Composer, Sidebar, QuestionDialog
    │   shared/protocol.ts   — Zod discriminated unions for all 19 commands + 17 events
    │
    └── AgentLoop (agent/loop.py)
            ├── ToolRegistry (agent/registry.py)
            ├── SessionTracker (agent/session.py)
            ├── Context compaction (AgentLoop.compact + tools/compact boundary)
            ├── SkillLoader (.dagi/skills/)
            └── AgentCallbacks → TUI via App.call_from_thread()
                             → GUI via dagi_gui/callbacks.py (EventWriter)
```

**Tool layout:** `tools/<name>/__init__.py` re-exports from `_<name>.py`; shared helpers are flat files in `tools/` (`_path_guard.py`, `_hash_cache.py`, `_subagent_runner.py`, `_handoff_format.py`, `_task_envelope.py`, `output_filter.py`, `subagent_main.py`, `subagent_api.py`). `edit` uses `oldText`/`newText` unique-substring matching; `read` outputs `cat -n` style line numbers.

**Subagents:** Pipe-based subprocesses. Public API: `run_subagent()` / `SubagentResult` / `resume_subagent_by_pid()` in `tools/subagent_api.py` (never import `_subagent_runner` directly). `run_subagent()` accepts optional `parent_log: SessionLog` — when provided and a turn is open, logs a `branch/start` event before spawning; `SubagentResult.branch_id` carries the generated id. `run_subagent()` also accepts `fork_context_path: str | None` — when set, injects `--fork-context <path>` into the subprocess argv (used by `compact()`). Each type is a self-contained package: `.dagi/subagents/<type>/main.py` exports a `BaseTool` subclass; `_discover_subagent_tools()` in `agent/subagent_tools.py` discovers types by import (scans DAGI root then `cwd/.dagi/subagents/`; project types override built-ins by name). All 10 constructors accept `session_log=None` and store `self._session_log`; `run()` forwards `parent_log=self._session_log` — `session_log` is passed unconditionally (no `inspect.signature` conditional). 10 built-in types: `explore_files`, `web_research`, `memory-query`, `memory-add`, `memory-refresh`, `long-reader`, `plan`, `cli`, `worker`, `review`. `subagent_config.yaml` schema: `tools`, `model_tier`, `default_handoff_spec`, `agents_md` (new — path to AGENTS.md injected into subagent system prompt; replaces the old hardcoded dict). WriteHandoffTool auto-injected when `handoff_path` is set — calling it writes the report and triggers immediate return via `<<HANDOFF_WRITTEN>>` sentinel. If missing at exit, `_ensure_handoff()` re-enters with a corrective prompt; last-resort scrape drops `<stem>_unverified.flag`. All spawn tools render `ok_unverified` as a warning banner. Every subagent task is wrapped by `_task_envelope.py` (`## Task` / `## Instructions` / `## Output`), with parent-supplied `briefing` and `handoff_spec`. Custom one-off subagent workflows are authored as DAGI scripts calling `run_subagent()` directly (see `.dagi/skills/run_subagent/SKILL.md`).

**Compact cache-prefix (branch `dagi/compact-cache-branching`):** The compact subagent inherits the parent's warm KV-cache prefix. Flow: (1) `compact()` captures `_last_request_snapshot` (frozen copy of the last API request's model + messages + tools — no credentials) immediately before every provider call. (2) On compaction trigger, `compact()` appends a `BRANCH_START` event with `parent_cut_seq` pointing to the last summarised step (retroactive branch — the physical append happens after later events but the logical fork is earlier). (3) `build_fork_context()` serialises version-1 fork-context JSON: `{version, branch:{id, parent_cut_seq, parent_surface_generation}, request:{model, messages, tools, parallel_tool_calls, extra_body, base_url}}` — no API keys. (4) Fork-context written to a temp file, passed to `run_subagent(fork_context_path=...)` which injects `--fork-context <path>` into the subprocess argv. (5) Compact subprocess (`subagent_main.run_forked_compact_mode`) reads the fork-context, calls `resolve_model_config()` to get credentials from environment (NOT from the fork-context), makes a single non-streaming API call with the inherited prefix + compact task, writes assistant text directly to the handoff file. (6) Parent validates: `result.is_ok`, non-empty handoff text, surface generation unchanged (atomicity check), all edge events live. On success: appends `CONTEXT_COMPACTION`, calls `_sync_messages()`. On failure: returns `_NO_COMPACTION` — surface untouched. `model_tier: inherit` in `.dagi/subagents/compact/subagent_config.yaml` signals the forked-compact path.

## Key Files


| Path                                                 | Purpose                                                                                                                                                        |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/loop.py`                                      | Core agent loop, system-prompt assembly, termination/compaction, WriteHandoff sentinel dispatch                                                                |
| `agent/config_loader.py`                             | Reads `config.yaml`, merges `.dagi/config.yaml`, resolves API key, services, Telegram config                                                                   |
| `agent/session_log.py`                               | Append-only event log; `SessionLog.branches` tracks subagent branches; `branch_event(id)` returns the BRANCH_START event for a branch                         |
| `agent/session_events.py`                            | Event vocabulary constants (`TURN_START`, `BRANCH_START`, etc.); `SESSION_FORMAT_VERSION`                                                                      |
| `agent/subagent_tools.py`                            | `_discover_subagent_tools()` import-based discovery; `build_subagent_registry()` with `tool_names_override`                                                    |
| `tools/subagent_api.py`                              | **Public API** — `run_subagent()` logs `branch/start` on `parent_log` before spawning; `SubagentResult.branch_id` carries generated id                        |
| `tools/_subagent_runner.py`                          | Private pipe-based subprocess spawner; returns raw dicts; wrapped exclusively by `subagent_api.py`                                                             |
| `tools/_handoff_format.py`                           | Shared handoff rendering and status dispatch for all subagent-spawning tools                                                                                   |
| `tools/_task_envelope.py`                            | Universal `briefing`/`handoff_spec` envelope for subagent tasks                                                                                                |
| `services/doc_converter/`                            | Standalone FastAPI service (port 8100); PDF→markdown via docling/ocrmypdf, Office→markdown via markitdown; own conda env                                       |
| `tui/app.py`, `tui/streaming.py`, `tui/callbacks.py` | TUI lifecycle, StreamPreview expand/collapse, callbacks bridge                                                                                                 |
| `dagi_gui/server.py`                                 | `GUIServer`: reads NDJSON commands from stdin loop, dispatches to `AgentLoop`/session                                                                          |
| `dagi_gui/session.py`                                | `SessionController`: lifecycle (run/pause/resume/cancel/clear/compact/shutdown), `_kill_active_work` kills active bash + subagents on pause                     |
| `desktop/src/shared/protocol.ts`                     | Zod discriminated unions: 19 command types + 17 event types; `PROTOCOL_VERSION=1`; `parseEvent`/`serializeCommand`                                             |
| `desktop/src/main/python-supervisor.ts`              | `PythonSupervisor extends EventEmitter`: spawns sidecar, NDJSON line-splitting, pending Map, exponential back-off restarts; injectable `spawnFn` for tests      |

## Errors Log (recent)

- **2026-07-26**: TUI displayed wrong model name — `get_model_display_name()` only read root config, missed `.dagi/config.yaml` overrides → TUI now resolves via `resolve_model_config()`.
- **2026-07-26 (known, deferred)**: `agent/loop.py` is 1172 lines (cap: 500), `AgentLoop.run` CC is 48 (cap: 8) — spun off as standalone refactor task.
- **2026-08-04**: Subagent refactor merged to main — `tools/subagent_api.py` public API; 9 types each with `main.py` + `subagent_config.yaml`; import-based discovery; `SpawnSubagentTool`/`SpawnCliSubagentTool` deleted; `--tools`/`--model-tier` CLI args; `agents_md` config; `DEFAULT_PYTHON_ENV` in system prompt; `run_subagent` skill; `plan`/`cli` configs fixed (were missing, caused `FileNotFoundError` on preset load).
- **2026-07-27**: Hashline experiment reverted — smaller models made too many errors copying opaque `LINE#HASH` anchors → restored `oldText`/`newText` edit, `cat -n` read, plain `file:line:` grep. `_hashline.py`, `edit_text/` tool, and hashline tests removed.
- **2026-08-07**: DeepSeek thinking-mode rejected multi-tool-call batches — (1) `model_extra` fallback in `_consume_stream` / `_extract_reasoning` only checked `"reasoning"` key, missing DeepSeek's `"reasoning_content"` key; (2) interleaved format split tool_calls across multiple assistant messages, only the first carrying `reasoning_content` → fixed both key lookups; restructured to emit one assistant message with all tool_calls before the dispatch loop (standard OpenAI format).
- **2026-08-08**: DeepSeek rejected orphaned tool messages — two causes: (1) compaction safe-cut logic could split multi-tool-call groups, leaving tool-result messages without their parent assistant → safe cuts now skip positions where the tail would start with a tool message; (2) `RELOAD_SKILLS_SENTINEL` injected a system message between assistant+tool_calls and tool results → deferred system messages until after all tool results are appended.
- **2026-08-10**: `conda run` drops stdin when used in Claude Code hook context — `json.load(sys.stdin)` always gets empty input → use `C:/Users/alexr/miniconda3/envs/dagi/python.exe` directly for hook scripts instead of `conda run -n dagi python`.
- **2026-08-11**: Grep Python fallback (no ripgrep) had no timeout — `rglob("*")` over Google Drive mount (`memory_root`) hung indefinitely, freezing TUI spinner → added 15s wall-clock timeout to both enumeration and file-scanning phases; installed `ripgrep` via conda.
- **2026-08-16**: `QuestionBroker.has_pending` missing `@property` — `_handle_pause` tested the bound method (always truthy), so pause never killed bash or paused loop → added `@property`; fixed stale test using `broker._pending` (old API) to use `broker._pending_id`.
- **2026-08-17**: Brief spec for `test_branch_id_uses_subagent_type` patched `Path.read_text` globally — broke `yaml.safe_load` in `_load_preset` → fixed by creating a real preset dir in `tmp_path` and removing the overly-broad mock.
- **2026-08-19**: Task 6 — integration tests missing `_last_request_snapshot` (new guard in `compact()`) → added `_SNAPSHOT` fixture + `loop._last_request_snapshot = _SNAPSHOT` to 3 tests; 17/17 passed.
- **2026-08-19**: Task 7 — added 4 new integration tests (list identity, raw-event preservation, failure atomicity, repeated compaction) to `test_compact_integration.py`; fixed missing snapshot in `test_compact_subagent_failure_leaves_surface_intact`; 8/8 pass.
- **2026-08-19**: Task 7 bug — `extra_argv.extend(["--system-prompt-file", ...])` extended the raw caller parameter (None) instead of internal `_extra_argv` accumulator → `AttributeError` on all 14 TestRunSubagent + TestBranchStartLogging tests; fixed as `_extra_argv.extend(...)`.
- **2026-08-19**: Task 8 — compact cache-prefix feature complete; `run_subagent(fork_context_path=...)` wires `--fork-context` to subprocess; 884 tests pass.

## Notes & Terms

- **AGENTS.md** is force-injected into every session's system prompt by `_assemble_system_string()`; the file is re-read from disk on every `AgentLoop.__init__` and `_messages[0]` is always overwritten — so AGENTS.md edits made during task N are live in task N+1's context window.
- **`<<END_OF_RESPONSE>>`**: primary exit sentinel (substring check on LLM text responses only); `_escape_sentinels()` rewrites it to `< <END_OF_RESPONSE>>` in tool results before they enter `_messages` to prevent LLM echo-back.
- **Document conversion**: `.pdf/.docx/.xlsx/.pptx` → doc-converter service at `AgentConfig.services["doc_converter"]`, hard-fail if unreachable. PDF page selection via `pages` parameter.
- **Subagent handoff**: WriteHandoffTool auto-injected; `<<HANDOFF_WRITTEN>>` sentinel triggers immediate return **only when `tc.function.name == "write_handoff"`** (name-gated to prevent false fire from inlined handoff content). Missing handoff → corrective re-entry → last-resort scrape + `_unverified.flag`.
- **Memory wiki**: unified store at `G:\My Drive\black_grimoire\dagi-memory\wiki\` — four categories (projects, todos, knowledge, events), three skills (memory-add, memory-query, memory-refresh); Claude Code hook at `~/.claude/hooks/bm25_memory_recall.py` provides passive BM25 recall on every substantive prompt.
- **`tools:` allowlist** (`config.yaml`): post-registration filter via `reg.filter_to(config.tools)`. Any tool not named here is silently stripped — including auto-discovered subagent spawn tools. When adding a new subagent type, also add its tool name to the list.
- **`DEFAULT_PYTHON_ENV`**: detected at `AgentLoop` startup from `CONDA_DEFAULT_ENV` or `VIRTUAL_ENV` and injected into the system prompt so DAGI knows which env to use for Python commands. Override in the project's `AGENTS.md` if a different env is needed.
- **Windows / conda**: `EditTool`/`WriteTool` always write LF, normalize `oldText`/`newText` for CRLF safety. Use `conda run -n dagi python` for DAGI scripts; for Claude Code hooks use `envs/dagi/python.exe` directly — `conda run` drops stdin in hook context.
- **`subagent_api` vs `_subagent_runner`**: `tools/subagent_api.py` is the public API (preset resolution, envelope, `SubagentResult`); `tools/_subagent_runner.py` is the private subprocess spawner. Never import `_subagent_runner` directly from outside `subagent_api.py`.
- **`desktop/out/` and `desktop/node_modules/`**: both gitignored (added 2026-08-16); Electron build artifacts must not be committed — regenerate with `npm run make` in `desktop/`.
- **Subagent discovery + branch logging**: `_discover_subagent_tools()` passes `session_log` unconditionally to each tool constructor; `run()` forwards it as `parent_log` to `run_subagent()`, which logs `branch/start` before spawning. Mock `tools.subagent_api._runner.run_subagent` (not the public function) in tests so the logging code actually runs.
- **`parent_cut_seq` on BRANCH_START**: optional field that overrides the physical event seq as the fork cut-off in `reconstruct()`. Enables retroactive branching — the BRANCH_START is appended after later events but logically forks from the earlier seq. `_collect_surface_events` filters by `seq <= fork_seq` and is unchanged.
- **`_last_request_snapshot`**: `AgentLoop` field (dict | None) capturing `model`, `messages`, `tools`, `parallel_tool_calls`, `extra_body`, `base_url` from `_create_kwargs` right before the provider call. Updated on every retry iteration. Used by `build_fork_context()` to build the compact fork-context file.
- **`run_forked_compact_mode()`**: `tools/subagent_main.py` entry point for `model_tier: inherit` compact. Inherits provider prefix from fork-context JSON (v1); makes a single non-streaming call; rejects tool-call/empty/truncated responses; writes assistant text directly as handoff (no `write_handoff` tool). Credentials always from env, never from fork-context. Retry logic extracted into `_compact_call_with_retry()` to stay within 100-line limit.

## User Insights

> Independent observations — not highlighted by the user.

### User Tendencies

- Ships incrementally, tests at each step; no large-batch refactors.
- Structural cleanup at ~800 lines, organizational only, behavior preserved.
- Works directly on `main`; prefers local merge over push+PR.
- Prefers explicit config and pause-and-resume over cancel-and-restart.
- Follows strict TDD for infrastructure; adversarial design grilling before implementation.
- Comfortable delegating multi-task features to autonomous subagents without check-ins.
- Hard line on real LLM spend — never without explicit permission.
- GNHF self-review dormant 95+ days despite 259 unanalysed sessions.
- Actively building Claude Code tooling (BM25 memory hook) around DAGI's wiki infra — treats Claude Code as first-class runtime alongside DAGI.

### Project Shortcomings

- ESC pauses parent loop but child subprocesses continue.
- Session cost tracking mostly blank (providers don't populate `usage.cost`).
- `/hist` in TUI broken — writes to `rich.Console` behind Textual's canvas.
- `_parse_frontmatter` duplicated verbatim between `agent/skills.py` and `agent/workflows.py`.
- `disable-model-invocation` flag has zero code enforcement — purely advisory.
- dagi_eval `--timeout-min` doesn't bound scoring phases or blocked API iterations.

### Potential Areas of Exploration

- Extract `web_fetch`/`web_search` as MCP-analog services (like doc_converter).
- Fix `/hist`; add cache-hit visibility in sidebar.
- Session replay / dry-run mode from JSONL logs.
- Parallel subagent dispatch via `background: true` + `get_subagent_result(id)` two-tool protocol.
- Bootstrap GNHF self-review against 259 accumulated session logs.
- TODO-013: DAGI-native `memory_recall` tool (BM25 inside agent loop, explicit tool call) still pending — Claude Code hook (passive, pre-prompt) is a complement, not a replacement.
- Tasks 1–7 of `compact-cache-prefix` done; remaining tasks (8+) in `.superpowers/sdd/2026-08-18-compact-cache-prefix/`.
