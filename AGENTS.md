# AGENTS.md

> Last updated: 2026-07-26 | [README](README.md) | [TODO](TODO.md)

---

## Overview

Driverless AGI (dagi) is a self-hosted, OpenAI-compatible agentic coding assistant built entirely in Python. It runs a Plan→Act→Observe loop calling tools (read, write, edit, bash, grep, web search, etc.) until a task is complete, surfacing results via a Textual TUI (`tui.py`), Telegram bot (`telegram_bot.py`), or one-shot `main.py`. Goal: a minimal but production-capable autonomous coding agent that survives long tasks via context compaction, accumulates persistent knowledge via a wiki memory system, spawns specialist subagents for research/planning, and self-improves over time via the GNHF feedback loop. Non-goals: cloud hosting, multi-user auth, UI beyond terminal/Telegram. See [README](README.md) for setup and usage.

## Rules

- Run all Python scripts and package installs via `conda run -n dagi ...` — this project's dependencies live in the `dagi` conda env.
- Never invoke `benchmarks/dagi_eval` (or anything else that drives `AgentLoop` against a real model) without explicit user authorization for the LLM spend — `--solver` defaults to `"agent"`, always pass `naive`/`gold` unless authorized.
- DAGI never merges, switches off, or deletes its own `dagi/*` task branch — that step is always left to the user.
- `git_add`/`git_commit`/`git_reset` tools only operate on `dagi/*` branches (`_dagi_branch_guard`); raw `git` via `BashTool` is not restricted by this guard.
- Always update `README.md`, `TODO.md`, and this file (`AGENTS.md`) after completing a task.

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

**Tool layout convention (as of 2026-07-25):** every tool lives in its own `tools/<name>/` subfolder: `tools/<name>/__init__.py` re-exports the public class/symbols (e.g. `from ._<name> import <Name>Tool`), and the implementation lives in `tools/<name>/_<name>.py` (leading underscore = private module, not meant to be imported directly by other packages). Shared cross-tool helpers stay as flat files at the top of `tools/` (`_path_guard.py`, `_hash_cache.py`, `_subagent_runner.py`, `_plan_parser.py`, `output_filter.py`, `subagent_main.py`). New tools should follow this pattern — a bare `tools/<name>.py` file is the old convention and no longer used anywhere in the tree.

