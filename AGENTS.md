# AGENTS.md

> Last updated: 2026-08-02 | [README](README.md) | [TODO](TODO.md)

---

## Overview

Driverless AGI (dagi) is a self-hosted Python agentic coding assistant: Plan→Act→Observe loop with tools (read, write, edit, bash, grep, web search), surfaced via Textual TUI, Telegram bot, or one-shot CLI. Survives long tasks via context compaction, accumulates knowledge via a wiki memory system, spawns specialist subagents, and self-improves via GNHF. Non-goals: cloud hosting, multi-user auth, UI beyond terminal/Telegram.

## Rules

- Use `conda run -n dagi ...` for all Python scripts and package installs.
- Never invoke `benchmarks/dagi_eval` against a real model without explicit authorization — `--solver` defaults to `"agent"`, always pass `naive`/`gold` unless authorized.
- DAGI never merges, switches off, or deletes its own `dagi/*` task branch — the user handles that.
- Always update `README.md`, `TODO.md`, and `AGENTS.md` after completing a task.

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
- [ ] State ownership and consistency clear?
- [ ] Feedback / observability in place?
- [ ] Blast radius understood?
- [ ] Timing and ordering safe?
- [ ] Follows existing patterns (or intentionally breaks them)?
- [ ] Security / obvious risks addressed?

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

**Tool layout:** `tools/<name>/__init__.py` re-exports from `_<name>.py`; shared helpers are flat files in `tools/` (`_path_guard.py`, `_hash_cache.py`, `_subagent_runner.py`, `_handoff_format.py`, `_task_envelope.py`, `output_filter.py`, `subagent_main.py`). `edit` uses `oldText`/`newText` unique-substring matching; `read` outputs `cat -n` style line numbers.

**Subagents:** Pipe-based subprocesses, each type declares `tools:` in `.dagi/subagents/<type>/subagent_config.yaml`. WriteHandoffTool auto-injected when `handoff_path` is set — calling it writes the report and triggers immediate return via `<<HANDOFF_WRITTEN>>` sentinel. If missing at exit, `_ensure_handoff()` re-enters with a corrective prompt; last-resort scrape drops `<stem>_unverified.flag`. All spawn tools render `ok_unverified` as a warning banner. Every subagent task is wrapped by `_task_envelope.py` (`## Task` / `## Instructions` / `## Output`), with parent-supplied `briefing` and `handoff_spec`.

## Key Files

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, system-prompt assembly, termination/compaction, WriteHandoff sentinel dispatch |
| `agent/config_loader.py` | Reads `config.yaml`, merges `.dagi/config.yaml`, resolves API key, services, Telegram config |
| `tools/read/` | `ReadTool` — text inline (`cat -n` style), docs delegated to doc-converter service over HTTP |
| `tools/edit/` | `EditTool` — `oldText`/`newText` unique-substring replacement, CRLF-safe |
| `tools/grep/`, `tools/find/` | Regex search (`file:line: content` format), glob file finding |
| `tools/bash/` | Unsandboxed shell execution — all git operations run through here |
| `tools/_subagent_runner.py` | Pipe-based `run_subagent()`/`resume_subagent()` with unverified-flag detection |
| `tools/_handoff_format.py` | Shared handoff rendering and status dispatch for all 5 subagent-spawning tools |
| `tools/_task_envelope.py` | Universal `briefing`/`handoff_spec` envelope for subagent tasks |
| `tools/output_filter.py` | Truncates tool results; full output stored in content-addressed cache |
| `tools/_document_reader.py` | Long-document summarization via `document-reader` subagent with cache |
| `services/doc_converter/` | Standalone FastAPI service (port 8100); PDF→markdown via docling/ocrmypdf, Office→markdown via markitdown; own conda env |
| `agent/subagent_tools.py` | Subagent registry construction; auto-injects WriteHandoffTool + EscalateIssueTool |
| `agent/tools.py` | Wires all tools into `ToolRegistry` |
| `tui/app.py`, `tui/streaming.py`, `tui/callbacks.py` | TUI lifecycle, StreamPreview expand/collapse, callbacks bridge |
| `tg/bot.py`, `tg/session.py` | Telegram bot with per-chat sessions and `allowed_chat_ids` gate |
| `benchmarks/dagi_eval/` | Coding + DS scorecard; `--solver` defaults to `"agent"` — **never invoke without `naive`/`gold` unless authorized** |
| `archives/cli.py` | Archived Rich REPL — dead code since 2026-07-12 |

