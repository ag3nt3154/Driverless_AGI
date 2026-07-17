# AGENTS.md

> Last updated: 2026-07-18 | [README](README.md) | [TODO](TODO.md)

---

## Overview

Driverless AGI (dagi) is a self-hosted, OpenAI-compatible agentic coding assistant built entirely in Python. It runs a Plan→Act→Observe loop calling tools (read, write, edit, bash, grep, web search, etc.) until a task is complete, surfacing results via a Textual TUI (`tui.py`), Telegram bot (`telegram_bot.py`), or one-shot `main.py`. Goal: a minimal but production-capable autonomous coding agent that survives long tasks via context compaction, accumulates persistent knowledge via a wiki memory system, spawns specialist subagents for research/planning, and self-improves over time via the GNHF feedback loop. Non-goals: cloud hosting, multi-user auth, UI beyond terminal/Telegram. See [README](README.md) for setup and usage.

## Rules

- Run all Python scripts and package installs via `conda run -n dagi ...` — this project's dependencies live in the `dagi` conda env.
- Never invoke `benchmarks/dagi_eval` (or anything else that drives `AgentLoop` against a real model) without explicit user authorization for the LLM spend — `--solver` defaults to `"agent"`, always pass `naive`/`gold` unless authorized.
- DAGI never merges, switches off, or deletes its own `dagi/*` task branch — that step is always left to the user.
- `git_add`/`git_commit`/`git_reset` tools only operate on `dagi/*` branches (`_dagi_branch_guard`); raw `git` via `BashTool` is not restricted by this guard.
- Always update `README.md`, `TODO.md`, and this file (`AGENTS.md`) after completing a task.

## Process Flow

1. User calls `tui.py` (TUI), `telegram_bot.py` (Telegram), or `main.py` (one-shot) with a task string
2. `resolve_model_config()` reads `config.yaml`, resolves API key, builds `AgentConfig`
3. `AgentLoop.__init__()` loads skills, builds `ToolRegistry`, constructs system prompt
4. `AgentLoop.run(task)` enters `while True` loop:
   - Checks `_pause_event` at top of each iteration — blocks if user pressed ESC (TUI only)
   - Calls the LLM with current `_messages`
   - If tool calls present → dispatch each tool, append results, loop again
   - If no tool calls → check response for termination flags (`<<END_OF_RESPONSE>>` exits cleanly, `<<TASK_END>>` is a legacy alias, neither → inject continue prompt up to `max_continuations`)
5. Context compaction triggers mid-loop if token count exceeds threshold
6. Session ends; `SessionTracker.finish()` writes summary to `.dagi/logs/`

## Architecture

```
tui.py / telegram_bot.py / main.py ← entry points (TUI | Telegram | one-shot)
    │
    tui.py → tui/ package: app.py (lifecycle), commands.py (slash commands),
              callbacks.py (build_callbacks), conversation.py, sidebar.py,
              prompt_input.py
    │
    └── AgentLoop (agent/loop.py)
            ├── ToolRegistry (agent/registry.py)
            ├── SessionTracker (agent/session.py) — logs turns to JSONL
            ├── CompactTool (tools/compact.py) — Pi-style context compaction
            ├── SkillLoader (.dagi/skills/)
            └── AgentCallbacks — rendering hooks (TUI/CLI)
```

**Config:** `config.yaml` → `agent/config_loader.py` → `AgentConfig`
**Memory:** `dagi-memory/{raw,wiki,sources}/`; retrieval via `memory-query` subagent (grep + wiki traversal), writing via `memory-add` subagent. Wiki index auto-injected at session start.
**Subagents:** Pipe-based subprocess spawning (`tools/_subagent_runner.py`), each type declares its own `tools:` list in `.dagi/subagents/<type>/subagent_config.yaml`. Stdout (newline-delimited JSON) relayed to TUI with `[subagent-type]` prefix.
**TUI rendering bridge:** `AgentCallbacks` fire on agent thread → `App.call_from_thread()` → Textual main loop.

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, `AgentConfig`, `AgentCallbacks`, termination flags, system-prompt assembly (`_assemble_system_string`), live Plan Status board rendering |
| `agent/config_loader.py` | Reads `config.yaml`, resolves API key, merges per-project `.dagi/config.yaml` over root |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; `build_subagent_registry()` |
| `agent/__init__.py` | `DAGI_ROOT` — the single canonical root definition |
| `tools/_subagent_runner.py` | Pipe-based subagent runner (`run_subagent()`/`resume_subagent()`) |
| `tools/git.py` | 8 git tools; `_dagi_branch_guard()` restricts add/commit/reset to `dagi/*` branches |
| `tools/output_filter.py` | `filter_tool_output()` — truncates large tool results before LLM context entry |
| `tools/compact.py` | Pi-style context compaction |
| `tui/app.py` | `DagiApp` — lifecycle, dispatch, callbacks wiring |
| `tui/commands.py` | `SlashCommandsMixin` — all `_cmd_*` slash command handlers |
| `tui/notifications.py` | Best-effort native Windows toast (`win11toast`, silent no-op elsewhere) |
| `tg/bot.py`, `tg/session.py` | Telegram bot + per-chat session state |
| `scheduler/runner.py` | `python -m scheduler.runner` — runs due scheduled tasks via `AgentLoop` |
| `benchmarks/dagi_eval/` | Coding-speedup + DS scorecard harness; `--solver` defaults to `"agent"` — **never invoke without an explicit `--solver naive`/`gold` flag unless the user has authorized a real LLM call** |
| `tools/_pdf_convert.py` | `parse_page_spec`, `select_pages` (pure, no deps) + `is_scanned_pdf` (pymupdf probe; optional dep) |
| `archives/cli.py` | Archived Rich REPL — dead code since 2026-07-12, not imported anywhere |
| `.dagi/agents.md` | Behavioral guidelines loaded every session (coding standards, memory protocol) — separate from this file |

