# AGENTS.md

> Last updated: 2026-08-23 (affect/process lifecycle integration) | [README](README.md) | [TODO](TODO.md)




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


## Architecture

**Inherited subagents and `/wtf`:** `ParentContextProvider` snapshots the exact parent request prefix (model, messages, tool schemas/order, provider options, and base URL) and records a stable branch. Version-2 forked children receive that prefix plus one new task message, use an explicitly allowlisted inherited registry, and call the parent-visible `write_handoff` schema as their final action; blocked tools return `Error: Access blocked for this tool`. The runner validates the written file and retries a missing/malformed report once. The read-only `wtf` preset writes strict three-section reports under `.dagi/errors/`; `AgentLoop.run_wtf()` validates branch generation, path, and report structure before appending only a `/wtf` reference to the parent. TUI `/wtf [description]` runs asynchronously, waits for a pause checkpoint when needed, and displays only the report description and path.

```
tui.py / telegram_bot.py / main.py / dagi_gui/__main__.py / pyside_gui/__main__.py
    │
    tui.py → tui/ (app, commands, callbacks, conversation, sidebar, prompt_input, streaming)
    │
    pyside_gui/__main__.py → pyside_gui/ (app, bridge, conversation, overlays, commands, sidebars)
    │   PySide6/Qt 6 desktop GUI. AgentBridge translates AgentCallbacks → Qt Signals.
    │   Agent runs on daemon thread; all UI via queued signals or QMetaObject.invokeMethod.
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

**Subagents:** Pipe-based subprocesses. Public API: `run_subagent()` / `SubagentResult` / `resume_subagent_by_pid()` in `tools/subagent_api.py` (never import `_subagent_runner` directly). `run_subagent()` accepts optional `parent_log: SessionLog` — when provided and a turn is open, logs a `branch/start` event before spawning; `SubagentResult.branch_id` carries the generated id. `run_subagent()` also accepts `fork_context_path: str | None` — when set, injects `--fork-context <path>` into the subprocess argv (used by `compact()`). Each type is a self-contained package: `.dagi/subagents/<type>/main.py` exports a `BaseTool` subclass; `_discover_subagent_tools()` in `agent/subagent_tools.py` discovers types by import (scans DAGI root then `cwd/.dagi/subagents/`; project types override built-ins by name). All 8 active constructors accept `session_log=None` and store `self._session_log`; `run()` forwards `parent_log=self._session_log` — `session_log` is passed unconditionally (no `inspect.signature` conditional). 8 built-in types (after simplification): `explore_files`, `web_research`, `memory-query`, `memory-add`, `memory-refresh`, `read-large-text`, `worker`, `review`. (`plan`, `cli`, `escalate_issue` were deleted in subagent-simplification branch.) `SubagentResult` fields: `status`, `handoff_text`, `handoff_path`, `session_log_path`, `pid`, `branch_id` — **no `escalation` field** (removed in simplification). `dispatch_status_result()` signature: `(result: dict, error_prefix: str, include_timeout: bool = True)` — **no `include_escalation` param**. `subagent_config.yaml` schema: `tools`, `model_tier`, `default_handoff_spec`, `agents_md`. WriteHandoffTool is always visible to the main agent and auto-injected when a child `handoff_path` is set; its `<<HANDOFF_WRITTEN>>` sentinel immediately ends either turn without `END_OF_RESPONSE`. Regular pipe mode retains `_ensure_handoff()` and its unverified scrape fallback; inherited v2 validates the explicit tool-written file and hard-fails after one corrective retry. Every subagent task is wrapped by `_task_envelope.py` (`## Task` / `## Instructions` / `## Output`), with parent-supplied `briefing` and `handoff_spec`. Custom one-off subagent workflows are authored as DAGI scripts calling `run_subagent()` directly (see `.dagi/skills/run_subagent/SKILL.md`).

