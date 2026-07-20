# AGENTS.md

> Last updated: 2026-07-20 (dependency install consolidated: `requirements.txt` retired, `pyproject.toml` is now the single source of truth) | [README](README.md) | [TODO](TODO.md)

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
| `agent/config_loader.py` | Reads `config.yaml`, resolves API key, merges per-project `.dagi/config.yaml` over root; `PdfConfig`/`load_pdf_config()` resolves the optional `pdf:` block (`worker_ram_gb`, `max_workers`) consumed by `tools/_pdf_convert.py`; `TelegramConfig`/`load_telegram_config()` resolves `telegram.allowed_chat_ids_env` into `allowed_chat_ids: frozenset[int]` — imports flow `tools -> agent.config_loader`, same direction as `tools.read -> agent.base_tool` |
| `tg/bot.py` | `TelegramBot._is_authorized(chat_id)` gates all 4 handlers against `allowed_chat_ids`; empty allowlist = open (back-compat) but logs a startup warning |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; `build_subagent_registry()` |
| `agent/__init__.py` | `DAGI_ROOT` — the single canonical root definition |
| `tools/_subagent_runner.py` | Pipe-based subagent runner (`run_subagent()`/`resume_subagent()`) |
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
| `tools/_pdf_convert.py` | PDF-to-markdown conversion: `convert_pdf()` orchestrator using the shared hash cache (`.dagi/hash_cache/pdf/`), dual pipeline (docling for digital-native, ocrmypdf→docling for scanned), page helpers (`parse_page_spec`, `select_pages`), detection (`is_scanned_pdf`). PDFs over `PDF_PARALLEL_MIN_PAGES` (8) route through a map-reduce parallel path: `_split_into_chunks` (page-range splitting via `fitz`) → `ProcessPoolExecutor` dispatch to `_convert_chunk` (one docling load per worker, picklable top-level function) → `_renumber_markers` merge/reduce step in `_convert_pdf_parallel`; worker count from `_estimate_worker_count` (caps: CPU count, page count, free RAM via `psutil`, `pdf.max_workers`). `_convert_pdf_digital` loads TableFormer/heron layout weights from `models/docling_models` via `PdfPipelineOptions.artifacts_path` (falls back to HF download if that dir is missing) and numbers `<!-- Page N -->` markers itself by splitting `export_to_markdown(page_break_placeholder=_PAGE_BREAK_SENTINEL)` on the sentinel |
| `tests/fixtures/pdf/` | `sample_digital.pdf`/`sample_scanned.pdf` fixtures for `tests/test_read_tool.py` and manual smoke tests, generated by `_generate_samples.py` (PyMuPDF: real text + hand-drawn table for digital, rasterized-to-image for scanned — no text layer) |
| `tools/_hash_cache.py` | Shared content-addressed cache (`cache_path()`, `get_or_compute()`) used by `_pdf_convert.py` and `output_filter.py`; layout `.dagi/hash_cache/{pdf,tool_output}/<sha256>.<ext>`, dedup-only (no eviction) |
| `tools/_document_reader.py` | Orchestrates the `document-reader` subagent for long documents: cache-hit fast path (`.dagi/hash_cache/document_summary/<sha256>_summary.md`), cache-miss spawns subagent via `run_subagent()`, returns `None` on failure for caller to fall back to truncation |
| `tests/test_document_reader.py` | Unit + integration tests: `TestSummarizeDocumentCacheHit` (cache retrieval), `TestSummarizeDocumentCacheMiss` (subagent spawn), `TestSummarizeDocumentFallback` (graceful failure), `TestEndToEnd` (ReadTool→summarize_document→mock subagent pipeline) |
| `archives/cli.py` | Archived Rich REPL — dead code since 2026-07-12, not imported anywhere |
| `.dagi/agents.md` | Behavioral guidelines loaded every session (coding standards, memory protocol) — separate from this file |

## Errors Log