**Config:** `config.yaml` → `agent/config_loader.py` → `AgentConfig`
**Memory:** `dagi-memory/{raw,wiki,sources}/`; retrieval via `memory-query` subagent (grep + wiki traversal), writing via `memory-add` subagent. Wiki index auto-injected at session start.
**Subagents:** Pipe-based subprocess spawning (`tools/_subagent_runner.py`), each type declares its own `tools:` list in `.dagi/subagents/<type>/subagent_config.yaml`. Stdout (newline-delimited JSON) relayed to TUI with `[subagent-type]` prefix.
**Subagent handoff contract (enforced, as of 2026-07-26):** Every subagent that has a `handoff_path` (all 7 registered types plus the dynamic `custom`/cli path) is auto-injected with `WriteHandoffTool` (`tools/write_handoff/_write_handoff.py`) in `agent/subagent_tools.py::_tools_from_list()` — regardless of whether `write_handoff` appears in that type's `tools:` list in `subagent_config.yaml`. The destination path is baked in at construction; the model's schema exposes only `content`. Calling it writes the file verbatim and returns a string containing `WRITE_HANDOFF_SENTINEL` (`"<<HANDOFF_WRITTEN>>"`, defined in `agent/loop.py`); `AgentLoop.run()`'s tool-dispatch loop detects the sentinel and calls `_handle_write_handoff()`, which appends the tool-message bookkeeping and returns immediately — no further model turn happens (this is what removes the extra continuation round-trip on the handoff path). If a subagent's turn ends without the file existing, `tools/subagent_main.py::_ensure_handoff()` re-enters `loop.run()` once with a corrective prompt naming `write_handoff` explicitly (`AgentLoop.run` is re-entrant — `_messages` persists on the instance); if the file is still missing after that, it scrapes the last assistant message into the file and drops a sidecar `<stem>_unverified.flag`. `tools/_subagent_runner.py` detects that flag on exit and returns status `"ok_unverified"` instead of `"ok"`. Every tool that can surface a subagent result (`spawn_subagent`, `cli_subagent`, `extend_timeout`, and by extension `explore_files`/`web_research`, which route through the same runner) renders `ok_unverified` as a warning banner followed by the scraped content via the shared `tools/_handoff_format.py::format_handoff_result(handoff_path, unverified=True)` — so the parent can tell a deliberate report from a scrape, never silently confusing the two.
**Parent-authored briefing/handoff_spec envelope:** Every subagent-spawning tool accepts two optional free-text parameters — `briefing` (guidance from the parent: traps to avoid, prior failed-attempt context, extra constraints) and `handoff_spec` (what the parent wants in the report). `tools/_task_envelope.py::wrap_envelope(body, briefing, handoff_spec)` composes the final task text sent to the subagent: the type-specific `body` (worker's plan subtask, review's worker-handoff-path + unit-test-paths, or a generic `## Task` block for everything else, dispatched via the `_BODY_BUILDERS` dict in `tools/spawn_subagent/_spawn_subagent.py::_compose_task()`), then `## Instructions\n{briefing}` (only if `briefing` is truthy), then always `## Output\n{handoff_spec or default}`. Each `.dagi/subagents/<type>/subagent_config.yaml` carries a `default_handoff_spec` used when the parent omits `handoff_spec`; `tools/_task_envelope.py::FALLBACK_HANDOFF_SPEC` is the last-resort default when neither is present. `custom_instructions` was renamed to `briefing` everywhere (no back-compat alias — internal parameter, no external callers).
**TUI rendering bridge:** `AgentCallbacks` fire on agent thread → `App.call_from_thread()` → Textual main loop.

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, `AgentConfig`, `AgentCallbacks`, termination flags, system-prompt assembly (`_assemble_system_string`), live Plan Status board rendering |
| `agent/config_loader.py` | Reads `config.yaml`, resolves API key, merges per-project `.dagi/config.yaml` over root; `_build_config_from_entry()` also reads the `services:` block into `AgentConfig.services: dict[str, str]` (e.g. `{"doc_converter": "http://localhost:8100"}`); `TelegramConfig`/`load_telegram_config()` resolves `telegram.allowed_chat_ids_env` into `allowed_chat_ids: frozenset[int]` — imports flow `tools -> agent.config_loader`, same direction as `tools.read -> agent.base_tool`. `PdfConfig`/`load_pdf_config()` (and the `pdf:`/`docs:` extras blocks) are fully removed as of 2026-07-25 — PDF conversion now lives entirely in the doc-converter service |
| `tools/read/_doc_service.py` | HTTP client (anti-corruption layer) for the doc-converter service: `convert_document(path, service_url, project_path) -> str`, `DocServiceError(code, message)`. Local hash-cache check before upload; SHA-256 of file bytes gates network calls |
| `tools/read/_read.py` | `ReadTool` — text files read inline; `.pdf/.docx/.xlsx/.pptx` delegate to `tools.read._doc_service.convert_document()` over HTTP (service must be running, `service_url` sourced from `AgentConfig.services["doc_converter"]`). No inline markitdown/docling conversion — hard fails with a clear "start the service" error if unreachable, no fallback |
| `services/doc_converter/` | Standalone FastAPI microservice for document conversion, own conda env (`environment.yml`, env name `doc_converter`). Entry point `python -m services.doc_converter` (`__main__.py` → `main.py`, listens on port 8100). `converter/pdf.py` — PDF→markdown (docling digital-native / ocrmypdf+docling scanned, map-reduce parallel path for large PDFs; migrated verbatim from the old `tools/_pdf_convert.py`). `converter/office.py` — docx/xlsx/pptx→markdown via `markitdown`. `converter/cache.py` — server-side content-addressed cache (`.cache/<sha256>.md`), keyed by SHA-256 of uploaded file bytes, shared across all clients |
| `tg/bot.py` | `TelegramBot._is_authorized(chat_id)` gates all 4 handlers against `allowed_chat_ids`; empty allowlist = open (back-compat) but logs a startup warning |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; re-exports `build_subagent_registry()` from `agent/subagent_tools.py` for backwards-compat call sites |
| `agent/subagent_tools.py` | `build_subagent_registry()`/`_tools_from_list()`/`_discover_subagent_tools()` — the actual subagent-registry construction logic (split out of `agent/tools.py`). Auto-injects `WriteHandoffTool` (and `EscalateIssueTool`) whenever `handoff_path is not None`, in both the config-driven and `custom` branches, independent of the type's declared `tools:` list |
| `agent/__init__.py` | `DAGI_ROOT` — the single canonical root definition |
| `tools/write_handoff/_write_handoff.py` | `WriteHandoffTool` — mirrors `EscalateIssueTool`: `handoff_path` baked in at construction (not model-visible), `run(content)` writes verbatim and returns a string containing `WRITE_HANDOFF_SENTINEL` |
| `tools/_task_envelope.py` | `wrap_envelope(body, briefing, handoff_spec)` — universal `## Instructions`/`## Output` envelope appended to every spawned subagent's composed task; `FALLBACK_HANDOFF_SPEC` last-resort default |
| `tools/_handoff_format.py` | `format_handoff_result(handoff_path, unverified=False)` — shared rendering for `spawn_subagent`/`cli_subagent`/`extend_timeout` results: inlines handoff content, prepends a warning banner when `unverified=True` |
| `tools/_subagent_runner.py` | Pipe-based subagent runner (`run_subagent()`/`resume_subagent()`); detects the `<stem>_unverified.flag` sidecar and returns status `"ok_unverified"` instead of `"ok"` |
| `tools/git.py` | 8 git tools; `_dagi_branch_guard()` restricts add/commit/reset to `dagi/*` branches |
| `tools/output_filter.py` | `filter_tool_output()` — truncates large tool results before LLM context entry |
| `tools/compact.py` | Pi-style context compaction |
| `tui/app.py` | `DagiApp` — lifecycle, dispatch, callbacks wiring, `_expand_stream_preview`/`_collapse_stream_preview` orchestration |
| `tui/streaming.py` | `StreamPreview` — live-streaming reasoning/text widget; `expand()`/`finish()` toggle full-window vs. capped (14-row/12-line) display |
| `tui/commands.py` | `SlashCommandsMixin` — all `_cmd_*` slash command handlers |
| `tui/notifications.py` | Best-effort native Windows toast (`win11toast`, silent no-op elsewhere) |
| `tg/bot.py`, `tg/session.py` | Telegram bot + per-chat session state |
| `scheduler/runner.py` | `python -m scheduler.runner` — runs due scheduled tasks via `AgentLoop` |
| `benchmarks/dagi_eval/` | Coding-speedup + DS scorecard harness; `--solver` defaults to `"agent"` — **never invoke without an explicit `--solver naive`/`gold` flag unless the user has authorized a real LLM call**. `config_dagi_eval.yaml` runs on `hy3-free-openrouter` (free tier) with a restricted tool list that includes all predefined subagent types, `spawn_cli_subagent`, `extend_subagent_timeout`, and `switch_model`. Every `run.py` invocation creates one `.dagi/benchmarks/dagi_eval/logs/<ts>_log/` folder (`harness.new_run_dir()`) holding `result.jsonl` (one row per task + a final `__aggregate__` row), `code/<task_name>/` (copy of the scored workspace), and `sessions/<task_name>/` (agent transcripts). Each row always carries `baseline_score`/`golden_score` from the canned naive/gold solutions (scored fresh via `scoring.score_reference()`, no LLM) plus `unified_score` — see Notes & Terms. `logs/claude_code_reference/` holds a manual reference run + per-task `.md` analysis docs. |
| `tests/fixtures/pdf/` | `sample_digital.pdf`/`sample_scanned.pdf` fixtures used by the doc-converter service's own tests and manual smoke tests, generated by `_generate_samples.py` (PyMuPDF: real text + hand-drawn table for digital, rasterized-to-image for scanned — no text layer) |
| `tools/_hash_cache.py` | Shared content-addressed cache (`cache_path()`, `get_or_compute()`) used by `output_filter.py`; layout `.dagi/hash_cache/tool_output/<sha256>.<ext>`, dedup-only (no eviction). No longer used for PDF caching — that moved to the service's own `services/doc_converter/converter/cache.py` |
| `tools/_document_reader.py` | Orchestrates the `document-reader` subagent for long documents: cache-hit fast path (`.dagi/hash_cache/document_summary/<sha256>_summary.md`), cache-miss spawns subagent via `run_subagent()`, returns `None` on failure for caller to fall back to truncation |
| `tests/test_document_reader.py` | Unit + integration tests: `TestSummarizeDocumentCacheHit` (cache retrieval), `TestSummarizeDocumentCacheMiss` (subagent spawn), `TestSummarizeDocumentFallback` (graceful failure), `TestEndToEnd` (ReadTool→summarize_document→mock subagent pipeline) |
| `archives/cli.py` | Archived Rich REPL — dead code since 2026-07-12, not imported anywhere |

