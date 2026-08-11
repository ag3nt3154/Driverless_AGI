# AGENTS.md

> Last updated: 2026-08-11 | [README](README.md) | [TODO](TODO.md)


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
tui.py / telegram_bot.py / main.py
    │
    tui.py → tui/ (app, commands, callbacks, conversation, sidebar, prompt_input, streaming)
    │
    └── AgentLoop (agent/loop.py)
            ├── ToolRegistry (agent/registry.py)
            ├── SessionTracker (agent/session.py)
            ├── CompactTool (tools/compact.py)
            ├── SkillLoader (.dagi/skills/)
            └── AgentCallbacks → TUI via App.call_from_thread()
```

**Tool layout:** `tools/<name>/__init__.py` re-exports from `_<name>.py`; shared helpers are flat files in `tools/` (`_path_guard.py`, `_hash_cache.py`, `_subagent_runner.py`, `_handoff_format.py`, `_task_envelope.py`, `output_filter.py`, `subagent_main.py`, `subagent_api.py`). `edit` uses `oldText`/`newText` unique-substring matching; `read` outputs `cat -n` style line numbers.

**Subagents:** Pipe-based subprocesses. Public API: `run_subagent()` / `SubagentResult` / `resume_subagent_by_pid()` in `tools/subagent_api.py` (never import `_subagent_runner` directly). Each type is a self-contained package: `.dagi/subagents/<type>/main.py` exports a `BaseTool` subclass; `_discover_subagent_tools()` in `agent/subagent_tools.py` discovers types by import (scans DAGI root then `cwd/.dagi/subagents/`; project types override built-ins by name). 10 built-in types: `explore_files`, `web_research`, `memory-query`, `memory-add`, `memory-refresh`, `long-reader`, `plan`, `cli`, `worker`, `review`. `subagent_config.yaml` schema: `tools`, `model_tier`, `default_handoff_spec`, `agents_md` (new — path to AGENTS.md injected into subagent system prompt; replaces the old hardcoded dict). WriteHandoffTool auto-injected when `handoff_path` is set — calling it writes the report and triggers immediate return via `<<HANDOFF_WRITTEN>>` sentinel. If missing at exit, `_ensure_handoff()` re-enters with a corrective prompt; last-resort scrape drops `<stem>_unverified.flag`. All spawn tools render `ok_unverified` as a warning banner. Every subagent task is wrapped by `_task_envelope.py` (`## Task` / `## Instructions` / `## Output`), with parent-supplied `briefing` and `handoff_spec`. Custom one-off subagent workflows are authored as DAGI scripts calling `run_subagent()` directly (see `.dagi/skills/run_subagent/SKILL.md`).

## Key Files