**Compact cache-prefix (branch `dagi/compact-cache-branching`):** The compact subagent inherits the parent's warm KV-cache prefix. Flow: (1) `compact()` captures `_last_request_snapshot` (frozen copy of the last API request's model + messages + tools — no credentials) immediately before every provider call. (2) On compaction trigger, `compact()` appends a `BRANCH_START` event with `parent_cut_seq` pointing to the last summarised step (retroactive branch — the physical append happens after later events but the logical fork is earlier). (3) `build_fork_context()` serialises version-1 fork-context JSON: `{version, branch:{id, parent_cut_seq, parent_surface_generation}, request:{model, messages, tools, parallel_tool_calls, extra_body, base_url}}` — no API keys. (4) Fork-context written to a temp file, passed to `run_subagent(fork_context_path=...)` which injects `--fork-context <path>` into the subprocess argv. (5) Compact subprocess (`subagent_main.run_forked_compact_mode`) reads the fork-context, calls `resolve_model_config()` to get credentials from environment (NOT from the fork-context), makes a single non-streaming API call with the inherited prefix + compact task, writes assistant text directly to the handoff file. (6) Parent validates: `result.is_ok`, non-empty handoff text, surface generation unchanged (atomicity check), all edge events live. On success: appends `CONTEXT_COMPACTION`, calls `_sync_messages()`. On failure: returns `_NO_COMPACTION` — surface untouched. `model_tier: inherit` in `.dagi/subagents/compact/subagent_config.yaml` signals the forked-compact path.

**Expression asset libraries (branch `dagi/affect-and-process-emotes`):** `agent/expression_assets.py` loads `.dagi/emotes/vad/manifest.yaml` and `.dagi/emotes/states/manifest.yaml` into immutable `ImageAsset` / `TextFallback` refs, validates asset paths stay under their channel roots, and caches warning keys so broken manifests warn once while later lookups fall back to `.dagi/emotes/default.md` (or literal `DAGI` if unreadable). `VadLibrary.resolve()` uses Euclidean distance plus hysteresis against the current id; `ProcessStateLibrary.resolve()` follows `tool:<name> -> tool -> thinking -> idle`.

**Dynamic context + affect callbacks (branch `dagi/affect-and-process-emotes`):** `agent/dynamic_context.py` builds the ephemeral request board (Python env, active plan status, affect line) outside the static system prefix. `AgentLoop(initial_affect=...)` restores affect once from history, binds `on_affect_changed(AffectSnapshot)`, and normal registries expose `adjust_affect` only when a controller is bound; the legacy `tools/emote` package has been deleted.

**Process-state controller (branch `dagi/affect-and-process-emotes`):** `agent/process_state.py` defines immutable `ProcessSnapshot` plus `ProcessStateController`. `AgentLoop` publishes `on_process_state_changed(ProcessSnapshot)` through API/tool/pause/resume/error lifecycle transitions, deduplicates exact repeats, and models tool flow as `idle -> thinking -> tool:<name> -> thinking`.

**Affect session persistence (branch `dagi/affect-and-process-emotes`):** Root `SessionTracker`s now own the bound affect controller, persist `affect_*` JSONL records alongside normal session events, and let child trackers reuse the root controller without replacing it. `agent/history.py` shares a private JSONL loader between raw-message restore and affect restore, selecting the latest valid affect record while preserving the original `affect_init` baseline and warning once on malformed entries.

## Key Files