## Errors Log

- **2026-07-16**: `ReadTool` returned bare joined lines with no line numbers, forcing `bash`/`cat -n` fallback to locate lines → `read.py` now emits `cat -n` style `{lineno:6d}\t{line}` output.
- **2026-07-14**: `/wd` didn't refresh sidebar model on project switch → added `model_id` to `AgentConfig`, `_cmd_wd` now refreshes sidebar and detects model changes.
- **2026-07-14**: `X[c].dtype == object` misclassified pandas 3.0.3 string columns, crashed `SimpleImputer` → switched to `pd.api.types.is_numeric_dtype(X[c])`.
- **2026-07-14**: dagi_eval generator produced below-target oracle/baseline AUC (signal invisible to non-interacting baseline) → raised `NOISE_SCALE` to 2.0, added `MAIN_COEFS` linear term.
- **2026-07-14**: git-bash `cd` fails on Windows-backslash paths; bare `conda` not on PATH → use forward-slash paths and full `conda.exe` path in this shell.
- **2026-07-12**: git toolkit expanded 3→8 tools; `git_rollback` removed with no replacement — use `git_reset`+`git_checkout` on `dagi/*` branches.
- **2026-07-12**: plan-work-review now commits per-subtask instead of once at plan end; DAGI never merges/deletes the `dagi/*` branch.
- **2026-07-12**: README architecture tree was stale (old 3-tool git set) → updated to all 8 tools + `dagi/*` guard note.
- **2026-07-12**: `shift+enter` unreliable in Windows Terminal (same bytes as `enter`) → added `ctrl+n`/`ctrl+enter` as newline aliases in `PromptInput`.
- **2026-07-12**: compose mode (`ctrl+o`) had 5 edge-case bugs (toggle mid-run, spinner state, blank-enter collapse, no visual feedback) → guarded and fixed all 5.

## Notes & Terms