- **2026-07-18**: `tg/bot.py:_run_agent_task`'s `finally` block referenced `loop` before it could be assigned if `resolve_model_config()`/`build_callbacks()` raised → `UnboundLocalError` masking the real exception → added `loop = None` before the `try`.
- **2026-07-18**: `requirements.txt` floors (`pymupdf>=1.24`, `docling>=2.0`) permitted a clean install to resolve versions vulnerable to CVE-2026-3029/CVE-2026-24009/CVE-2026-44023 → bumped to `pymupdf>=1.26.6`, `docling>=2.75` (pulls docling-core>=2.74.1).
- **2026-07-18**: `plan-work-review` decomposed into `grilling`→`plan`→`to-spec`→`dagi-execute`; `tui/commands.py:63` hardcoded `/plan` to invoke the deleted skill and was missed by all 8 per-task diffs (file untouched by any of them) → caught by a final whole-implementation review, fixed by removing the special case so `/plan` falls through to the generic `self._skill_map` dispatch.
- **2026-07-18**: Harbor Framework / Terminal-bench 2 (Docker-based 89-task benchmark) removed at user request — full 89-task run was never completed, only smoke-tested → deleted `benchmarks/harbor/`, `benchmarks/jobs/`, `benchmarks/config_benchmark.yaml`, `tools/tmux_bash.py`, `docs/terminal-bench.md`, `tests/test_harbor_harness.py`; `benchmarks/dagi_eval/` (self-referential scorecard) is now the only benchmark suite in the repo.
- **2026-07-19**: `config_dagi_eval.yaml`'s `tools:` list included `"compact"`, but `CompactTool` is bound directly by `AgentLoop` (`agent/loop.py`) and never registered into `ToolRegistry` — the entry was a dead no-op → removed it; documented in-file that `compact` can never be LLM-callable via the `tools:` filter.
- **2026-07-19**: dagi_eval benchmark: agent never used `enter_plan_mode` (0 calls across 5 tasks) because tool description emphasized restrictions ("restricts tools") not benefits → rewritten to emphasize quality improvement. Agent also wasted ~13 iterations on Unix commands (`ls`, `find`) on Windows → added OS-detection instruction. Agent hit `continue_injected` on every task → added `<<END_OF_RESPONSE>>` completion signal instruction to system prompt.
- **2026-07-16**: `ReadTool` returned bare joined lines with no line numbers, forcing `bash`/`cat -n` fallback to locate lines → `read.py` now emits `cat -n` style `{lineno:6d}\t{line}` output.
- **2026-07-20**: `_convert_pdf_digital()` called docling's `export_to_markdown()` with no `page_break_placeholder`, so real output had zero `<!-- Page N -->` markers — broke `select_pages()`, `_renumber_markers()`, and `total_pages` in `read.py`; invisible to unit tests because the fake docling mocks bypassed the real call signature → split on a sentinel `page_break_placeholder` and number pages manually; updated ~14 test fixtures accordingly.
- **2026-07-20**: `requirements.txt` and `pyproject.toml` had silently diverged for months — `pyproject.toml` was missing `typer`/`rich`/`textual` and still listed dead `nicegui`/`markdown`/`matplotlib` → retired `requirements.txt`, consolidated everything into `pyproject.toml` (core `dependencies` + `pdf`/`docs`/`web`/`benchmark`/`telegram` extras).
- **2026-07-19**: dagi_eval sweeps looked stuck for minutes with zero console output — `build_task_row()` runs `scoring.score_reference()` twice (naive+gold) *before* the agent step and `score_coding_task()` again *after*, each re-timing the deliberately-slow O(n²) baseline `TIMING_RUNS` (5) times, with no progress logging anywhere in that path; separately, `log_callbacks.py` never wired `on_stream_start`/`on_assistant_text_delta`/`on_reasoning_delta` even though `config.stream` defaults `True`, so a turn's text only ever printed after the *entire* turn finished generating → added `print(f"[{name}] scoring ...")` lines around both reference/final scoring phases in `run.py`, and wired live raw-stdout delta printing into `build_cli_callbacks()`.

## Notes & Terms