## Errors Log (recent)

- **2026-07-25**: `ReadTool` rewrite to call doc-converter service broke test collection → fixed by mocking `convert_document` in tests and removing dead `PdfConfig`.
- **2026-07-26**: TUI displayed wrong model name — `get_model_display_name()` only read root config, missed `.dagi/config.yaml` overrides → TUI now resolves via `resolve_model_config()`.
- **2026-07-26**: Subagent handoff enforcement — write_handoff auto-injection, sentinel detection, corrective re-entry, and unverified-flag scraping added.
- **2026-07-26**: Post-merge cleanup — duplicated dispatch logic across 5 spawn tools centralized into `dispatch_status_result()`; `unverified_flag_path()` shared; `_handle_write_handoff` refactored to share `_bookkeep_tool_call()`/`_finalize_turn()`.
- **2026-07-26**: Typed subagent spawn tools absent from runtime registry → `tools:` allowlist in `.dagi/config.yaml` filtered them out post-registration; added all 7 typed spawner names to the list.
- **2026-07-26 (known, deferred)**: `agent/loop.py` is 1172 lines (cap: 500), `AgentLoop.run` CC is 48 (cap: 8) — spun off as standalone refactor task.
- **2026-07-27**: Hashline experiment reverted — smaller models made too many errors copying opaque `LINE#HASH` anchors → restored `oldText`/`newText` edit, `cat -n` read, plain `file:line:` grep. `_hashline.py`, `edit_text/` tool, and hashline tests removed.

## Notes & Terms

- **AGENTS.md** is force-injected into every session's system prompt by `_assemble_system_string()`.
- **`<<END_OF_RESPONSE>>`**: primary exit sentinel (substring check anywhere in response).
- **Document conversion**: `.pdf/.docx/.xlsx/.pptx` → doc-converter service at `AgentConfig.services["doc_converter"]`, hard-fail if unreachable. PDF page selection via `pages` parameter.
- **Subagent handoff**: WriteHandoffTool auto-injected, `<<HANDOFF_WRITTEN>>` sentinel triggers immediate return. Missing handoff → corrective re-entry → last-resort scrape + `_unverified.flag`.
- **Skill chain**: `grilling` → `plan` → `to-spec` → `dagi-execute` (write-tests/worker/review cycle, 2-attempt retry, escalation sidecar).
- **Memory wiki**: `G:\My Drive\black_grimoire\dagi-memory\wiki\` (Claude Code skills) vs. repo-local `dagi-memory/wiki/` (DAGI's own subagents). Two separate systems.
- **`tools:` allowlist** (`config.yaml`): post-registration filter via `reg.filter_to(config.tools)`. Any tool not named here is silently stripped — including auto-discovered spawn tools. When adding a new subagent type, also add its `spawn_{type}_subagent` name to the list.
- **Windows**: `EditTool`/`WriteTool` always write LF, normalize `oldText`/`newText` for CRLF safety. Use `conda run -n dagi python` not bare `python.exe`.
- **TUI**: `StreamPreview` expands on first delta, collapses on `on_stream_end`. `on_emote` callback is `(name: str, display: str)` — name rendered as dim label beneath art in sidebar. `_model_name` derived from resolved config. Layout is horizontal 65/35: `#main-column` (Vertical, 65%) holds chat + prompt on the left; `Sidebar` (35%) is a right panel with sections stacked vertically (status → tokens → plan).
- **dagi_eval caveats**: `--timeout-min` only bounds agent loop, not scoring phases. Relative `task_dir` silently breaks scoring — always use `harness.TASKS_DIR`.

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
- GNHF self-review dormant 85+ days despite 259 unanalysed sessions.

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