- **END_OF_RESPONSE / `<<END_OF_RESPONSE>>`**: Primary exit sentinel, checked before the legacy `<<TASK_END>>` alias; can appear anywhere in the response (substring check).
- **continuation**: Harness injecting a `"continue"` message when the agent stops without a termination flag.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds budget; preserves system prompt and recent tail. `_compact_context()` catches all exceptions — a failed compaction never crashes the session.
- **tier**: One of `default`/`worker`/`plan` — three model slots in `config.yaml`, switched via `switch_model`. `provider_order` is per-model, read from the catalog entry.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow, notes at `.dagi/gnhf/notes.md`.
- **memory-query / memory-add subagents**: grep + wiki-index traversal for retrieval; classify+write 5-field frontmatter nodes for writing. Both take a single `task` parameter — any other name produces an empty task string.
- **`dagi/*` branch**: naming convention for branches auto-created on `enter_plan_mode`; the only prefix on which `git_add`/`git_commit`/`git_reset` are permitted. `_dagi_branch_guard()` only covers the dedicated git tools — raw `git` via `BashTool` bypasses it entirely (a nudge, not a security boundary).
- **scheduler**: `scheduler/` package; tasks in `.dagi/scheduler/schedule.yaml` (interval in **seconds**, min 60); runner sets `plan_mode_initiated_by="dagi"` and `ask_user_timeout=60`.
- **tool output filter**: `filter_tool_output()` — LLM sees a truncated preview + file pointer; JSONL logs keep the full result.
- **`api_key` vs `api_key_env`**: direct `api_key` in config.yaml overrides env var; empty string still falls through to env var.
- **`supports_pause`**: gates error-pause behavior on `AgentCallbacks`, defaults `False`; TUI sets `True` explicitly (checking `on_pause is not lambda` would be fragile).
- **TUI thread safety**: `AgentLoop` runs on a daemon thread; all widget mutations go through `App.call_from_thread()`. Sidebar uses plain instance attributes + `self.refresh()`, not Textual `reactive` (dict-content equality checks miss updates).
- **`pyproject.toml` is incomplete**: `typer`, `rich`, `textual` are missing from declared deps — `pip install -e .` fails on a clean env for CLI/TUI use.
- **Escalation is a sidecar file, not live IPC**: `EscalateIssueTool` writes `<handoff-stem>_escalation.md`; `_subagent_runner.py`'s existing 2s poll loop picks it up. Resolving an escalation does not consume a retry attempt — only a completed FAIL verdict does.
- **`__list__:` encoding**: non-string tool results are encoded as `"__list__:" + json.dumps(result)` in JSONL/callbacks — downstream consumers must know this prefix.
- **Windows CRLF**: `EditTool`/`WriteTool` always write LF on disk (`newline="\n"`) and normalize `oldText`/`newText` before matching — prevents Windows' default `\n`→`\r\n` translation from corrupting files or doubling to `\r\r\n`.
- **Harbor dual filesystem**: file tools operate on the Windows host; only `harbor_bash` routes into the Docker container.
- **`read` tool output format**: `cat -n` style — each line prefixed `{1-indexed lineno:6d}\t{content}`; the line number is not part of the file and must be stripped before use as `oldText` in `edit`.
- **`read` tool document support**: `.docx`/`.xlsx`/`.pptx` are converted to markdown in memory via the optional `markitdown` dependency (`tools/read.py::_convert_document`), then fed through the same `cat -n` numbering/offset/limit path as text files. `markitdown` is not a hard dependency — missing/failed conversion returns a friendly `"Error: Could not convert '<name>': ..."` string, never a traceback. PDF was deliberately deferred (weaker table fidelity, no OCR in markitdown's PDF backend) — see `TODO.md`.
- **PDF page-range helpers**: `tools/_pdf_convert.py` provides `parse_page_spec("1-3,5,8-10") → set[int]`, `select_pages(markdown, spec) → str` (filters by `<!-- Page N -->` markers), and `is_scanned_pdf(path, sample_pages=3) → bool` (probes first N pages via pymupdf; returns `False` gracefully if `fitz` absent). Threshold: `_SCANNED_CHAR_THRESHOLD = 50` chars across sampled pages. All TDD-tested (13 tests); pure helpers have no optional deps.

---

## User Insights

> Independent observations — not highlighted by the user. Be specific and honest.

### User Tendencies

- Ships incrementally and tests at each step; does not batch large refactors.
- Invests in structural cleanup once a module exceeds ~800 lines, organizational only, behavior preserved.
- Works directly on `main` rather than feature branches; prefers "merge locally" over "push + PR" for solo-authored work.
- Prefers explicit, non-magical configuration and pause-and-resume semantics over cancel-and-restart.
- Prefers behavioral unification over micro-optimization — accepted an extra LLM round-trip to eliminate divergent code paths.
- Follows strict TDD for infrastructure work and engages deeply in adversarial design grilling before implementation.
- Comfortable delegating a whole multi-task feature to autonomous subagents without check-ins.
- Draws a hard, repeated line around real LLM API spend — never run dagi with real LLM calls without explicit permission.
- Review velocity outpaces fix velocity — GNHF self-review loop dormant 80+ days despite 240+ unanalysed session logs.

### Project Shortcomings

- `BashTool` is unsandboxed and can run raw `git` commands that bypass the `dagi/*` branch guard entirely.
- No pause during subagent execution — ESC pauses the parent loop but child subprocesses continue unaffected.
- Base64 image data inflates compaction prompts and `session_end` JSONL records with raw base64 noise.
- Session cost tracking is almost always blank — most providers don't populate `usage.cost`.
- `/hist` in TUI is broken — writes to a `rich.Console` behind Textual's canvas instead of `ConversationPane`.
- No integration tests — all tests use mocked LLM clients.
- DAGI Eval Benchmark has never been run with `--solver agent` against a real model.
- `_parse_frontmatter` is duplicated verbatim between `agent/skills.py` and `agent/workflows.py`.

### Potential Areas of Exploration

- Fix `/hist` and add cache-hit visibility (`usage.prompt_tokens_details.cached_tokens`) in the sidebar.
- Session replay / dry-run mode — JSONL logs already have everything needed for deterministic replay.
- Parallel subagent dispatch — no architectural change needed, `spawn_*` already supports concurrent calls.
- Bootstrap a real GNHF self-review run against the 240+ accumulated session logs.
- Run a full Terminal-bench 2 / Harbor benchmark pass — currently smoke-tested only (1 task).