- **END_OF_RESPONSE / `<<END_OF_RESPONSE>>`**: Primary exit sentinel, checked before the legacy `<<TASK_END>>` alias; can appear anywhere in the response (substring check).
- **continuation**: Harness injecting a `"continue"` message when the agent stops without a termination flag.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds budget; preserves system prompt and recent tail. `_compact_context()` catches all exceptions — a failed compaction never crashes the session.
- **`unified_score`** (dagi_eval): efficiency-adjusted score per task, `normalize_perf(recorded, baseline, golden) / normalize_tokens(tokens_in+tokens_out)`, clamped to `MAX_UNIFIED_SCORE` (10.0). `normalize_perf` maps `recorded_score` to [0,1] using the canned `baseline_score` as the floor and canned `golden_score` as the ceiling (0 = no better than baseline, 1 = matches the handcrafted gold solution); `normalize_tokens` scales total tokens against `TOKEN_BUDGET_PER_TASK` (200k), floored at 0.05 so token-free canned rows don't divide-by-near-zero. Both reference scores are computed every run via `scoring.score_reference()` (fresh canned-solution timing, no LLM) regardless of which `--solver` produced `recorded_score`. Both constants live in `benchmarks/dagi_eval/scoring.py`, tunable.
- **tier**: One of `default`/`worker`/`plan` — three model slots in `config.yaml`, switched via `switch_model`. `provider_order` is per-model, read from the catalog entry. `agent/tools.py` only registers the `switch_model` tool if `worker_config` or `advanced_config` is non-`None` on `AgentConfig` — a config with only `default_model` set never exposes the tool. `benchmarks/dagi_eval/harness.py` works around this without adding real tiers: it points `worker_config`/`advanced_config` back at a `dataclasses.replace()` copy of the resolved default config, so `switch_model` is callable but every tier resolves to the same model (a documented no-op) until distinct tiers are configured.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow, notes at `.dagi/gnhf/notes.md`.
- **memory-query / memory-add subagents**: grep + wiki-index traversal for retrieval; classify+write 5-field frontmatter nodes for writing. Both take a single `task` parameter — any other name produces an empty task string.
- **`dagi/*` branch**: naming convention for branches auto-created on `enter_plan_mode`; the only prefix on which `git_add`/`git_commit`/`git_reset` are permitted. `_dagi_branch_guard()` only covers the dedicated git tools — raw `git` via `BashTool` bypasses it entirely (a nudge, not a security boundary).
- **scheduler**: `scheduler/` package; tasks in `.dagi/scheduler/schedule.yaml` (interval in **seconds**, min 60); runner sets `plan_mode_initiated_by="dagi"` and `ask_user_timeout=60`.
- **tool output filter**: `filter_tool_output()` — LLM sees a truncated preview + file pointer; JSONL logs keep the full result. Full output is deduplicated into the shared hash cache (`.dagi/hash_cache/tool_output/<sha256>.txt`) instead of a randomly-named `tempfile.mkstemp()` file — fixes prior unbounded growth of `.dagi/temp/`.
- **`api_key` vs `api_key_env`**: direct `api_key` in config.yaml overrides env var; empty string still falls through to env var.
- **`supports_pause`**: gates error-pause behavior on `AgentCallbacks`, defaults `False`; TUI sets `True` explicitly (checking `on_pause is not lambda` would be fragile).
- **TUI thread safety**: `AgentLoop` runs on a daemon thread; all widget mutations go through `App.call_from_thread()`. Sidebar uses plain instance attributes + `self.refresh()`, not Textual `reactive` (dict-content equality checks miss updates).
- **Dependency install**: `pyproject.toml` is the single source of truth (as of 2026-07-20, replacing the retired `requirements.txt`) — core `dependencies` cover CLI/TUI/Telegram; `[project.optional-dependencies]` extras are `pdf`, `docs`, `web`, `benchmark`, `telegram`. Install via `pip install -e .` (core) or `pip install -e ".[pdf,docs,web,benchmark]"` (everything).
- **Escalation is a sidecar file, not live IPC**: `EscalateIssueTool` writes `<handoff-stem>_escalation.md`; `_subagent_runner.py`'s existing 2s poll loop picks it up. Resolving an escalation does not consume a retry attempt — only a completed FAIL verdict does.
- **`__list__:` encoding**: non-string tool results are encoded as `"__list__:" + json.dumps(result)` in JSONL/callbacks — downstream consumers must know this prefix.
- **Windows CRLF**: `EditTool`/`WriteTool` always write LF on disk (`newline="\n"`) and normalize `oldText`/`newText` before matching — prevents Windows' default `\n`→`\r\n` translation from corrupting files or doubling to `\r\r\n`.
- **`read` tool output format**: `cat -n` style — each line prefixed `{1-indexed lineno:6d}\t{content}`; the line number is not part of the file and must be stripped before use as `oldText` in `edit`.
- **`read` tool document support**: `.docx`/`.xlsx`/`.pptx` via optional `markitdown`; `.pdf` via optional `docling` (digital-native) or `ocrmypdf`+`docling` (scanned). All paths converge on the same `cat -n` numbering/offset/limit logic. PDF output includes a metadata header with cache path. `pages` parameter (PDF only) filters by `<!-- Page N -->` markers. Missing dependencies return friendly install-hint errors, never tracebacks.
- **`read` tool auto-summarization gate**: when `ReadTool` is constructed with `reserve_tokens > 0` and `project_path`, a default `run()` call (offset=1, limit=2000) estimates full-doc token count (`len(full_text) // 4`); if it meets or exceeds `reserve_tokens`, `summarize_document()` is invoked and its result returned in place of raw lines. Falls back to raw text if the subagent returns `None`. Subagent `ReadTool` instances are constructed without `reserve_tokens` (stays 0) to prevent recursive summarization.
- **PDF conversion cache**: `.dagi/hash_cache/pdf/<sha256>.md` — full document cached on first read, keyed by SHA-256 of PDF content, via the shared `tools/_hash_cache.py` module. Cache auto-invalidates when PDF changes. `pages`/`offset`/`limit` slice from the cached markdown. Cache path is exposed in tool output so the LLM can reference it for copy/save operations.
- **Shared hash cache**: `tools/_hash_cache.py` — `cache_path()`/`get_or_compute()`, content-addressed (SHA-256 of input bytes) storage shared by the PDF cache and the tool-output filter cache. Layout: `.dagi/hash_cache/{pdf,tool_output}/<sha256>.<ext>`. Dedup-only by design — no eviction, no cross-project sharing, no migration of the old `.dagi/pdf_cache/`/`.dagi/temp/` directories (they're simply no longer written to).
- **PDF scanned detection**: `is_scanned_pdf()` in `_pdf_convert.py` probes first 3 pages via `pymupdf` (fitz); < 50 chars total = scanned. Returns `False` gracefully if fitz is absent. Scanned PDFs go through `ocrmypdf` (tesseract overlay) before docling conversion.
- **PDF parallel conversion (map-reduce)**: `PDF_PARALLEL_MIN_PAGES = 8` in `tools/_pdf_convert.py` is a hardcoded threshold, not exposed in `config.yaml` — PDFs with more than 8 pages are eligible for the parallel path. Worker count comes from `_estimate_worker_count`, capped by `os.cpu_count()`, page count, free RAM (`psutil`, budgeted per `pdf.worker_ram_gb`), and the optional `pdf.max_workers` config key; if the estimate is 1, `convert_pdf()` falls back to the original single-process path unchanged. `pdf:` in `config.yaml` (both keys optional) — `worker_ram_gb` (default 2.0), `max_workers` (default `null`/uncapped) — loaded via `PdfConfig`/`load_pdf_config()` in `agent/config_loader.py`. `psutil` is a **core** (required) dependency in `requirements.txt` as of this feature.
- **document_summary cache**: `.dagi/hash_cache/document_summary/<sha256>_summary.md` — sectioned markdown summary written by the `document-reader` subagent, keyed by SHA-256 of the full document text. `summarize_document()` checks for this file before spawning the subagent. Full text spooled to `.dagi/hash_cache/tool_output/<sha256>.txt` so the subagent can read it without re-passing the content.
- **StreamPreview full-window expand**: `expand()`/`finish()` in `tui/streaming.py` toggle between `height: 1fr` (fills window down to the running-indicator/prompt, `ConversationPane` hidden) and the collapsed `height: auto`/`max-height: 14` default. `tui/callbacks.py` defers the expand trigger to the *first rendered delta* of a stream segment (not `on_stream_start`) to avoid a blank-screen flash on segments with no visible text/reasoning; a per-segment `_stream["expanded"]` flag gates the matching collapse on `on_stream_end`. Tail-line rendering is size-aware only while expanded (`self.size.height`), unchanged (`TAIL_LINES = 12`) while collapsed.
- **Textual `clear_rule()` vs CSS-declared styles**: clearing an inline style rule (`styles.clear_rule("x")`) falls back to the class-level `DEFAULT_CSS` value if one exists, not `None` — a style must be set as an *inline* rule (e.g. in `__init__`) for `clear_rule()` to genuinely unset it. `StreamPreview.max_height` is set in `__init__` rather than `DEFAULT_CSS` for exactly this reason.
- **Skill chain replacing `plan-work-review`**: the old monolithic skill is now four independent skills chained by prose ("invoke `plan` next", `skill("to-spec")`) — `grilling` (adversarial interrogation) → `plan` (orchestrates spec synthesis, exploration, plan-file authoring, approval) → `to-spec` (`disable-model-invocation: true`, conversation→`spec.md`) → `dagi-execute` (per-subtask write-tests/worker/review cycle, 2-attempt retry budget, escalation handling). Blind-oracle test model unchanged: only the review subagent sees test paths.
- **`previous_branch`**: `AgentConfig.previous_branch` + `get_current_branch()` in `agent/_git_branch.py` capture the branch active before `enter_plan_mode` creates its `dagi/*` branch; `dagi-execute`'s Completion phase checks back out to it, guarded for `None` (plan mode entered outside a git repo).
- **Telegram `allowed_chat_ids`**: defaults to an empty `frozenset` (open to anyone) for backwards compatibility with existing single-user deployments — `TelegramBot.__init__` logs a `warning` on startup whenever it's empty rather than refusing to run. Set `TELEGRAM_ALLOWED_CHAT_IDS` (comma-separated) to actually restrict access.
- **dagi_eval `run_entry()` needs an absolute `task_dir`**: `scoring.run_entry()` spawns `_exec_entry.py` with `cwd=<scratch tempdir>`, so a *relative* `input_dir`/`code_dir` silently resolves against the wrong cwd and `pipeline.run()` sees an empty `logs/` dir → looks exactly like a correctness-gate failure. Production always goes through `harness.TASKS_DIR` (`Path(__file__).parent`, always absolute), so this only bites ad-hoc scripts/tests that pass `Path("benchmarks/dagi_eval/tasks/...")` directly — always resolve via `harness.TASKS_DIR` when testing `scoring.py` in isolation.
- **`dagi` conda env quirks (PDF/OCR)**: must invoke via `conda run -n dagi python ...`, not a bare `python.exe` path from the env — conda's `etc/conda/activate.d/*` scripts set `PATH` (`Library/bin`) and `TESSDATA_PREFIX`, which a bare interpreter invocation skips, breaking tesseract DLL loading and OCR config lookup. The env's `share/tessdata/` was also missing `configs/`/`tessconfigs/` subfolders present under the sibling `Library/share/tessdata/` — ocrmypdf needs both copied in to run.
- **CLI streaming (`agent/log_callbacks.py`)**: `build_cli_callbacks()` wires `on_stream_start`/`on_assistant_text_delta`/`on_reasoning_delta` to print raw, unbuffered deltas straight to `sys.stdout` (not through `logging`, since partial lines don't fit its per-call-newline model). `on_assistant_text`/`on_reasoning` still log the same content again afterward as one timestamped, complete line — intentional duplication (live preview + finalized record), mirroring `tui/callbacks.py`'s `StreamPreview` pattern.

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

- Fix `/hist` and add cache-hit visibility (`usage.prompt_tokens_details.cached_tokens`) in the sidebar.
- Session replay / dry-run mode — JSONL logs already have everything needed for deterministic replay.
- Parallel subagent dispatch — no architectural change needed, `spawn_*` already supports concurrent calls.
- Bootstrap a real GNHF self-review run against the 259 accumulated session logs.