| Path                                                 | Purpose                                                                                                                                                        |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/loop.py`                                      | Core loop, parent fork capture, system-prompt assembly, affect/process lifecycle, termination/compaction, and handoff dispatch                                  |
| `agent/dynamic_context.py`                           | Builds the ephemeral request board: Python env, active plan status, and affect line without mutating the static system prefix                                  |
| `agent/config_loader.py`                             | Reads/merges config, resolves API keys/models/services, and validates affect tuning                                                                            |
| `agent/session_log.py`                               | Append-only event log; `SessionLog.branches` tracks subagent branches; `branch_event(id)` returns the BRANCH_START event for a branch                         |
| `agent/wtf.py`, `agent/wtf_report.py`                | Atomic `/wtf` orchestration and strict report parser                                                                                                           |
| `agent/expression_assets.py`                         | Strict VAD/process-state manifest loaders, safe-path validation, hysteresis resolution, and universal text fallback                                            |
| `agent/process_state.py`                             | Process state snapshot + controller with duplicate-snapshot suppression and explicit idle/thinking/tool/pause/error transitions                                |
| `agent/tools.py`, `agent/subagent_tools.py`          | Main/subagent registry construction, including mandatory and inherited `write_handoff`                                                                          |
| `tools/subagent_api.py`                              | **Public API** — spawn/compact/inherited dispatch, branch metadata, handoff and fork-context lifecycle                                                        |
| `tools/_subagent_runner.py`                          | Private pipe-based subprocess spawner; returns raw dicts; wrapped exclusively by `subagent_api.py`                                                             |
| `tools/subagent_main.py`                             | Forked compact/inherited child entry points, credentials, allowlists, retries, and final handoff validation                                                   |
| `tui/app.py`, `tui/commands.py`, `tui/callbacks.py`  | TUI lifecycle, slash commands including `/wtf`, StreamPreview, and callbacks bridge                                                                           |
| `pyside_gui/app.py`                                  | `DagiMainWindow` — main window: splitter layout, agent on daemon thread, streaming dedup, pause/resume, slash commands, overlays (500-line cap)                  |
| `pyside_gui/bridge.py`                               | `AgentBridge(QObject)` — translates `AgentCallbacks` → Qt Signals; `build_callbacks()` returns wired callbacks for thread-safe UI; owns `_stream_text` accumulator |
| `pyside_gui/commands.py`                             | `SlashCommandHandler` — GUI slash-command dispatch, skill/workflow map loading, definition-list formatted output                                                 |
| `pyside_gui/conversation.py` + `resources/`          | `ConversationView(QWebEngineView)` — 13 Python→JS methods; Catppuccin Mocha HTML/CSS/JS template with streaming bubble support                                  |

## Errors Log (recent)

- **2026-08-23**: Task 5 review found falsey malformed `affect:` blocks were masked as defaults and main sessions never bound an affect controller → validate present block shape before defaults and bind a fallback-capable controller before normal registry construction.
- **2026-08-22**: `/wd` did not switch model when project `.dagi/config.yaml` sets a different `default_model` → `_cmd_wd` was passing `self._model_id` to `resolve_model_config`, pinning the old model; fix: pass `None` so the project default wins.
- **2026-08-20**: Main handoffs used filtered output, ambiguous failure state, and raw thread prefixes → defer full `on_done` Markdown only after confirmed termination and use a reserved, hashed filename.
- **2026-08-21**: `test_discover_subagent_tools` and `test_subagent_configs` still fail on `dagi/subagent-simplification` branch because `plan`/`cli` deletions (Tasks 1-2) weren't reflected in those tests — pre-existing, not caused by Task 4.
- **2026-08-22**: PySide6 6.11.2 on Python 3.14 in `dagi` conda env fails DLL load unless `os.add_dll_directory(pyside6_dir)` is called before import — Qt DLLs not on PATH via conda activation; `__main__.py` must bootstrap this before any PySide6 import.
- **2026-08-22**: pyside_gui final-review: XSS in fence lang (escape before `class=` interpolation); timeout=0 deadlock (`0.0 or None = None` → explicit `if timeout <= 0` branch); `_messages` race between main+worker threads (snapshot via `list()` before passing to `CopyPicker`).
- **2026-08-22**: pyside_gui streaming showed `<<END_OF_RESPONSE>>` + duplicate assistant/reasoning bubbles → strip `_LOOP_SENTINELS` in `_on_stream_ended`; gate `_on_assistant_text` and `_on_reasoning` behind `_stream_had_content` flag.
- **2026-08-22**: `_parse_frontmatter` captured literal `>-` instead of parsing YAML block scalars → added indented-continuation-line collection for `>-`/`|-`/`>`/`|` indicators in both `agent/skills.py` and `agent/workflows.py`.
- **2026-08-23**: `--basetemp .pytest-tmp` makes git-sensitive tmp_path tests inherit the repo parent → use an out-of-repo basetemp for `test_plan_mode_branch.py`.
- **2026-08-22**: `pytest` temp fixtures under `C:\Users\alexr\AppData\Local\Temp\pytest-of-alexr` can fail with `PermissionError` in this workspace → pass `--basetemp .pytest-tmp` except for git-sensitive tests.

## Notes & Terms

- **AGENTS.md** is force-injected into every session's system prompt by `_assemble_system_string()`; the file is re-read from disk on every `AgentLoop.__init__` and `_messages[0]` is always overwritten — so AGENTS.md edits made during task N are live in task N+1's context window.
- **`<<END_OF_RESPONSE>>`**: primary exit sentinel (substring check on LLM text responses only); `_escape_sentinels()` rewrites it to `< <END_OF_RESPONSE>>` in tool results before they enter `_messages` to prevent LLM echo-back.
- **Handoff termination**: Main calls save `.dagi/handoffs/main_<thread-hash12>.md` and display full Markdown; child calls use assigned paths; only a `write_handoff` result can trigger `<<HANDOFF_WRITTEN>>` termination.
- **`tools:` allowlist** (`config.yaml`): post-registration filtering strips unnamed tools except mandatory `write_handoff`; `adjust_affect` survives only when explicitly named.
- **Windows / conda**: `EditTool`/`WriteTool` always write LF, normalize `oldText`/`newText` for CRLF safety. Use `conda run -n dagi python` for DAGI scripts; for Claude Code hooks use `envs/dagi/python.exe` directly — `conda run` drops stdin in hook context.
- **`subagent_api` vs `_subagent_runner`**: `tools/subagent_api.py` is the public API (preset resolution, envelope, `SubagentResult`); `tools/_subagent_runner.py` is the private subprocess spawner. Never import `_subagent_runner` directly from outside `subagent_api.py`.
- **Inherited fork v2**: `ParentContextProvider` preserves the exact request prefix; children reuse its `write_handoff` schema as their final action, and every other tool call remains allowlist-enforced.
- **PySide6 DLL bootstrap**: On Windows + conda, `os.add_dll_directory` must be called for the PySide6 package dir before any `from PySide6.*` import; `python -m pyside_gui` will crash without it.
- **PySide6 cross-thread UI calls**: Never call Qt widget methods directly from a background thread; use `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` for non-signal paths, or route through `AgentBridge` signals (auto-queued when connected across threads).
- **PySide6 streaming dedup**: After streaming, `AgentLoop` fires `on_reasoning` and `on_assistant_text` with the same content already shown via deltas — `app.py` gates both behind `_stream_had_content` (set in `_on_stream_ended`, cleared only in `_on_assistant_text`).
- **Expression manifests**: `.dagi/emotes/vad/manifest.yaml` stores `emotes: [{id, file, vad}]`; `.dagi/emotes/states/manifest.yaml` stores `states: {key: file}` with required `idle`, `thinking`, and `tool`.
- **Affect restore logs**: `affect_init` owns the baseline; history restore reuses its baseline with the latest valid `affect_*` current/emote snapshot and emits at most one warning for malformed records.
- **Process-state dedupe**: `ProcessStateController` resolves the requested state every call, but only publishes when the new `(state, asset)` snapshot differs from the stored one.

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
- `_parse_frontmatter` duplicated between `agent/skills.py` and `agent/workflows.py` — both now handle block scalars but should be deduplicated into a shared module.
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