## Errors Log

- **2026-07-18**: `requirements.txt` floors (`pymupdf>=1.24`, `docling>=2.0`) permitted a clean install to resolve versions vulnerable to CVE-2026-3029/CVE-2026-24009/CVE-2026-44023 → bumped to `pymupdf>=1.26.6`, `docling>=2.75` (pulls docling-core>=2.74.1).
- **2026-07-18**: `plan-work-review` decomposed into `grilling`→`plan`→`to-spec`→`dagi-execute`; `tui/commands.py:63` hardcoded `/plan` to invoke the deleted skill and was missed by all 8 per-task diffs (file untouched by any of them) → caught by a final whole-implementation review, fixed by removing the special case so `/plan` falls through to the generic `self._skill_map` dispatch.
- **2026-07-18**: Harbor Framework / Terminal-bench 2 (Docker-based 89-task benchmark) removed at user request — full 89-task run was never completed, only smoke-tested → deleted `benchmarks/harbor/`, `benchmarks/jobs/`, `benchmarks/config_benchmark.yaml`, `tools/tmux_bash.py`, `docs/terminal-bench.md`, `tests/test_harbor_harness.py`; `benchmarks/dagi_eval/` (self-referential scorecard) is now the only benchmark suite in the repo.
- **2026-07-19**: `config_dagi_eval.yaml`'s `tools:` list included `"compact"`, but `CompactTool` is bound directly by `AgentLoop` (`agent/loop.py`) and never registered into `ToolRegistry` — the entry was a dead no-op → removed it; documented in-file that `compact` can never be LLM-callable via the `tools:` filter.
- **2026-07-19**: dagi_eval benchmark: agent never used `enter_plan_mode` (0 calls across 5 tasks) because tool description emphasized restrictions ("restricts tools") not benefits → rewritten to emphasize quality improvement. Agent also wasted ~13 iterations on Unix commands (`ls`, `find`) on Windows → added OS-detection instruction. Agent hit `continue_injected` on every task → added `<<END_OF_RESPONSE>>` completion signal instruction to system prompt.
- **2026-07-20**: `_convert_pdf_digital()` called docling's `export_to_markdown()` with no `page_break_placeholder`, so real output had zero `<!-- Page N -->` markers — broke `select_pages()`, `_renumber_markers()`, and `total_pages` in `read.py`; invisible to unit tests because the fake docling mocks bypassed the real call signature → split on a sentinel `page_break_placeholder` and number pages manually; updated ~14 test fixtures accordingly.
- **2026-07-20**: `requirements.txt` and `pyproject.toml` had silently diverged for months — `pyproject.toml` was missing `typer`/`rich`/`textual` and still listed dead `nicegui`/`markdown`/`matplotlib` → retired `requirements.txt`, consolidated everything into `pyproject.toml` (core `dependencies` + `pdf`/`docs`/`web`/`benchmark`/`telegram` extras).
- **2026-07-19**: dagi_eval sweeps looked stuck for minutes with zero console output — `build_task_row()` runs `scoring.score_reference()` twice (naive+gold) *before* the agent step and `score_coding_task()` again *after*, each re-timing the deliberately-slow O(n²) baseline `TIMING_RUNS` (5) times, with no progress logging anywhere in that path; separately, `log_callbacks.py` never wired `on_stream_start`/`on_assistant_text_delta`/`on_reasoning_delta` even though `config.stream` defaults `True`, so a turn's text only ever printed after the *entire* turn finished generating → added `print(f"[{name}] scoring ...")` lines around both reference/final scoring phases in `run.py`, and wired live raw-stdout delta printing into `build_cli_callbacks()`.
- **2026-07-20**: `models/docling_models/` was gitignored but had already been committed pre-ignore, including a 203MB `tableformer_accurate.safetensors` blob past GitHub's 100MB hard limit → blocked all `git push` to `main` → purged the whole directory from every commit in history via `git filter-repo --path models/docling_models --invert-paths` (tool installed into the `dagi` conda env), force-pushed `main` (safe: `origin/main` was an ancestor, no one else had pulled the blocked commits).
- **2026-07-25**: `ReadTool` rewrite to call the doc-converter service temporarily broke `tests/test_read_tool.py` and `tests/test_config_loader.py::TestLoadPdfConfig` collection (both imported symbols deleted from `tools/_pdf_convert.py`'s dependency chain) → resolved by the subsequent test-rewrite task (`tests/test_read_tool.py` now mocks `tools.read._doc_service.convert_document`) and by removing `PdfConfig`/`load_pdf_config` and their test class entirely; full suite is green (463 passed) as of the final verification task.
- **2026-07-26**: TUI displayed wrong model name — `get_model_display_name()` only read root `config.yaml` and missed project-level `.dagi/config.yaml` overrides → `tui/app.py:__init__` now calls `resolve_model_config()` first (which merges both config levels) and derives `_model_name`/`_model_id` from the resolved config, eliminating the separate root-only lookup

## Notes & Terms

- **AGENTS.md is force-injected, not just tool-read**: as of 2026-07-24, `_build_preamble()`/`_assemble_system_string()` (`agent/loop.py`) load `AGENTS.md` (dagi-root and project-path copies) directly into every session's system prompt — the old separate `.dagi/agents.md` behavioral-guidelines file is gone, merged into this file's `## Behavioral Guidelines` section. `update-project-context` must preserve that section verbatim on routine updates.
- **END_OF_RESPONSE / `<<END_OF_RESPONSE>>`**: Primary exit sentinel, checked before the legacy `<<TASK_END>>` alias; can appear anywhere in the response (substring check).
- **continuation**: Harness injecting a `"continue"` message when the agent stops without a termination flag.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds budget; preserves system prompt and recent tail. `_compact_context()` catches all exceptions — a failed compaction never crashes the session.
- **`unified_score`** (dagi_eval): efficiency-adjusted score per task, `normalize_perf(recorded, baseline, golden) / normalize_tokens(tokens_in+tokens_out)`, clamped to `MAX_UNIFIED_SCORE` (10.0). `normalize_perf` maps `recorded_score` to [0,1] using the canned `baseline_score` as the floor and canned `golden_score` as the ceiling (0 = no better than baseline, 1 = matches the handcrafted gold solution); `normalize_tokens` scales total tokens against `TOKEN_BUDGET_PER_TASK` (200k), floored at 0.05 so token-free canned rows don't divide-by-near-zero. Both reference scores are computed every run via `scoring.score_reference()` (fresh canned-solution timing, no LLM) regardless of which `--solver` produced `recorded_score`. Both constants live in `benchmarks/dagi_eval/scoring.py`, tunable.
- **tier**: One of `default`/`worker`/`plan` — three model slots in `config.yaml`, switched via `switch_model`. `provider_order` is per-model, read from the catalog entry. `agent/tools.py` only registers the `switch_model` tool if `worker_config` or `advanced_config` is non-`None` on `AgentConfig` — a config with only `default_model` set never exposes the tool. `benchmarks/dagi_eval/harness.py` works around this without adding real tiers: it points `worker_config`/`advanced_config` back at a `dataclasses.replace()` copy of the resolved default config, so `switch_model` is callable but every tier resolves to the same model (a documented no-op) until distinct tiers are configured.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow, notes at `.dagi/gnhf/notes.md`.
- **memory-query / memory-add subagents**: grep + wiki-index traversal for retrieval; classify+write 5-field frontmatter nodes for writing. Both take a single `task` parameter — any other name produces an empty task string. These are DAGI's *own* internal subagents, reading/writing this repo's local `dagi-memory/wiki/` — do not confuse with the next entry.
- **Claude Code `memory-add`/`memory-query` skills (2026-07-25, unrelated to the subagents above)**: global Claude Code skills at `C:\Users\alexr\.claude\skills\{memory-add,memory-query}\`, available in every project the Admiral works in via Claude Code (not DAGI's own agent loop). They target a fixed, hardcoded root — `G:\My Drive\black_grimoire\dagi-memory\wiki\` — not this repo's local `dagi-memory/`, and not resolved from `{cwd}` or `config.yaml`. Adapted from this repo's `.dagi/skills/memory-add` / `.dagi/skills/memory-query` templates; `memory-query` uses only `Read`/`Grep` (no BM25/ranking script, by design). Smoke-tested successfully from this repo's directory, confirming they resolve to the black_grimoire wiki regardless of `cwd`.
- **`dagi/*` branch**: naming convention for branches auto-created on `enter_plan_mode`; the only prefix on which `git_add`/`git_commit`/`git_reset` are permitted. `_dagi_branch_guard()` only covers the dedicated git tools — raw `git` via `BashTool` bypasses it entirely (a nudge, not a security boundary).
- **scheduler**: `scheduler/` package; tasks in `.dagi/scheduler/schedule.yaml` (interval in **seconds**, min 60); runner sets `plan_mode_initiated_by="dagi"` and `ask_user_timeout=60`.
- **tool output filter**: `filter_tool_output()` — LLM sees a truncated preview + file pointer; JSONL logs keep the full result. Full output is deduplicated into the shared hash cache (`.dagi/hash_cache/tool_output/<sha256>.txt`) instead of a randomly-named `tempfile.mkstemp()` file — fixes prior unbounded growth of `.dagi/temp/`.
- **`api_key` vs `api_key_env`**: direct `api_key` in config.yaml overrides env var; empty string still falls through to env var.
- **`get_model_display_name` is root-only — TUI must use resolved config**: as of 2026-07-26, the TUI derives `_model_name` from `resolve_model_config()` (which merges root + `.dagi/config.yaml`) rather than calling the root-only `get_model_display_name()`. The latter still exists and is used by `archives/cli.py` (dead code), but it must never source the display name in any context where a project-level `.dagi/config.yaml` could override `default_model`.
- **`supports_pause`**: gates error-pause behavior on `AgentCallbacks`, defaults `False`; TUI sets `True` explicitly (checking `on_pause is not lambda` would be fragile).
- **TUI thread safety**: `AgentLoop` runs on a daemon thread; all widget mutations go through `App.call_from_thread()`. Sidebar uses plain instance attributes + `self.refresh()`, not Textual `reactive` (dict-content equality checks miss updates).
- **Dependency install**: `pyproject.toml` is the single source of truth (as of 2026-07-20, replacing the retired `requirements.txt`) — core `dependencies` cover CLI/TUI/Telegram; `[project.optional-dependencies]` extras are `web`, `benchmark`, `telegram` (the `pdf`/`docs` extras were removed 2026-07-25 — those heavy deps, docling/torch/pymupdf/ocrmypdf/markitdown, now live only in `services/doc_converter/environment.yml`). Install via `pip install -e .` (core) or `pip install -e ".[web,benchmark,telegram]"` (everything); set up the doc-converter service separately with `conda env create -f services/doc_converter/environment.yml` if document (PDF/docx/xlsx/pptx) reading is needed.
- **Escalation is a sidecar file, not live IPC**: `EscalateIssueTool` writes `<handoff-stem>_escalation.md`; `_subagent_runner.py`'s existing 2s poll loop picks it up. Resolving an escalation does not consume a retry attempt — only a completed FAIL verdict does.
- **`__list__:` encoding**: non-string tool results are encoded as `"__list__:" + json.dumps(result)` in JSONL/callbacks — downstream consumers must know this prefix.
- **Windows CRLF**: `EditTool`/`WriteTool` always write LF on disk (`newline="\n"`) and normalize `oldText`/`newText` before matching — prevents Windows' default `\n`→`\r\n` translation from corrupting files or doubling to `\r\r\n`.
- **`read` tool output format**: `cat -n` style — each line prefixed `{1-indexed lineno:6d}\t{content}`; the line number is not part of the file and must be stripped before use as `oldText` in `edit`.
- **`read` tool document support (2026-07-25 rewrite)**: `.pdf`/`.docx`/`.xlsx`/`.pptx` all delegate to `tools.read._doc_service.convert_document()`, which calls the doc-converter FastAPI service over HTTP (`AgentConfig.services["doc_converter"]`; `None`/missing → friendly error, no inline fallback). All paths converge on the same `cat -n` numbering/offset/limit logic. PDF output includes a `[PDF: name | N pages]` header. `pages` parameter (PDF only) filters the returned markdown by `<!-- Page N -->` markers via `_select_pages()`/`_parse_page_spec()` (now local to `_read.py`, not `tools/_pdf_convert.py`). `DocServiceError` surfaces service-side errors with a code+message, never a raw traceback.
- **`read` tool auto-summarization gate**: when `ReadTool` is constructed with `reserve_tokens > 0` and `project_path`, a default `run()` call (offset=1, limit=2000) estimates full-doc token count (`len(full_text) // 4`); if it meets or exceeds `reserve_tokens`, `summarize_document()` is invoked and its result returned in place of raw lines. Falls back to raw text if the subagent returns `None`. Subagent `ReadTool` instances are constructed without `reserve_tokens` (stays 0) to prevent recursive summarization.
- **PDF/document conversion internals moved to the service (2026-07-25)**: docling/ocrmypdf/pymupdf pipelines, the PDF hash cache (`.dagi/hash_cache/pdf/`), scanned-PDF detection, and map-reduce parallel conversion all now live in the standalone doc-converter service, not in dagi's `tools/_pdf_convert.py` (dead code, see Key Files table). dagi-side, `tools/read/_doc_service.py` keeps its own local hash cache under `.dagi/hash_cache/doc_convert/` to avoid re-uploading unchanged files. `tools/_hash_cache.py` (`cache_path()`/`get_or_compute()`) is still used by the tool-output filter cache (`.dagi/hash_cache/tool_output/`).
- **document_summary cache**: `.dagi/hash_cache/document_summary/<sha256>_summary.md` — sectioned markdown summary written by the `document-reader` subagent, keyed by SHA-256 of the full document text. `summarize_document()` checks for this file before spawning the subagent. Full text spooled to `.dagi/hash_cache/tool_output/<sha256>.txt` so the subagent can read it without re-passing the content.
- **StreamPreview full-window expand**: `expand()`/`finish()` in `tui/streaming.py` toggle between `height: 1fr` (fills window down to the running-indicator/prompt, `ConversationPane` hidden) and the collapsed `height: auto`/`max-height: 14` default. `tui/callbacks.py` defers the expand trigger to the *first rendered delta* of a stream segment (not `on_stream_start`) to avoid a blank-screen flash on segments with no visible text/reasoning; a per-segment `_stream["expanded"]` flag gates the matching collapse on `on_stream_end`. Tail-line rendering is size-aware only while expanded (`self.size.height`), unchanged (`TAIL_LINES = 12`) while collapsed.
- **Textual `clear_rule()` vs CSS-declared styles**: clearing an inline style rule (`styles.clear_rule("x")`) falls back to the class-level `DEFAULT_CSS` value if one exists, not `None` — a style must be set as an *inline* rule (e.g. in `__init__`) for `clear_rule()` to genuinely unset it. `StreamPreview.max_height` is set in `__init__` rather than `DEFAULT_CSS` for exactly this reason.
- **Skill chain replacing `plan-work-review`**: the old monolithic skill is now four independent skills chained by prose ("invoke `plan` next", `skill("to-spec")`) — `grilling` (adversarial interrogation) → `plan` (orchestrates spec synthesis, exploration, plan-file authoring, approval) → `to-spec` (`disable-model-invocation: true`, conversation→`spec.md`) → `dagi-execute` (per-subtask write-tests/worker/review cycle, 2-attempt retry budget, escalation handling). Blind-oracle test model unchanged: only the review subagent sees test paths.
- **`previous_branch`**: `AgentConfig.previous_branch` + `get_current_branch()` in `agent/_git_branch.py` capture the branch active before `enter_plan_mode` creates its `dagi/*` branch; `dagi-execute`'s Completion phase checks back out to it, guarded for `None` (plan mode entered outside a git repo).
- **Telegram `allowed_chat_ids`**: defaults to an empty `frozenset` (open to anyone) for backwards compatibility with existing single-user deployments — `TelegramBot.__init__` logs a `warning` on startup whenever it's empty rather than refusing to run. Set `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated) to actually restrict access.
- **dagi_eval `run_entry()` needs an absolute `task_dir`**: `scoring.run_entry()` spawns `_exec_entry.py` with `cwd=<scratch tempdir>`, so a *relative* `input_dir`/`code_dir` silently resolves against the wrong cwd and `pipeline.run()` sees an empty `logs/` dir → looks exactly like a correctness-gate failure. Production always goes through `harness.TASKS_DIR` (`Path(__file__).parent`, always absolute), so this only bites ad-hoc scripts/tests that pass `Path("benchmarks/dagi_eval/tasks/...")` directly — always resolve via `harness.TASKS_DIR` when testing `scoring.py` in isolation.
- **`dagi` conda env quirks (PDF/OCR)**: must invoke via `conda run -n dagi python ...`, not a bare `python.exe` path from the env — conda's `etc/conda/activate.d/*` scripts set `PATH` (`Library/bin`) and `TESSDATA_PREFIX`, which a bare interpreter invocation skips, breaking tesseract DLL loading and OCR config lookup. The env's `share/tessdata/` was also missing `configs/`/`tessconfigs/` subfolders present under the sibling `Library/share/tessdata/` — ocrmypdf needs both copied in to run.
- **`git-filter-repo`**: not on PATH by default; install via `conda run -n dagi pip install git-filter-repo`, then prepend `<dagi-env>/Scripts` to `PATH` so `git filter-repo` resolves as a git subcommand. Removes the `origin` remote as a safety measure — re-add it after rewriting. Only rewrite/force-push branches confirmed to have `origin/<branch>` as an ancestor of local `<branch>` (checked via `git merge-base --is-ancestor`).
- **CLI streaming (`agent/log_callbacks.py`)**: `build_cli_callbacks()` wires `on_stream_start`/`on_assistant_text_delta`/`on_reasoning_delta` to print raw, unbuffered deltas straight to `sys.stdout` (not through `logging`, since partial lines don't fit its per-call-newline model). `on_assistant_text`/`on_reasoning` still log the same content again afterward as one timestamped, complete line — intentional duplication (live preview + finalized record), mirroring `tui/callbacks.py`'s `StreamPreview` pattern.
- **Subagent handoff enforcement — out-of-scope residuals (logged 2026-07-26, not fixed by design/deferral):**
  1. Subagent prompts never teach `<<END_OF_RESPONSE>>`.
  2. `plan/` and `cli/` prompt dirs are vestigial (no `subagent_config.yaml`).
  3. `escalate_issue`'s docstring is stale.
  4. `_poll_until`'s "exited without writing handoff" branch stays dead by design.
- **MCP-analog service extraction (complete, 2026-07-25)**: document conversion (PDF/docx/xlsx/pptx → markdown) was extracted from dagi into a standalone FastAPI service at `services/doc_converter/` (design: `docs/superpowers/specs/2026-07-25-doc-converter-service-design.md`). `read` tool (`tools/read/_read.py`) delegates all doc conversion to `tools/read/_doc_service.py` over HTTP (`services.doc_converter` in `config.yaml` → `AgentConfig.services`), hard-fail-if-unreachable, no inline fallback — the service must be started separately (`conda run -n doc_converter python -m services.doc_converter`, own `environment.yml`). `tools/_pdf_convert.py` was deleted; `PdfConfig`/`load_pdf_config` and the `pdf`/`docs` `pyproject.toml` extras were removed entirely. Known deferred follow-up: `dev/_verify_local_models.py` still imports the deleted `tools._pdf_convert` module and needs to be rewritten against the new service-based conversion API — not covered by the test suite, not fixed by this migration.

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
- Review velocity outpaces fix velocity — GNHF self-review loop dormant 85+ days despite 259 unanalysed session logs.

### Project Shortcomings

- `BashTool` is unsandboxed and can run raw `git` commands that bypass the `dagi/*` branch guard entirely.
- No pause during subagent execution — ESC pauses the parent loop but child subprocesses continue unaffected.
- Base64 image data inflates compaction prompts and `session_end` JSONL records with raw base64 noise.
- Session cost tracking is almost always blank — most providers don't populate `usage.cost`.
- `/hist` in TUI is broken — writes to a `rich.Console` behind Textual's canvas instead of `ConversationPane`.
- DAGI Eval Benchmark first real `--solver agent` run (hy3:free) scored well on speedup (123x, 65x, 359x) but never invoked plan mode despite it being available — tool description and system prompt were the bottleneck, not the model.
- `_parse_frontmatter` is duplicated verbatim between `agent/skills.py` and `agent/workflows.py`.
- `disable-model-invocation` SKILL.md frontmatter flag has zero code-level enforcement in `agent/skills.py` — purely advisory, any phrasing can still trigger a skill meant to be programmatic-only.
- dagi_eval's `--timeout-min` only bounds `run_agent_on_task()`'s own loop (checked between iterations via `on_iteration`) — it does not bound the reference/final scoring phases in `build_task_row()`, and a single slow/blocked iteration (e.g. stuck in the API retry backoff) isn't interrupted until that iteration completes. A sweep's real wall-clock time can run well past what `--timeout-min` implies.

### Potential Areas of Exploration

- **MCP-analog services**: doc_converter is the first extraction; web_fetch, web_search are candidates for the same pattern — slim dagi core, reusable services in `services/`.
- Fix `/hist` and add cache-hit visibility (`usage.prompt_tokens_details.cached_tokens`) in the sidebar.
- Session replay / dry-run mode — JSONL logs already have everything needed for deterministic replay.
- Parallel subagent dispatch — **does** require architectural change, contrary to an earlier note here. `agent/loop.py:631-641` builds the transcript in strict assistant/tool alternation and `registry.dispatch()` is a synchronous `str`-returning call, so a subagent run (being a tool call) blocks the loop. Two `spawn_*` calls in one message run back-to-back. The fix is **not** a thread pool in the loop — it is a two-tool protocol: give `spawn_*` a `background: true` mode that registers the subprocess in `_active` and returns an id immediately, plus a new `get_subagent_result(id)` tool that blocks on the existing poll. Both stay ordinary blocking tools, so `loop.py` needs no change. A concurrency cap is then required, since nothing else throttles fan-out once spawn returns instantly. See `wiki/projects/driverless-agi/subagent-architecture-comparison.md`.
- Bootstrap a real GNHF self-review run against the 259 accumulated session logs.