| Path                                                 | Purpose                                                                                                                                                        |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent/loop.py`                                      | Core agent loop, system-prompt assembly, termination/compaction, WriteHandoff sentinel dispatch                                                                |
| `agent/config_loader.py`                             | Reads`config.yaml`, merges `.dagi/config.yaml`, resolves API key, services, Telegram config                                                                    |
| `tools/subagent_api.py`                              | **Public API** — `run_subagent()` / `SubagentResult` / `resume_subagent_by_pid()`; only import point for subagent execution                                   |
| `tools/_subagent_runner.py`                          | Private pipe-based subprocess spawner; returns raw dicts; wrapped exclusively by`subagent_api.py`                                                              |
| `tools/_handoff_format.py`                           | Shared handoff rendering and status dispatch for all 5 subagent-spawning tools                                                                                 |
| `tools/_task_envelope.py`                            | Universal`briefing`/`handoff_spec` envelope for subagent tasks                                                                                                 |
| `tools/output_filter.py`                             | Truncates tool results; full output stored in content-addressed cache                                                                                          |
| `services/doc_converter/`                            | Standalone FastAPI service (port 8100); PDF→markdown via docling/ocrmypdf, Office→markdown via markitdown; own conda env                                     |
| `agent/subagent_tools.py`                            | `_discover_subagent_tools()` import-based discovery; `build_subagent_registry()` with `tool_names_override`; auto-injects WriteHandoffTool + EscalateIssueTool |
| `tui/app.py`, `tui/streaming.py`, `tui/callbacks.py` | TUI lifecycle, StreamPreview expand/collapse, callbacks bridge                                                                                                 |
| `tg/bot.py`, `tg/session.py`                         | Telegram bot with per-chat sessions and`allowed_chat_ids` gate                                                                                                 |
| `benchmarks/dagi_eval/`                              | Coding + DS scorecard;`--solver` defaults to `"agent"` — **never invoke without `naive`/`gold` unless authorized**                                            |
| `tools/read/_long_reader.py`                         | Long-file summarization via`long-reader` subagent; caches digest by SHA-256 of full text                                                                       |
| `.dagi/skills/memory-add/SKILL.md`                   | Canonical memory-add protocol (parent passes category+metadata; subagent routes)                                                                               |
| `.dagi/skills/memory-query/SKILL.md`                 | Canonical memory-query protocol (read-only; scope parameter)                                                                                                   |
| `.dagi/skills/memory-refresh/SKILL.md`               | Canonical memory-refresh protocol (lint sweep + triage); scripts/ has 5 lint scripts                                                                           |

## Errors Log (recent)

- **2026-08-02**: `AgentLoop.__init__` with `initial_messages` discarded the freshly-assembled system string — AGENTS.md updates never propagated to the next task's context window → overwrite `_messages[0]` with fresh `system` after copying `initial_messages`.
- **2026-08-02**: `<<END_OF_RESPONSE>>` in tool results (file read or unverified subagent handoff) caused LLM to echo sentinel on next turn, breaking loop prematurely → `_escape_sentinels()` in `_bookkeep_tool_call` rewrites `<<` to `< <` before storing in `_messages`.
- **2026-08-02**: `<<HANDOFF_WRITTEN>>` embedded in inlined handoff content falsely triggered `_handle_write_handoff` in parent loop → sentinel check now gated on `tc.function.name == "write_handoff"`.
- **2026-07-26**: TUI displayed wrong model name — `get_model_display_name()` only read root config, missed `.dagi/config.yaml` overrides → TUI now resolves via `resolve_model_config()`.
- **2026-07-26 (known, deferred)**: `agent/loop.py` is 1172 lines (cap: 500), `AgentLoop.run` CC is 48 (cap: 8) — spun off as standalone refactor task.
- **2026-08-04**: Subagent refactor merged to main — `tools/subagent_api.py` public API; 9 types each with `main.py` + `subagent_config.yaml`; import-based discovery; `SpawnSubagentTool`/`SpawnCliSubagentTool` deleted; `--tools`/`--model-tier` CLI args; `agents_md` config; `DEFAULT_PYTHON_ENV` in system prompt; `run_subagent` skill; `plan`/`cli` configs fixed (were missing, caused `FileNotFoundError` on preset load).
- **2026-07-27**: Hashline experiment reverted — smaller models made too many errors copying opaque `LINE#HASH` anchors → restored `oldText`/`newText` edit, `cat -n` read, plain `file:line:` grep. `_hashline.py`, `edit_text/` tool, and hashline tests removed.
- **2026-08-07**: DeepSeek thinking-mode rejected multi-tool-call batches — (1) `model_extra` fallback in `_consume_stream` / `_extract_reasoning` only checked `"reasoning"` key, missing DeepSeek's `"reasoning_content"` key; (2) interleaved format split tool_calls across multiple assistant messages, only the first carrying `reasoning_content` → fixed both key lookups; restructured to emit one assistant message with all tool_calls before the dispatch loop (standard OpenAI format).
- **2026-08-08**: DeepSeek rejected orphaned tool messages — two causes: (1) compaction safe-cut logic could split multi-tool-call groups, leaving tool-result messages without their parent assistant → safe cuts now skip positions where the tail would start with a tool message; (2) `RELOAD_SKILLS_SENTINEL` injected a system message between assistant+tool_calls and tool results → deferred system messages until after all tool results are appended.
- **2026-08-10**: `conda run` drops stdin when used in Claude Code hook context — `json.load(sys.stdin)` always gets empty input → use `C:/Users/alexr/miniconda3/envs/dagi/python.exe` directly for hook scripts instead of `conda run -n dagi python`.
- **2026-08-11**: Grep Python fallback (no ripgrep) had no timeout — `rglob("*")` over Google Drive mount (`memory_root`) hung indefinitely, freezing TUI spinner → added 15s wall-clock timeout to both enumeration and file-scanning phases; installed `ripgrep` via conda.

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
- **Subagent discovery**: `_discover_subagent_tools()` scans `_DAGI_ROOT/.dagi/subagents/` then `cwd/.dagi/subagents/`; imports each `main.py` and instantiates the exported `BaseTool` subclass. Project types with the same name override built-in types.

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
