# TODO

## Completed

- **Compact cache-prefix (Tasks 1–8)** · `done` · `2026-08-19` — Wired compact subagent to inherit the parent's warm KV-cache prefix via retroactive branching, fork-context serialization, and `reconstruct()`. (1) `agent/context_spec.py`: `reconstruct()` honors `parent_cut_seq` (retroactive fork point in `BRANCH_START` data). (2) `agent/session_log.py`: `branch_event(id)` helper. (3) `agent/loop.py`: `_last_request_snapshot` captured before every API call; `compact()` rewritten — appends `BRANCH_START` with `parent_cut_seq`, calls `build_fork_context()`, writes fork-context JSON temp file, calls `run_subagent(preset="compact", fork_context_path=...)`, validates handoff + surface generation (atomicity), appends `CONTEXT_COMPACTION`. (4) `tools/subagent_api.py`: `build_fork_context()` builds version-1 fork-context (no API keys); `run_subagent()` gained `fork_context_path` param (injects `--fork-context` into subprocess argv). (5) `tools/_subagent_runner.py`: `fork_context_path` tracked in `_SubagentState`; cleaned up on all terminal paths (success/error/escalation; NOT timeout). (6) `tools/subagent_main.py`: `run_forked_compact_mode()` reads fork-context, resolves credentials via env (NOT from fork-context), makes single non-streaming API call, writes assistant text directly as handoff; `main()` dispatches to it when `--fork-context` is present. (7) `.dagi/subagents/compact/subagent_config.yaml`: `model_tier: main` → `model_tier: inherit`. (8) Full test suite: 884 passing. Bug caught during review: `extra_argv` (None) extended instead of `_extra_argv` accumulator in `subagent_api.py` — fixed. Plan: `docs/superpowers/plans/2026-08-18-compact-cache-prefix.md`.

- **Subagent-based context compaction (Tasks 1–7)** · `done` · `2026-08-18` — Replaced `CompactTool`'s direct LLM summarization call with a dedicated `compact` subagent that inherits the parent's warm KV-cache prefix via `spec_for_branch`. (1) `.dagi/subagents/compact/` preset (no `main.py` — internal-only, not model-callable): `subagent_config.yaml` + `prompt.md` with a 5-rule technical summarization prompt. (2) `tools/compact/_tail_boundary.py`: `TailBoundary` frozen dataclass, `compute_tail_boundary()` (step-based floor, avg-tokens-per-step heuristic), `estimate_tokens()` with a 200-token base64 placeholder to prevent list-content inflation. (3) `agent/loop.py` rewrite: `CompactionResult` local dataclass, `_NO_COMPACTION` sentinel, `_collect_steps()` walks `log.surface.nodes` (surface-aware — skips already-summarized steps), `_find_surface_index_for_step()`, `_log_compaction()` appends `CONTEXT_COMPACTION` replace op, `compact()` calls `run_subagent(preset="compact")` and logs the result, `_compact_context()` swallows exceptions. Generation counter `_compaction_generation` increments per successful compaction. (4) `tools/compact/__init__.py` updated to export new API; `_compact.py` gutted (logic moved to subagent path); `test_compact_tool.py` deleted; stale `TestCompactionSnapshot` class removed from `test_continuation.py`. (5) Integration tests in `tests/test_compact_subagent.py` (6 tests) and `tests/test_compact_integration.py` (4 tests) — surface replace-op verified, generation counter, subagent failure, surface-aware step collection. 849 tests passing. Plan: `docs/superpowers/plans/2026-08-18-hybrid-compaction-pipeline.md`.

- **Session log tree — agent loop wiring (Tasks 1–5)** · `done` · `2026-08-17` — Wired `branch/start` event logging into the live agent loop and subagent execution path. (1) `tools/subagent_api.py`: `run_subagent()` gained `parent_log: SessionLog | None = None`; logs `branch/start` event before subprocess spawn guarded on `open_turn AND open_step`; `SubagentResult` gained `branch_id: str | None = None`. (2) `agent/subagent_tools.py` + `agent/tools.py`: `session_log` parameter threaded through `_discover_subagent_tools()` and `create_tool_registry()`. (3) `agent/loop.py`: `AgentLoop` passes `session_log=self.log` at all 3 `create_tool_registry()` call sites; `self.log` init moved earlier in `__init__` to allow this. (4) All 10 `.dagi/subagents/*/main.py` tools: accept `session_log=None`, store `self._session_log`, pass `parent_log=self._session_log` to `run_subagent()`. (5) Integration tests in `tests/test_branch_start_integration.py` verify full end-to-end path with subprocess mocked at `_runner.run_subagent`. 849 tests passing. Plan: `docs/superpowers/plans/2026-08-17-session-log-tree-agent-loop-wiring.md`.

- **Session log tree + subagent context construction (Tasks 1–10)** · `done` · `2026-08-17` — 10-task implementation on `worktree-session-log-tree`. Data layer for tree-structured session logs: (1) `branch/start` event type marks fork points; (2) `SessionEvent.branch` field (default `"main"`, omitted from JSON for backward compat with format-1 logs); (3) `SessionLog` tracks branches in `_branches`, routes non-main events off the main surface, enforces BRANCH_START-on-main and `"main"`-reserved-name invariants; (4) `agent/context_spec.py` — `BranchSegment`, `ContextSpec`, `reconstruct()` with two-pass surface simulation (handles compaction replace ops and no-turn CONTEXT_COMPACTION events), `spec_for_main()` and `spec_for_branch()` builder helpers; (5) `ToolRegistry.deny()` for dispatch-time access denial (tools stay in schema for provider KV-cache preservation); (6) `SESSION_FORMAT_VERSION` bumped 1→2. 835 tests passing. Plan: `docs/superpowers/plans/2026-08-17-session-log-tree-and-subagent-context.md`.

- **Electron desktop GUI — Python sidecar + TypeScript/React frontend (Tasks 0–12)** · `done` · `2026-08-15` — 14-task implementation on `claude/typescript-gui`. Python side: `dagi_gui/` package with NDJSON protocol (`protocol.py`), question broker (`interaction.py`), callback adapter (`callbacks.py`), session controller with state machine (`session.py`), catalog/history adapters (`catalog.py`, `history.py`), NDJSON server (`server.py`), sidecar entry point (`__main__.py`), and plan file monitor (`plan_monitor.py`). `agent/history.py` extracted from `tui/history.py` for shared use. TypeScript/Electron side: `desktop/` scaffold with Forge 7.11, Electron 43, React 19, Vite 5, TypeScript 5.8, Zod, Vitest; Zod-validated shared protocol schemas (`src/shared/protocol.ts`); Python process supervisor with crash restart (`src/main/python-supervisor.ts`); hardened BrowserWindow with contextBridge IPC (`src/main/preload.ts`, `src/main/main.ts`); pure `dagiReducer` state machine; `Conversation`, `ToolCard`, `Composer`, `QuestionDialog`, `Sidebar` components with CSS modules dark theme; slash command parser; `App.tsx` full wiring. 692 Python tests + 104 TypeScript tests = 796 total passing.

- **`read_large_text` tool rebuilt on the renamed `read-large-text` subagent directory** · `done` · `2026-08-15` — `.dagi/subagents/read-large-text/main.py` rewritten from the old `SpawnDocumentReaderSubagentTool` (`spawn_document-reader_subagent`) to a clean `ReadLargeTextTool` named `read_large_text`, following the `explore_files` generic-subagent-tool pattern. New `tests/test_read_large_text_tool.py` covers the tool name, `run_subagent` preset dispatch, `custom_instructions` passthrough, and the non-ok status dispatch path. `tests/test_subagent_tools_new.py`'s `_TOOL_NAME_OVERRIDES` entry for `read-large-text` updated from the old pending-rename tool name to `read_large_text`, with the comment reframed as a permanent, intentional naming exception (directly LLM-callable, not following the `spawn_{type}_subagent` convention) rather than a pending rename. `README.md` updated to match (subagents tree entry, new `read_large_text` Tools table row; removed a stale claim that `read` auto-spawns a `document-reader` subagent on oversized reads — no code implements that today). Full suite: 564/564 passing. Known residual: `benchmarks/dagi_eval/config_dagi_eval.yaml` still references the old `spawn_document-reader_subagent` name — out of scope for this task, left for a follow-up.

- **Dynamic context board + `update_task_status`** · `done` · `2026-08-10` — plan status board moved from `_messages[0]` to an ephemeral trailing context injected at API-call time (`_build_active_plan_tail()`); `update_task_status` tool replaces `complete_plan` (regex-updates plan markers, auto-completes plan when all tasks resolved); `complete_plan` tool deleted; `dagi-execute` skill updated to use `update_task_status`; 568 tests passing. (wiki: TODO-012 marked in-progress; remaining items: compaction cache, DeepSeek cache stats, TUI cache visibility.)

- **`is_scanned_pdf` / `_get_page_count` fitz handle leak** · `done` · `verified:2026-08-09` — `services/doc_converter/converter/pdf.py` now calls `.close()` in both functions; handle leak no longer present.
- **`_estimate_worker_count` ZeroDivisionError on `worker_ram_gb=0`** · `done` · `verified:2026-08-09` — `worker_ram_gb` defaults to `4.0`, eliminating the division-by-zero path.
- **`BashTool._killed_by_user` race between `run()` and `force_kill()`** · `done` · `verified:2026-08-09` — lock now properly wraps the `_killed_by_user` read; race window closed.
- **Reading any image file crashes agent loop (`AttributeError` on list result)** · `done` · `verified:2026-08-09` — `isinstance(result, str)` guard confirmed present before `parse_switch_sentinel()` in `agent/loop.py`.
- **`tg/bot.py` `asyncio.get_event_loop()` deprecated — Python 3.14 breakage risk** · `done` · `verified:2026-08-09` — already uses `asyncio.get_running_loop()` at line 73.
- [x] Unify DAGI and Claude Code memory system (2026-08-08) — four-category wiki
  (projects, todos, knowledge, events); canonical SKILL.md protocols in `.dagi/skills/`;
  lint scripts in `.dagi/skills/memory-refresh/scripts/`; DAGI subagents updated to
  reference canonical skills; new `memory-refresh` subagent and Claude Code skill added;
  `spawn_memory-refresh_subagent` added to `.dagi/config.yaml`.

- **Subagent refactor (Tasks 1–10)** · `done` · `2026-08-04` — rewrote subagent architecture: (1) `tools/subagent_api.py` public API (`run_subagent()`, `SubagentResult`, `resume_subagent_by_pid()`); (2) each type migrated to `.dagi/subagents/<type>/main.py` `BaseTool` subclass (9 types: explore_files, web_research, memory-query, memory-add, document-reader, plan, cli, worker, review); (3) import-based discovery via `_discover_subagent_tools()` replacing YAML scanning; (4) `SpawnSubagentTool` / `SpawnCliSubagentTool` deleted; (5) `subagent_main.py` gains `--tools`/`--model-tier` args, reads `agents_md` from config; (6) `DEFAULT_PYTHON_ENV` detected at startup from `CONDA_DEFAULT_ENV`/`VIRTUAL_ENV` and injected into system prompt; (7) `run_subagent` skill added at `.dagi/skills/run_subagent/SKILL.md` for custom workflow scripts; (8) `extend_timeout` updated to call `resume_subagent_by_pid()`. Deferred follow-up: parallel subagent dispatch (`spawn_parallel_subagents` + `wait_subagents` tools).

- **Session history — auto-named session files and `/hist` restore** · `done` · `2026-08-01` — two-part feature. Part 1 (session naming): `SessionTracker.rename_with_slug(slug)` in `agent/session.py` renames `.dagi/logs/session_<ts>.jsonl` → `<ts>_<slug>_logs.jsonl` after the first user message; `AgentLoop._generate_session_slug()` makes a lightweight LLM side-call (≤30 tokens, `max_tokens=30`) to generate a 3–5 word snake_case slug and calls `rename_with_slug()` on fresh sessions only (`_skip_slug_generation=True` for resumptions). Part 2 (`/hist` command): `tui/history.py` provides `load_sessions(logs_dir)`, `load_raw_messages(path)`, `build_turn_list(raw_messages)`, and `HistoryScreen` — a Textual `Screen` with a two-step OptionList picker (session list → turn list within the selected session). `_restore_session()` in `tui/app.py` slices `raw_messages[:turn_index+1]` from the selected session's `session_end` JSONL record and stashes them as `_restore_initial_messages`; the next `/dispatch_agent` call picks them up via `_agent_work`. Old (`session_*.jsonl`) and new (`*_logs.jsonl`) file naming are both supported. 71 tests passing, 0 regressions. Plan: `docs/superpowers/plans/2026-08-01-session-history.md`.

- [x] ~~Hash-anchored `read`/`edit`/`grep` (hashline)~~ — reverted 2026-07-27; smaller models made too many errors with hash anchors. Restored `oldText`/`newText` edit, `cat -n` read, plain `file:line:` grep

- **Post-merge ponytail review cleanup of the subagent handoff/briefing feature** · `done` · `2026-07-26` — adversarial review of the just-merged `subagent-handoff-and-briefing` branch found 5 findings, all fixed directly on top of the merge (no new branch): (1) the `run_subagent`/`resume_subagent` result-dict → tool-return-string dispatch was duplicated 5 ways (`spawn_subagent`, `cli_subagent`, `extend_timeout`, `explore_files`, `web_research`) — extracted to `tools/_handoff_format.py::dispatch_status_result(result, error_prefix, include_escalation=False, include_timeout=True)`, preserving each site's exact behavior including `explore_files`/`web_research`'s pre-existing lack of timeout/resume support (`include_timeout=False`) and `extend_timeout`'s now-removed cross-class `SpawnSubagentTool` import; (2) `SpawnSubagentTool.__init__` parsed the same `subagent_config.yaml` twice (once each for `_parameters`/`_default_handoff_spec`) — now reads `_load_type_data()` once and derives both, keeping `_load_parameters`/`_load_default_handoff_spec` as separately-patchable staticmethods for test compatibility; (3) `agent/loop.py`'s new `_handle_write_handoff` (added when `WRITE_HANDOFF_SENTINEL` short-circuit handling shipped) duplicated the per-tool-call bookkeeping block with two bugs — a dropped list-safety (`__list__:`) conversion and 6 positional params over the 5-param cap — fixed by extracting shared `_bookkeep_tool_call()`/`_finalize_turn()` helpers used by both the normal dispatch loop and the short-circuit path; (4) the `<stem>_unverified.flag` sidecar path was constructed independently in `tools/subagent_main.py` (writer) and `tools/_subagent_runner.py` (reader) — centralized as `tools/_handoff_format.py::unverified_flag_path()`; (5) `tools/write_handoff/_write_handoff.py`'s docstring described the sentinel-termination behavior as "planned" when it had already shipped — corrected to present tense. Full suite: 546/546 passing. Pre-existing `agent/loop.py` size (1172 lines) / `AgentLoop.run` complexity (CC 48) violations noted but explicitly out of scope — spun off as a separate follow-up task.
- **Subagent handoff enforcement + parent-authored briefing/handoff_spec** · `done` · `2026-07-26` — two-stage, 11-task branch. Stage 1: new `WriteHandoffTool` (`tools/write_handoff/`) mirrors `EscalateIssueTool` — handoff path baked in at construction, `run(content)` writes verbatim and returns a `WRITE_HANDOFF_SENTINEL` that `AgentLoop` (`agent/loop.py`) detects and hard-terminates the subagent's turn on, skipping an extra continuation round-trip. Auto-injected in `agent/subagent_tools.py::_tools_from_list()` whenever `handoff_path is not None`, regardless of a type's declared `tools:` list — fixes `explore_files`/`web_research`, which previously had no `write` tool and structurally could not comply. `tools/subagent_main.py::_ensure_handoff()` retries once with a corrective prompt if the handoff file is missing after the subagent's turn; if still missing, scrapes the last assistant message into the file and drops a `<stem>_unverified.flag` sidecar, which `tools/_subagent_runner.py` turns into result status `"ok_unverified"`. Every subagent-spawning tool renders `ok_unverified` as a `⚠️ UNVERIFIED HANDOFF` warning banner via the shared `tools/_handoff_format.py::format_handoff_result()`. Stage 2: `custom_instructions` renamed to `briefing` everywhere (no back-compat shim — internal parameter, no external callers); every subagent type (7 registered types plus the dynamic `custom`/cli path) now accepts optional `briefing` and `handoff_spec` parameters, composed via the shared `tools/_task_envelope.py::wrap_envelope()` into a universal `## Instructions`/`## Output` envelope on top of each type's existing per-type task body (dispatched via a `_BODY_BUILDERS` dict in `tools/spawn_subagent/_spawn_subagent.py::_compose_task()`). Each `subagent_config.yaml` gained a `default_handoff_spec` used when the parent omits `handoff_spec`. Also resolves the long-standing `explore_files` `handoff_file` schema-waste TODO item below, since the handoff path is now parent-only for every type. Full suite: 546/546 passing. Four items logged as out-of-scope residuals (not fixed): subagent prompts never teach `<<END_OF_RESPONSE>>`; `plan/`/`cli/` prompt dirs are vestigial (no `subagent_config.yaml`); `escalate_issue`'s docstring is stale; `_poll_until`'s "exited without writing handoff" branch stays dead by design. Plan: `docs/superpowers/plans/2026-07-26-subagent-handoff-and-briefing.md`.
- **Restructured all 28 DAGI tools into `tools/{name}/` subfolders; extracted document conversion into a standalone `services/doc_converter/` FastAPI microservice** · `done` · `2026-07-25` — two-phase, 12-task branch (`feature/doc-converter-service`). Phase 1: every `tools/{name}.py` file became `tools/{name}/__init__.py` (re-export) + `tools/{name}/_{name}.py` (implementation), zero behavior change, shared helpers (`_path_guard.py`, `_hash_cache.py`, `_subagent_runner.py`, `_plan_parser.py`, `output_filter.py`, `subagent_main.py`) stayed flat. Phase 2: PDF/docx/xlsx/pptx conversion (`tools/_pdf_convert.py`, docling/ocrmypdf/markitdown pipelines) moved out of dagi entirely into `services/doc_converter/` — a standalone FastAPI service with its own conda env (`environment.yml`), own server-side content-addressed cache (`.cache/<sha256>.md`), started via `python -m services.doc_converter` on port 8100. `tools/read/_doc_service.py` is the new HTTP client anti-corruption layer, with its own client-side hash cache (`.dagi/hash_cache/doc_convert/`) to avoid re-uploading unchanged files. `read` tool hard-fails with a clear "start the service" error if it's unreachable — no inline fallback. `tools/_pdf_convert.py` deleted; `PdfConfig`/`load_pdf_config()` removed from `agent/config_loader.py`; `pdf`/`docs` `pyproject.toml` extras removed. New `services:` block in `config.yaml`/`config.example.yaml` maps service name → base URL, read into `AgentConfig.services: dict[str, str]`. Also resolved the long-standing `tests/test_read_tool.py` 500-line-limit TODO item as a side effect of the rewrite (541 → 201 lines). Full suite: 463/463 passing. Resolves the "MCP-analog service extraction" item noted under Potential Areas of Exploration in `AGENTS.md`. Known deferred follow-up: `dev/_verify_local_models.py` still imports the deleted `tools._pdf_convert` module (see Work Queue below).
- **Consolidated `.dagi/agents.md` behavioral guidelines into `AGENTS.md`** · `done` · `2026-07-24` — the two separate per-project files (`AGENTS.md` for human orientation, `.dagi/agents.md` for force-injected behavioral guidelines) are now one. `AGENTS.md` gained a `## Behavioral Guidelines` section (preserved verbatim across routine `update-project-context` runs); `.dagi/agents.md` deleted. Every load path repointed: `agent/loop.py` (`_build_preamble`, `_assemble_system_string`), `tui/utils.py` (`_system_breakdown` token accounting), `tools/subagent_main.py` (`_build_subagent_system_prompt`). `agent/cli_utils.py::_cmd_init` now scaffolds `AGENTS.md` (was `.dagi/agents.md`) with a stub matching the current template — the old stub template had drifted stale (Description/Objectives/Known Issues headers no longer matched what `update-project-context` actually writes). `.dagi/skills/update-project-context/SKILL.md` and `.dagi/prompts/main/main_system.md` updated to match. `README.md` updated (`/init` output list, Tips section). 49 affected tests pass unchanged.
- **Double-click launcher for the portable (conda-packed) distribution** · `done` · `2026-07-24` — new `dagi_run.bat` opens Windows Terminal (falls back to `cmd` if `wt.exe` isn't on `PATH`), activates a sibling `dagi_env` conda-packed environment (`{parent_folder}\dagi_env` next to `{parent_folder}\driverless_agi`), and runs `dagi_launch.py`, which prompts interactively for a model (numbered list read from `config.yaml`'s `models` catalog) and a verbose on/off toggle, then launches `tui.py --model <id> [--verbose]`. Verified `dagi_launch.py`'s config-loading/menu logic directly against `config.yaml` under the `dagi` conda env (Python 3.14) — 7 models listed correctly with the current default marked.
- **`_convert_pdf_digital`'s docling import error mislabeled every dependency failure as "docling is not installed"** · `done` · `2026-07-22` — `tools/_pdf_convert.py`'s `except ImportError` around the docling import caught everything — including transitive dependency failures (e.g. `ImportError: DLL load failed while importing onnxruntime_pybind11_state`, or `torch`/`rapidocr` missing) — and reported them all as "docling is not installed. Install it with: pip install docling", which is both wrong and unhelpful for a broken-DLL case (reinstalling docling doesn't fix a native dependency's DLL). Split into `except ModuleNotFoundError` (checked against `e.name` — only a name rooted at `docling` gets the "not installed" message) and a fallback `except ImportError` that surfaces the real underlying error instead. Also fixed the `_install_fake_docling` test fixture in `tests/test_read_tool.py`, which was silently missing `AcceleratorDevice`/`AcceleratorOptions` since the 2026-07-22 "force cpu mode" change added them — this had been failing 17 of `tests/test_read_tool.py`'s tests on `main` (masked because nobody had re-run the full suite since that commit); new `test_docling_dependency_import_failure_is_not_reported_as_missing` covers the fixed branch. Full suite: 514/514 passing.
- **PDF conversion (docling) and OCR (tesseract via ocrmypdf) now forced to CPU mode** · `done` · `2026-07-22` — `tools/_pdf_convert.py` sets `CUDA_VISIBLE_DEVICES=""` at module import time (re-applied in each `ProcessPoolExecutor` worker on re-import) and `_convert_pdf_digital` explicitly sets `PdfPipelineOptions.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)`, so no GPU/CUDA init is attempted regardless of what's installed on the host.
- **PDF parallel conversion worker count now capped at `page_count // 4`, not 1:1 per page** · `done` · `2026-07-21` — `tools/_pdf_convert.py::_estimate_worker_count()`'s page-count cap changed from `page_count` to `page_count // 4`, so each worker handles at least 4 pages (still floored to a minimum of 1 via the existing `max(1, min(caps))`); avoids paying per-worker process-spawn/docling-load overhead for chunks too small to be worth splitting. `tests/test_read_tool.py::TestEstimateWorkerCount::test_capped_by_page_count` updated to expect 1 worker at `page_count=3` (was 3); new `test_capped_by_page_count_div_4` covers the `page_count=50` → 12 case.
- **`get_or_compute` shared hash cache had a check-then-write race — concurrent workers converting the same PDF could observe a truncated cache file** · `done` · `2026-07-21` — `tools/_hash_cache.py`'s `get_or_compute()` wrote the computed text directly to the final cache path (`path.exists()` check, then `path.write_text()`), so a reader landing between another worker's truncate and completed write would see partial/corrupted content. Fixed by writing to a per-writer temp file (`<hash>.<pid>-<tid>.tmp`) and atomically renaming it onto the final path via `os.replace()` — the final path now only ever shows the pre-existing complete file or the new complete file, never a partial one. Regression test in `tests/test_hash_cache.py::TestGetOrComputeAtomicity` deterministically reproduces the race (monkeypatches `write_text` to split the write in two with a controlled pause) and reliably failed against the old implementation before the fix.
- **Added `environment.yml` for fully pinned, reproducible conda environment** · `done` · `2026-07-21` — generated via `conda env export -n dagi --no-builds` and trimmed of the `prefix:` line; pins every package (core + currently-installed `pdf`/`docs`/`benchmark` extras) to the exact version verified working, complementing `pyproject.toml`'s floor/ceiling version ranges. Does not include the `web`/`telegram` extras (not installed in the current `dagi` env) — documented in `README.md` as a follow-up `pip install -e ".[web,telegram]"` step. `README.md`'s Setup and Dependencies sections updated with `conda env create -f environment.yml` instructions.
- **Scanned-PDF reads broken again with a Tesseract config error — recurrence of the 2026-07-20 env fix, which didn't persist** · `done` · `2026-07-21` — `ocrmypdf.ocr()` raised `TesseractConfigError: Can't open hocr` because the `dagi` conda env's `TESSDATA_PREFIX` (`envs/dagi/share/tessdata`, holding the `.traineddata` language files) never contained the `configs`/`tessconfigs` subfolders — those only exist under the separate `envs/dagi/Library/share/tessdata/`. Fixed by copying `configs`/`tessconfigs` into the `TESSDATA_PREFIX` dir so it's self-contained. Fixing that surfaced two further latent gaps in the (gitignored, machine-local) `models/docling_models/` vendor directory: the layout model (`docling-project--docling-layout-heron/`) was entirely absent, and the tableformer model was missing `tm_config.json` alongside its `.safetensors` weights — both re-downloaded. Verified end-to-end: `convert_pdf()` on `tests/fixtures/pdf/sample_scanned.pdf` now OCRs and extracts real text (25.7k chars) instead of erroring. Since none of this is version-controlled or checked by `scripts/verify_pdf_env.py` (which only checks imports, not tessdata layout or model completeness), it can silently regress again on a fresh env/checkout — see open item below.
- **Retired `requirements.txt` in favor of a single-source `pyproject.toml`** · `done` · `2026-07-20` — `pyproject.toml` now declares the full dependency set as core `dependencies` plus `pdf`/`docs`/`web`/`benchmark`/`telegram` optional-dependency groups (mirroring `requirements.txt`'s prior comments/floors); `requirements.txt` deleted. Updated install instructions in `README.md` (`pip install -e .` / `pip install -e ".[extra]"`), the `scripts/verify_pdf_env.py` docstring, and the `dependency-check` scheduled-task prompt in `.dagi/scheduler/schedule.example.yaml`. Also removed README's stale `pip install langchain` troubleshooting advice while touching that section.
- **PDF read tool verified end-to-end offline (digital + scanned) and a real page-marker bug fixed** · `done` · `2026-07-20` — generated `tests/fixtures/pdf/{sample_digital,sample_scanned}.pdf` fixtures; wired `_convert_pdf_digital` to load TableFormer/heron weights from `models/docling_models` via `PdfPipelineOptions.artifacts_path` (falls back to HF download if absent); fixed `dagi` conda env (missing `libcurl` dependency broke `tesseract.exe`; `TESSDATA_PREFIX` dir was missing `configs`/`tessconfigs` subfolders, breaking ocrmypdf) and downloaded the missing `tableformer_accurate.safetensors` weight file; fixed a real bug where `_convert_pdf_digital` never passed `page_break_placeholder` to `export_to_markdown()`, so real conversions produced zero `<!-- Page N -->` markers (broke `select_pages`, `_renumber_markers`, and the `total_pages` count in `read.py`) — invisible to unit tests since the docling mocks bypassed the real call signature; verified via `HF_HUB_OFFLINE=1` smoke tests through both `convert_pdf()` and `ReadTool.run()`. Known non-blocking limitation: the synthetic hand-drawn table in the digital fixture isn't recognized as table structure by TableFormer (real-world PDF tables are unaffected).
- **No way to catch a broken PDF-dep install (missing Windows DLL) before first PDF read** · `done` · `2026-07-20` — new `scripts/verify_pdf_env.py` eagerly imports docling/torch/onnxruntime/rapidocr/ocrmypdf and reports a VC++ Redistributable hint on Windows DLL-load failures; wired into `README.md` setup + troubleshooting.
- **dagi_eval benchmark: per-run output folders with baseline/gold/unified scoring** · `done` · `2026-07-19` — every `run.py` invocation now creates `.dagi/benchmarks/dagi_eval/logs/<ts>_log/` with `result.jsonl` (per-task rows + `__aggregate__` row), `code/<task>/` copies of the actually-scored solution, and `sessions/<task>/` transcripts; every task always scores cheap no-LLM `baseline_score`/`golden_score` references alongside `recorded_score`, combined into `unified_score` via `scoring.normalize_perf`/`normalize_tokens`.
- **dagi_eval benchmark looked silent/stuck for minutes; CLI never streamed live output** · `done` · `2026-07-19` — `run.py` prints progress around reference/final scoring (each re-times the O(n²) baseline `TIMING_RUNS` times with zero prior output); `agent/log_callbacks.py`'s `build_cli_callbacks()` now wires `on_stream_start`/`on_assistant_text_delta`/`on_reasoning_delta` to print raw deltas live to stdout (previously only TUI streamed; CLI/benchmark waited for each full turn).
- **Telegram bot had no authorization — unauthenticated remote code execution** · `done` · `2026-07-18` — new `TELEGRAM_ALLOWED_CHAT_IDS` allowlist gates `_cmd_start`/`_cmd_clear`/`_cmd_help`/`_handle_message`; loud startup warning if left unconfigured (backwards-compat default).
- **`ask_user` deadlock protection missing on the TUI side (Telegram side was already fixed)** · `done` · `2026-07-18` — `tui/callbacks.py:126` safety timeout changed from `None` to `600`, matching the Telegram-side fix.
- **`tg/bot.py` `UnboundLocalError` in `finally` block — masks original exception** · `done` · `2026-07-18` — added `loop = None` before the `try` block so the `finally` check no longer raises before `AgentLoop` is constructed.
- **`grep` Python fallback dotted-directory bug — already fixed, TODO entry was stale** · `done` · `verified:2026-07-18` — confirmed `tools/grep.py` already scopes the dotted-component check via `p.relative_to(search_path)` (fixed in `bfbdd63`); no code change needed.
- **Memory-subagent wiki sandbox no longer fails open when `memory_root` is unset** · `done` · `2026-07-12` · `verified:2026-07-18` — restructured `build_subagent_registry` so the wiki-sandbox branch is always taken; residual fragility noted for a future defense-in-depth pass.
- **`requirements.txt` floor pins allow installing vulnerable pymupdf/docling-core** · `done` · `2026-07-18` — bumped floors (`pymupdf>=1.26.6`, `docling>=2.75`) to close CVE-2026-3029 / CVE-2026-24009 / CVE-2026-44023 exposure on a clean install.
- **Decompose monolithic `plan-work-review` skill into `grilling` → `plan` → `to-spec` → `dagi-execute`** · `done` · `2026-07-18` — split via subagent-driven development into 4 skills + `agent/_git_branch.py`; post-review fixed a stale `/plan` hardcode in `tui/commands.py`. Spec/plan under `docs/superpowers/`.
- **PDF parallel conversion (map-reduce) — large PDFs convert across multiple worker processes** · `done` · `2026-07-18` — `tools/_pdf_convert.py` gained a `ProcessPoolExecutor` map-reduce path (page-range split → per-chunk docling → merge) for PDFs over 8 pages; new `pdf:` config keys, `psutil` added as core dep.
- **Long-document auto-summarization via document-reader subagent** · `done` · `2026-07-18` — `ReadTool` now spawns a `document-reader` subagent to produce a sectioned digest (cached by SHA-256) instead of truncating oversized reads.
- **`StreamPreview` expands to fill the full window during active streaming** · `done` · `2026-07-18` — `tui/streaming.py`/`tui/app.py`/`tui/callbacks.py` make the live-stream tail size-aware and full-window instead of a fixed 14-line cap.
- **Shared content-addressed hash cache replaces `pdf_cache`/`mkstemp` schemes — fixes unbounded `.dagi/temp/` growth** · `done` · `2026-07-18` — new `tools/_hash_cache.py` unifies PDF and tool-output caching under `.dagi/hash_cache/`, deduping by content hash.
- **`ReadTool` reads PDF documents (converted to markdown via docling)** · `done` · `2026-07-18` — dual pipeline (`docling` for digital, `ocrmypdf`+`docling` for scanned), SHA-256 cache, `pages` filter param.
- **`ReadTool` reads DOCX, XLSX, and PPTX documents (converted to markdown)** · `done` · `2026-07-18` — via optional `markitdown` dependency; PDF explicitly deferred (handled separately above).
- **TUI streaming support — assistant text/reasoning render incrementally as they're generated** · `done` · `2026-07-17` — `AgentLoop._consume_stream()` accumulator + `StreamPreview` widget; new `stream` config key.
- **Unit test coverage added for 6 previously-untested core modules** · `done` · `2026-07-17` — `registry.py`, `session.py`, `_path_guard.py`, `compact.py`, `loop.py` dispatch/compaction, `config_loader.py` (81 new tests).
- **`read` tool now returns `cat -n` style line numbers** · `done` · `2026-07-16` — matches Claude Code's `Read` convention, removing the need to shell out to `bash` for line numbers.
- **`Esc` now force-kills the active bash process (main loop and subagents)** · `done` · `2026-07-16` — shared `agent/_process_kill.py::kill_process_tree()`, wired into `BashTool.force_kill()` and subagent runner.
- **Main agent could complete a subagent handoff without ever reading it — now automatic** · `done` · `2026-07-16` — `SpawnSubagentTool.run()` now inlines the handoff file's content directly into the tool result.
- **TUI went silent after a subagent handoff — looked like the main loop stopped, but it had actually completed normally with no visible signal** · `done` · `2026-07-16` — `on_done` now always writes a `"— turn complete —"` marker to the conversation pane.
- **Review subagent could stall the main agent loop indefinitely — `bash` tool had no timeout, and Windows timeouts didn't work anyway** · `done` · `2026-07-15` — `tools/bash.py` rewritten on `Popen`+`communicate(timeout=...)` with full process-tree kill on timeout.
- **DAGI Eval Benchmark — coding speedup + DS scorecard harness** · `done` · `2026-07-13` — new `benchmarks/dagi_eval/` package, 6 tasks, naive/gold self-test modes.
- **plan-work-review: grill-me thoroughness + explore_files scope creep into planning** · `done` · `2026-07-14` — `grilling` now tracks every decision-tree branch to closure; `explore_files` banned from writing plan-shaped output.
- **Windows toast notifications for TUI** · `done` · `2026-07-14` — `tui/notifications.py::notify()` via `win11toast`, with a foreground-window suppression check.
- **Subagent spawning broken after `cli.py` deprecation — `CliConfig` import error** · `done` · `2026-07-13` — pipe-mode runner extracted to `tools/subagent_main.py`, invoked via `python -m tools.subagent_main`.
- **`ctrl+o` compose mode in TUI** · `done` · `2026-07-12` — expands `PromptInput` to full height, hiding `ConversationPane`.
- **`ctrl+n` / `ctrl+enter` as universal newline bindings in `PromptInput`** · `done` · `2026-07-12` — works around Windows Terminal sending identical bytes for `shift+enter`/`enter`.
- **DAGI git workflow — expanded git toolkit, auto-branch per plan, dagi/\* guard, per-subtask commits** · `done` · `2026-07-12` — `tools/git.py` rewrite, `agent/_git_branch.py::create_task_branch()`, `_dagi_branch_guard()` whitelist.
- **Telegram bot `ask_user` hangs forever when `timeout=None`** · `done` · `2026-07-05` — fixed in `e39e146` with a 600s safety fallback.
- **Telegram bot `loop.finish()` skipped on exception — session log lost** · `done` · `2026-07-05` — moved to a `finally` block in `e39e146`.
- **`python-dotenv` CVE-2026-28684 — symlink file overwrite** · `done` · `2026-07-05` — bumped to `>=1.2.2`.
- **Windows line-ending triple-bug fix in `EditTool` / `WriteTool`** · `done` · `2026-07-05` — CRLF normalization on read/write, `newline="\n"` on write.
- **`review-session` skill reworked — free-text selection + single running cross-session report** · `done` · `2026-07-03` — replaced rigid selection grammar and per-session output files with one accumulating report.
- **`requirements.txt` crawl4ai CVE patch** · `done` · `2026-07-01` — bumped to `>=0.8.7`, fixing 3 CVEs (SSRF, JWT auth bypass, path traversal).
- **5 remaining `DAGI_ROOT` independent computations in cli/tui** · `done` · `2026-06-27` — replaced with `from agent import DAGI_ROOT` across `cli.py`, `tui/app.py`, `tui/commands.py`, `tools/spawn_subagent.py`.
- **`json.loads(tc.function.arguments)` parsed up to 4 times per tool call** · `done` · `2026-06-27` — single parse reused at all dispatch branches in `agent/loop.py`.
- **Subagent discovery only scans project path — misses DAGI root types** · `done` · `2026-06-27` — `_discover_subagent_tools` now scans both DAGI root and project path.
- **Persistent Memory System** · `done` · `2026-06-27` — BM25 removed in favor of subagent-based memory-query/memory-add; wiki restructured.
- **Tool Output Filter — Task 2: wire `filter_tool_output` into `AgentLoop`** · `done` · `2026-06-30` — `agent/loop.py` dispatch now routes through the filter.
- **Tool Output Filter — Task 1: `filter_tool_output()` pure function + tests** · `done` · `2026-06-30` — `tools/output_filter.py`, 16 unit tests.
- **`<<END_OF_RESPONSE>>` position relaxed + continue prompt visibility** · `done` · `2026-06-28` — flag can appear anywhere; TUI shows continuation-injection count.
- **Telegram bot interface** · `done` · `2026-06-28` — new `tg/` package (`bot.py`, `callbacks.py`, `session.py`, `utils.py`), entry point `telegram_bot.py`.
- **Unified `_rebuild_system_prompt()` — eliminate 3-site divergence** · `done` · `2026-06-27` — `_assemble_system_string()` centralizes all 8 assembly steps.
- **`_rebuild_for_reload` silently resets autonomous plan mode to interactive** · `done` · `2026-06-27` — derives `interactive` from `plan_mode_initiated_by` before rebuild.
- **`build_subagent_registry` fails for non-DAGI projects** · `done` · `2026-06-27` — `_load_subagent_config` now tries `project_path` first, then DAGI root.
- **Plan skeleton missing `## Execution Protocol` heading** · `done` · `2026-06-27` — added to the scaffold in `agent/loop.py`.
- **`_subagent_runner.py` pipe buffer deadlock in CLI mode** · `done` · `2026-06-26` — added `_drain_stdout()`, always-started drain thread.
- **`SpawnCliSubagentTool` pipe buffer deadlock** · `done` · `2026-06-26` — replaced hand-rolled `Popen`+`wait()` with `run_subagent()`.
- **`_handle_complete_plan` uses stale `Path(__file__).parent.parent` instead of `DAGI_ROOT`** · `done` · `2026-06-26` — last stale site in `loop.py` fixed.
- **`_rebuild_for_normal_mode` missing `memory_root=` in `create_tool_registry`** · `done` · `2026-06-26` — all three call sites now forward custom memory root consistently.
- **README install & troubleshooting update** · `done` · `2026-06-21` — conda + venv paths, troubleshooting section, TUI-first workflow.

---

## Work Queue

### 🔴 HIGH — Bugs

- **Scanned-PDF OCR/conversion silently regresses on any fresh `doc_converter` env or checkout — nothing verifies tessdata layout or `models/docling_models` completeness** · `priority:medium` · `open:2026-07-21` · `effort:S`
  - **Files:** `scripts/verify_pdf_env.py` (stale — predates the 2026-07-25 service split, needs updating to target the `doc_converter` conda env, see below); `services/doc_converter/environment.yml`'s `doc_converter` conda env (`share/tessdata` vs `Library/share/tessdata`); `models/docling_models/` (gitignored, machine-local)
  - **Problem:** Fixed for the second time on 2026-07-21 (first fixed 2026-07-20, see Completed) — a broken `TESSDATA_PREFIX` (missing `configs`/`tessconfigs`) and an incomplete `models/docling_models/` (missing layout model, missing tableformer `tm_config.json`) both went undetected until an actual scanned-PDF read failed. `scripts/verify_pdf_env.py` only import-checks the PDF dependency packages — it never runs a real tesseract OCR call or checks that `models/docling_models/` has every file each vendored model needs. As of 2026-07-25, PDF conversion moved from `tools/_pdf_convert.py` (dagi env) to `services/doc_converter/converter/pdf.py` (its own `doc_converter` env) — this check still applies but now targets the service's env instead.
  - **Fix:** Extend `scripts/verify_pdf_env.py` (or add a companion check, run inside the `doc_converter` env) to (1) run `tesseract --version`/a trivial hocr conversion to catch `TESSDATA_PREFIX` misconfiguration, and (2) validate `models/docling_models/` has the full expected file set for the layout and tableformer models before `_convert_pdf_digital`/`_convert_pdf_scanned` (now in `services/doc_converter/converter/pdf.py`) are ever called from a real read.
  - **Source:** recurrence found 2026-07-21 while investigating a user-reported tesseract error.

- **`archives/cli.py:1240` `plan_mode_exited` — AttributeError (dead code)** · `priority:low` · `open:9d` · `effort:XS`
  - **File:** `archives/cli.py:1240`
  - **Problem:** `active_loop.plan_mode_exited` is referenced but the attribute was removed on 2026-05-31. **However, `cli.py` was moved to `archives/cli.py` on 2026-07-12 (`d6f7f25`) and is no longer imported or executed by any live code.** This bug exists only in dead code. The live entry points are `tui.py` and `telegram_bot.py`.
  - **Fix:** Delete `archives/cli.py` entirely (tracked under dead code cleanup).
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#2) · Downgraded 2026-07-14: cli.py archived, bug unreachable.

- **`_convert_pdf_scanned` OCR temp file path collides across same-stem PDFs** · `priority:low` · `open:2d` · `effort:XS`
  - **File:** `services/doc_converter/converter/pdf.py` (moved verbatim from `tools/_pdf_convert.py` on 2026-07-25 — bug still present, line numbers may have shifted)
  - **Problem:** `searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"` uses the source filename's stem, not the content hash. Two different scanned PDFs with the same filename stem (e.g., `A/report.pdf` and `B/report.pdf`) produce the same OCR temp path. The `finally` block cleans up the temp file, so sequential calls are safe, but concurrent calls (relevant since parallel conversion is wired up) would corrupt each other's OCR output.
  - **Fix:** Use the content hash for the temp file name: `searchable_path = cache_dir / f"{content_hash}_ocr.pdf"` (pass `content_hash` from the caller).
  - **Source:** `review/2026-07-18`

- **Scheduler `loop.finish()` races with daemon thread on timeout** · `priority:medium` · `open:21d` · `effort:XS`
  - **File:** `scheduler/runner.py:113`
  - **Problem:** `loop.finish()` is called unconditionally after `thread.join(timeout=...)`. On timeout, the daemon thread is still running `loop.run()` — mutating `loop._messages` concurrently. `finish()` calls `tracker.finish(raw_messages=self._messages)` which serializes `_messages` via `json.dumps`. The daemon thread may be appending to `_messages` at the same time — data race on the list. CPython's GIL prevents crashes but the serialized output can be inconsistent (missing or partial messages).
  - **Fix:** Only call `loop.finish()` after confirming `not thread.is_alive()`. On timeout, defer `finish()` or take a snapshot: `msgs_copy = list(loop._messages); tracker.finish(raw_messages=msgs_copy)`.
  - **Source:** `review/2026-06-29`

- **Telegram `build_callbacks` doesn't wire `on_subagent_event_factory` — subagent output invisible** · `priority:medium` · `open:21d` · `effort:S`
  - **Escalated 2026-07-11:** Open 14 days with no fix commit.
  - **File:** `tg/callbacks.py:82-97`
  - **Problem:** `build_callbacks()` in `tg/callbacks.py` doesn't set `on_subagent_event_factory`. The default is `None`, so subagent stdout (worker, review, explore_files, web_research) is silently discarded. When a Telegram user triggers plan-work-review, they see no progress from worker/review subagents — only the final result.
  - **Fix:** Add an `on_subagent_event_factory` that returns a callback forwarding subagent lines via `_send()` (with a `[subagent-type]` prefix and message batching to avoid Telegram rate limits).
  - **Source:** `review/2026-06-29`

---

### 🟠 Architecture Debt

- **`disable-model-invocation` SKILL.md frontmatter flag has no code-level enforcement** · `priority:medium` · `open:2d` · `effort:S`
  - **File:** `agent/skills.py`
  - **Problem:** The flag is intended to mean "never auto-trigger via ordinary user phrasing, only invoke programmatically via `skill(name)`" — used by `to-spec` (SKILL.md frontmatter sets it). Discovered during the 2026-07-18 `plan-work-review` decomposition that `agent/skills.py` parses the flag but never checks it anywhere in the invocation path — any user phrasing that happens to match a skill's trigger words can still fire it, defeating the purpose of the flag for `to-spec` and any future programmatic-only skill.
  - **Fix:** Add an enforcement check at the skill-dispatch site in `agent/skills.py` (or wherever skill triggers are matched against user/model input) that skips skills with `disable-model-invocation: true` unless the invocation is the explicit programmatic `skill(name)` call path.
  - **Source:** code review during `docs/superpowers/plans/2026-07-18-plan-skill-decomposition.md` Task 5, spun off as a standalone follow-up rather than fixed inline (out of scope for a structure-only decomposition).

- **`write_text()` CRLF inconsistency — 10 call sites lack `newline="\n"`** · `priority:medium` · `open:15d` · `effort:S`
  - **Escalated 2026-07-20:** Open 15 days with no fix commit.
  - **Files:** `agent/loop.py:637`, `agent/cli_utils.py:132,140`, `agent/config_loader.py:244`, `tools/cli_subagent.py:82`, `tools/_subagent_runner.py:138`, `tools/subagent_main.py:206`, `tools/escalate_issue.py:57`, `tools/output_filter.py:72`, `scheduler/runner.py:134`, `scheduler/models.py:110`
  - **Problem:** The 2026-07-05 CRLF fix added `newline="\n"` to `EditTool` and `WriteTool`, establishing the invariant "all DAGI-written files have LF on disk." But 10 other `write_text()` call sites still use the Windows default (`newline=None`), which adds `\r` to every `\n` on Windows. Most impactful: plan files (`loop.py:637`), handoff fallbacks (`subagent_main.py:206`), escalation files (`escalate_issue.py:57`), and scheduler output (`runner.py:134`) — all persist on disk and may be read by tools.
  - **Fix:** Add `newline="\n"` to all 10 call sites. Grep `\.write_text\(` to ensure no new sites are missed.
  - **Updated 2026-07-14:** 3 old `cli.py` sites are now dead (archived). 3 new sites added: `agent/cli_utils.py:132,140` (extracted from cli.py), `tools/subagent_main.py:206`, `tools/escalate_issue.py:57`.
  - **Source:** `review/2026-07-05`

- **`tui/commands.py` imports from `cli.py` — layering violation** · `done` · `2026-07-13` — extracted `_cmd_init`/`_skill_invocation_message` into `agent/cli_utils.py` after `cli.py` was archived and broke `/init`/`/plan`.

- **`explore_files` / `memory-query` subagents fail with `ModuleNotFoundError: No module named 'agent'`** · `done` · `2026-07-13` — subagent entry point moved to `tools/subagent_main.py`, invoked via `python -m tools.subagent_main` so `cwd` resolves correctly.

- **Dead code: `ExploreFilesTool`, `WebResearchTool`, `SubAgentRunner`** · `priority:high` · `open:40d` · `effort:S`
  - **Escalated 2026-07-02:** Open 22 days with no fix commit — raised to high.
  - **Files:** `tools/explore_files.py`, `tools/web_research.py`, `agent/sub_agent.py`
  - **Problem:** None of these are registered in `create_tool_registry()` or used anywhere. They are remnants of the old direct-spawn architecture replaced by pipe-based subagents.
  - **Fix:** Audit for external callers; delete if unused.
  - **Updated 2026-07-14:** Removed `tools/plan_subagent.py` (already deleted in `bfbdd63`) and `cli.py:77 _resolve_option` (only exists in `archives/cli.py`, dead code).
  - **Source:** `_todo/todo_2026-06-13.md` #4, `docs/fable/code_review_2026-07-11.md` (#6, #12)

- **Split `agent/loop.py` (1259 lines) into focused modules** · `priority:high` · `open:6d` · `effort:M`
  - **File:** `agent/loop.py` (1259 lines — 2.5× over 500-line standard; was 1114 on 2026-08-03, grew with streaming + plan-mode additions)
  - **Problem:** Mixes core loop execution, plan-mode handling, system-prompt assembly, wiki injection, sentinel parsing, model switching, tool dispatch, compaction, streaming response accumulation, and the live plan-status board rendering. Largest Python file in the live codebase.
  - **Suggested split:** Extract `_handle_enter_plan_mode`/`_handle_exit_plan_mode`/`_handle_complete_plan` → `agent/_plan_mode.py`; extract `_assemble_system_string`/`_build_active_plan_tail`/`_render_plan_status_section`/`_refresh_active_plan_tail` → `agent/_system_prompt.py`; extract `_handle_switch_model`/`_base_config_snapshot` → `agent/_model_switch.py`; extract `_consume_stream` → `agent/_streaming.py`.
  - **Note:** Replaces the old "Split cli.py" item — `cli.py` was moved to `archives/cli.py` on 2026-07-12 and is dead code.
  - **Updated 2026-07-17:** Line count rose from 1013 → 1112 with the addition of `_consume_stream` (streaming support) — added `_consume_stream` to the suggested-split list above rather than treating it as a new backlog item.
  - **Source:** `review/2026-07-14`

- **`agent/prompts.py` still uses independent `Path(__file__).parent.parent`** · `priority:medium` · `open:23d` · `effort:XS`
  - **Escalated 2026-07-16:** Open 19 days with no fix commit.
  - **File:** `agent/prompts.py:5-6`
  - **Problem:** `_PROMPTS_DIR` and `_SUBAGENTS_DIR` are computed via `Path(__file__).parent.parent` — the same pattern that caused 4 confirmed divergence bugs before centralisation in `agent/__init__.py:DAGI_ROOT`. These 2 sites were missed in the 2026-06-27 sweep (`cli.py` ×2, `tui/app.py`, `tui/commands.py`, `tools/spawn_subagent.py`). They work correctly today because `prompts.py` lives inside `agent/`, but any restructuring would break them silently.
  - **Fix:** Replace with `from agent import DAGI_ROOT; _PROMPTS_DIR = DAGI_ROOT / ".dagi" / "prompts"` (and same for `_SUBAGENTS_DIR`).
  - **Source:** `review/2026-06-27`

- **`_parse_frontmatter` duplicated verbatim between `agent/skills.py` and `agent/workflows.py`** · `priority:medium` · `open:30d` · `effort:XS`
  - **Files:** `agent/skills.py:30-42`, `agent/workflows.py:30-42`
  - **Problem:** Identical regex patterns and function body. Any bug fix must be applied twice.
  - **Fix:** Extract to `agent/_frontmatter.py`; import in both files.
  - **Source:** `_todo/todo_2026-06-20.md` B1

- **`_extra_body` construction duplicated in `__init__` and `_handle_switch_model`** · `priority:medium` · `open:31d` · `effort:XS`
  - **Files:** `agent/loop.py:311-317`, `agent/loop.py:732-738`
  - **Problem:** Identical 6-line block in two places. New OpenRouter extensions must be added in both or silently break after a tier switch.
  - **Fix:** Extract `_build_extra_body() -> dict` method.
  - **Source:** `_todo/todo_2026-06-19.md` B2

- **`_tools_from_list` limited to 9 hardcoded tool names** · `priority:medium` · `open:32d` · `effort:S`
  - **File:** `agent/tools.py:51-81`
  - **Problem:** Subagent registries can only reference 9 tools. Any other tool name (e.g., `skill`, `ask_user`, `git_status`) is silently dropped with a warning.
  - **Fix:** Either expand the registry map to cover all tools, or drive subagent registration from `create_tool_registry(tool_names=[...])` and delete `_tools_from_list`.
  - **Source:** `_todo/todo_2026-06-18.md` D2

- **Sidebar `_system_breakdown` reads stale `soul.md` path** · `priority:medium` · `open:32d` · `effort:XS`
  - **File:** `tui/utils.py:66`
  - **Problem:** `_toks(dagi_root / "soul.md")` — `soul.md` was moved to `.dagi/prompts/soul.md`. The old path doesn't exist; sidebar understates system prompt token count by ~150–300 tokens.
  - **Fix:** Change to `dagi_root / ".dagi" / "prompts" / "soul.md"`.
  - **Source:** `_todo/todo_2026-06-18.md` A2

- **`_system_breakdown()` reads disk on every Textual render cycle** · `priority:medium` · `open:32d` · `effort:XS`
  - **File:** `tui/utils.py:58-70` (called from `sidebar.py` render)
  - **Problem:** 3 file reads per render cycle for files that never change during a session.
  - **Fix:** Compute once in `Sidebar.__init__` and cache as `self._sys_parts`.
  - **Source:** `_todo/todo_2026-06-18.md` B1

- **`SkillTool.run()` reloads all skills from disk on every invocation** · `priority:medium` · `open:25d` · `effort:S`
  - **File:** `tools/skill.py:41-46`
  - **Problem:** Every `skill("name")` call creates a new `SkillLoader`, scans all skill root dirs, reads and parses every SKILL.md. `AgentLoop` already has `self.skills` pre-loaded. ~30 file reads per call.
  - **Fix:** Pass the pre-loaded skills list to `SkillTool` at construction time, or cache after first load.
  - **Source:** `_todo/todo_2026-06-25_2.md` A2

- **Falsy-zero coercion in config — `reserve_tokens: 0` silently becomes `16384`** · `priority:medium` · `open:9d` · `effort:XS`
  - **File:** `agent/config_loader.py:133-135`
  - **Problem:** `entry.get("context_window") or raw.get(...)` treats a legitimately configured `0` as "unset" and falls through to the default. `reserve_tokens: 0` (explicitly supported to disable output filtering) and `keep_recent_tokens: 0` can never be set from a per-model entry.
  - **Fix:** Replace `X or Y` with explicit presence check: `entry[k] if k in entry else raw.get(k, default)`.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#9)

- **`AskUserTool` double-timeout race — user answers but tool already returned fallback** · `priority:medium` · `open:9d` · `effort:XS`
  - **File:** `tools/ask_user.py:89-96`
  - **Problem:** The callback (`on_ask_user`) already enforces its own timeout (+60s safety). Wrapping it in a *second* `t.join(timeout=effective_timeout)` means the tool can return the fallback while the user is still in the callback's safety window. The daemon thread is left dangling with a result nobody reads.
  - **Fix:** Let the callback own the timeout. Drop the `t.join` timeout (join without timeout) or call `_on_ask_user` synchronously and rely on the single timeout inside the callback.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#10)

- **`explore_files` schema requires `handoff_file` param the code ignores — token waste** · `done` · `2026-07-26` — resolved as part of the subagent-handoff-enforcement feature (see Completed below): `handoff_file` removed from `explore_files`' `parameters`/`required`; the handoff path is now parent-only for every subagent type, never model-visible.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#11)

- **`WebFetchTool` silently upgrades HTTP→HTTPS for private IP addresses** · `priority:medium` · `open:25d` · `effort:XS`
  - **File:** `tools/web_fetch.py:123`
  - **Problem:** HTTP→HTTPS upgrade excludes `localhost` and `127.0.0.1` but not `192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, or `[::1]`. Agent fails to fetch local dev servers with a misleading error.
  - **Fix:** Expand exclusion regex to cover all RFC-1918 and loopback ranges.
  - **Source:** `_todo/todo_2026-06-25_2.md` A4

- **Benchmark `prepare_workspace` temp dirs never cleaned up — disk leak** · `priority:medium` · `open:0d` · `effort:XS`
  - **Files:** `benchmarks/dagi_eval/harness.py:43-46`, `benchmarks/dagi_eval/run.py:98`, `benchmarks/dagi_eval/scoring.py:232`
  - **Problem:** `prepare_workspace()` creates a temp dir via `tempfile.mkdtemp()` but no caller ever removes it. `build_task_row()` (run.py:98) leaks one workspace per task, and `score_reference()` (scoring.py:232) leaks one per baseline/gold call. A full 6-task sweep leaks 18 temp dirs (6 agent + 12 reference). Over repeated benchmark runs this silently fills `%TEMP%` with multi-MB workspace copies.
  - **Fix:** Add `shutil.rmtree(ws, ignore_errors=True)` in a `finally` block in both `build_task_row` (after `save_task_code` copies the workspace) and `score_reference` (after scoring completes). Or switch to `tempfile.TemporaryDirectory` as a context manager.
  - **Source:** `review/2026-07-20`

- **`combine_results.py` uses `openpyxl` engine but it's not declared as a dependency** · `priority:low` · `open:0d` · `effort:XS`
  - **File:** `benchmarks/dagi_eval/combine_results.py:88`
  - **Problem:** `pd.ExcelWriter(out_path, engine="openpyxl")` requires the `openpyxl` package, which isn't listed anywhere (nor is it a transitive dependency of `pandas`). Running `combine_results.py` on a clean install crashes with `ModuleNotFoundError: No module named 'openpyxl'`.
  - **Fix:** Add `"openpyxl>=3.1"` to the `benchmark` extra in `pyproject.toml`.
  - **Source:** `review/2026-07-20`

- **README architecture tree lists deleted `agent/memory_retriever.py`** · `priority:low` · `open:0d` · `effort:XS`
  - **File:** `README.md:517`
  - **Problem:** The architecture tree still lists `agent/memory_retriever.py` with the description "BM25 wiki retrieval — auto-injects context at session start". This file was deleted when BM25 was removed on 2026-06-27. The retrieval system is now subagent-based (`memory-query`). Misleads contributors about the codebase structure.
  - **Fix:** Remove the line from the architecture tree, or replace it with the current wiki-injection mechanism (`agent/loop.py:_build_wiki_index_context`).
  - **Source:** `review/2026-07-20`

- **README troubleshooting section recommends `pip install langchain` — stale advice** · `done` · `2026-07-20` — removed as part of the `requirements.txt` → `pyproject.toml` consolidation; replaced with a `.env`/`python-dotenv` pointer.
  - **Source:** `review/2026-07-20`

---

### 🟡 Token Efficiency & Observability

- **Session cost tracking always shows `$—`** · `priority:high` · `open:32d` · `effort:S`
  - **File:** `agent/session.py:108`
  - **Problem:** Most API providers (including OpenRouter for many models) don't populate `usage.cost`. Sidebar shows `$—`, `session_end` has `total_cost: null`. No cost visibility makes it impossible to benchmark model tiers.
  - **Fix:** Fall back to computing cost from token counts using a per-model `pricing` section in `config.yaml` (input/output cost per 1M tokens).
  - **Source:** `_todo/todo_2026-06-18.md` C1

- **`thinking_tokens` (reasoning tokens) not recorded in session JSONL** · `priority:high` · `open:30d` · `effort:S`
  - **File:** `agent/session.py:100-118`
  - **Problem:** `completion_tokens_details.reasoning_tokens` is never extracted from API responses. For extended-thinking models (DeepSeek, Claude with thinking), reasoning tokens can be 50%+ of the completion budget — invisible in post-session analysis.
  - **Fix:** Add `thinking_tokens: int | None = None` to `MessageNode`; extract in `record_assistant()`; include `total_thinking_tokens` in `session_end`.
  - **Source:** `_todo/todo_2026-06-20.md` C1

- **Cache hit visibility in TUI sidebar** · `priority:high` · `open:34d` · `effort:S`
  - **Escalated 2026-07-16:** Open 30 days with no fix commit.
  - **File:** `agent/loop.py:480-487`, `tui/sidebar.py`
  - **Problem:** `cache_prompt: true` is sent to OpenRouter, but `usage.prompt_tokens_details.cached_tokens` is never read. Users have no visibility into whether prompt caching is working.
  - **Fix:** Extract `cached_tokens` from `usage.prompt_tokens_details`; pass through `on_token_update`; display in sidebar as `{cached_tok}↩ cached`.
  - **Source:** `_todo/todo_2026-06-16.md` C1

- **Tool result content not truncated in JSONL logs** · `priority:medium` · `open:30d` · `effort:XS`
  - **File:** `agent/session.py:129-135`
  - **Problem:** `record_tool_end(name, result_str)` writes the full result. Compare with `record_subagent_end` which truncates to 500 chars. Large tool results (file reads, grep output, base64) are the primary driver of log disk consumption.
  - **Fix:** Truncate to 2000 chars in `record_tool_end`; record `result_length` for reference.
  - **Source:** `_todo/todo_2026-06-20.md` C2

- **Wiki index system messages accumulate across `run()` calls — unbounded token waste** · `priority:medium` · `open:11d` · `effort:XS`
  - **File:** `agent/loop.py:370-372`
  - **Problem:** `_build_wiki_index_context()` is called at the top of every `run()` call and appends a new system message to `_messages`. In multi-turn CLI/TUI sessions, `initial_messages` carries forward previous messages, so each user turn adds another copy of the wiki index (~200–500 tokens) without removing prior copies. After 10 turns, that's 2000–5000 tokens of redundant context. Compaction will eventually consume them, but they inflate token counts and can trigger premature compaction.
  - **Fix:** Before injecting, scan `_messages` for the last wiki-index system message (identifiable by a prefix like `"## Wiki Index"`) and replace it in-place; or guard with a flag so it's only injected once per `AgentLoop` instance.
  - **Source:** `review/2026-07-09`

- **Token efficiency benchmark harness** · `priority:high` · `open:31d` · `effort:M`
  - **Problem:** No way to measure whether code changes improve or degrade token efficiency. `benchmarks/dagi_eval/` measures task correctness/speedup but not per-task tokens/cost/continuation count.
  - **Fix:** `scripts/benchmark_token_efficiency.py` that parses session JSONL files and produces per-task metrics: `input_tokens`, `output_tokens`, `thinking_tokens`, `tool_call_count`, `continuation_count`, `cache_hit_tokens`.
  - **Source:** `_todo/todo_2026-06-19.md` D3

- **GNHF self-improvement loop — never bootstrapped (85 days stale)** · `priority:high` · `open:85d`
  - **Current:** The `review-session` skill (reworked 2026-07-03 to accept free-text session selection and accumulate cross-session findings into one running report) and `improve-yourself` workflow exist; `.dagi/self-review/` has 5 files all from April 2026; 259 session logs have accumulated (last: 2026-07-19). The entire GNHF feedback cycle has never run. Now 85 days dormant.
  - **Next:** Invoke `review-session` once with "review the 10 most recent sessions" to bootstrap a single cross-session report. Then schedule a weekly run.
  - **Source:** `_todo/todo_2026-06-16.md` C2

---

### 🟢 Features

- **Task scheduler** · `done` · `2026-06-28` — new `scheduler/` package, `tools/schedule_tools.py`, `run_scheduler.bat`, `.dagi/scheduler/` config+log; 40 unit tests.

- **`/stats` slash command for live session diagnostics** · `priority:medium` · `effort:S`
  - Show total tokens (in/out/thinking), cost, tool call histogram, continuation count, compaction count, and session duration. All data already available on `loop.tracker._messages` and `app._stats`.
  - **Source:** `_todo/todo_2026-06-17.md` D1

- **Worker model for compaction (cheaper)** · `priority:low` · `effort:XS`
  - **File:** `.dagi/subagents/compact/subagent_config.yaml`
  - The compact subagent now uses `model_tier: inherit` (inherits parent model via fork-context). If a cheaper worker model is desired, `run_forked_compact_mode` in `tools/subagent_main.py` would need to override the inherited model after credential resolution.
  - **Source:** `_todo/todo_2026-06-16.md` B2

- **Parallel subagent dispatch** · `priority:medium` · `effort:M`
  - **Current:** `_active` dict supports multiple PIDs; TUI relay handles concurrent streams. Missing: a `spawn_parallel_subagents` tool + `wait_subagents(pids, timeout_per)` tool; skill update to use them for independent subtasks.
  - **Source:** `_todo/todo_2026-06-16.md` D3

- **Structured error context for tool failures** · `priority:medium` · `effort:XS`
  - **File:** `agent/registry.py:29-35`
  - Current `except Exception as e: return f"Error: {e}"` loses the exception type. Return `f"Error [{type(e).__name__}]: {e}"` so the LLM can pattern-match on `FileNotFoundError` vs `PermissionError`.
  - **Source:** `_todo/todo_2026-06-26.md` D1

- **Project / Folder Scoping** · `priority:high` · `impact:high`
  - **Current:** Path guard wired into Read/Write/Edit/Grep/Find. Roots hardcoded to `[dagi_root, cwd]`. BashTool unsandboxed.
  - **Next:** Add `allowed_paths` / `blocked_commands` keys to `config.yaml` and read them in `agent/tools.py`.

- **Error Handling & Retries** · `priority:high` · `impact:high` · `partial`
  - **Current:** Transient API error retry with exponential backoff. TUI error-pauses on retry exhaustion. `tools/bash.py` now kills the full process tree (`os.killpg`/`taskkill /T`) on timeout — done 2026-07-15.
  - **Next:** Improve API key validation at startup.

- **Per-project config (work in projects)** · `priority:medium` · `impact:medium` · `partial`
  - **Current:** `resolve_model_config(project_path=...)` merges project config over root. Core config merge infra complete.
  - **Next:** Wire `project_path` into CLI/TUI startup; add `/project <path>` TUI command.

- **Multi-agent / parallel clones** · `priority:medium` · `impact:high`
  - **Current:** Subagents run sequentially. `_active` dict already supports multiple PIDs.
  - **Next:** Prototype parallel dispatch; add `spawn_parallel_subagents` tool.

---

### 🔵 Testing

- **Tests for compaction failure recovery** · `done` · `2026-08-18` — Covered by `tests/test_compact_subagent.py::test_compact_context_swallows_exceptions` (RuntimeError from `run_subagent` swallowed, returns `_NO_COMPACTION`) and `tests/test_compact_integration.py::test_compact_subagent_failure_leaves_surface_intact` (surface unchanged on `is_ok=False`).
  - **Source:** `_todo/todo_2026-06-20.md` E1

- **Tests for `_handle_switch_model` tier transitions** · `priority:medium` · `effort:S`
  - Parametrize default→plan→worker→default and assert each field is correctly set/restored (covers `provider_order`, `cache_prompt`, `model`, etc.).
  - **Source:** `_todo/todo_2026-06-19.md` E1

- **Tests for `_rebuild_for_reload` plan-mode state preservation** · `priority:medium` · `effort:XS`
  - Assert `plan_mode_initiated_by == "dagi"` is preserved after a skill reload in autonomous plan mode.
  - **Source:** `_todo/todo_2026-06-26.md` E1

- **RAM watchdog threshold configurable** · `priority:low` · `effort:XS`
  - **File:** `tests/conftest.py`
  - Hardcoded 70%/90% thresholds cause test failures on high-baseline machines. Read from `DAGI_RAM_WARN_PCT` / `DAGI_RAM_KILL_PCT` env vars.
  - **Source:** `_todo/todo_2026-06-16.md` E1

---

### ⚪ LOW — Housekeeping & Dead Code

- **`dev/_verify_local_models.py` broken — still imports the deleted `tools._pdf_convert` module** · `priority:low` · `open:2026-07-25` · `effort:S`
  - **File:** `dev/_verify_local_models.py`
  - **Problem:** Standalone dev script (not part of the test suite) imports from `tools._pdf_convert`, which was deleted 2026-07-25 when PDF conversion moved to `services/doc_converter/converter/pdf.py`. Currently broken; deliberately deferred during the doc-converter-service migration (Task 12 explicitly out of scope).
  - **Fix:** Rewrite to call the doc-converter service's conversion API (either via `tools/read/_doc_service.py`'s HTTP client or `services/doc_converter/converter/pdf.py` directly, depending on whether the script needs to run against a live service or in-process).
  - **Source:** doc-converter-service migration, `feature/doc-converter-service` Task 12 final verification.

- **Validate project root in system prompt against actual filesystem** · `priority:high` · `review-item`
  - System prompt can contain an incorrect project root (e.g., inside `raw/`), causing all tool paths to resolve incorrectly. Add startup validation in `cli.py`/`main.py`.
  - **Source:** Session `2026-04-26` self-review

- **Extend path guard to cover full dagi-memory tree** · `priority:high` · `review-item`
  - Path guard allows only a single subdirectory of the dagi-memory tree. Allow the full tree.
  - **Source:** Session `2026-04-26` self-review

- **Dead `registry` singleton in `registry.py`** · `priority:low` · `effort:XS`
  - `agent/registry.py:38` — `registry = ToolRegistry()` is never used anywhere. Delete it.
  - **Source:** `_todo/todo_2026-06-18.md` B3

- **Dead `format_skills_for_prompt()` in `agent/skills.py`** · `priority:low` · `effort:XS`
  - `agent/skills.py:117-132` — function is never called; actual formatting is done by `_format_tools_and_skills()` in `loop.py`. Delete.
  - **Source:** `_todo/todo_2026-06-17.md` C2

- **`session.py:finish()` dead `cost_str`/`tools_str` variables** · `priority:low` · `effort:XS`
  - `agent/session.py:219-224` — `cost_str` and `tools_str` are computed but never included in the `print()` call. Either include them or delete.
  - **Source:** `_todo/todo_2026-06-17.md` E3

- **Base64 image data dumped into compaction summarization prompt** · `done` · `2026-08-18` — Resolved by removing `CompactTool` and `_format_messages_for_summary()` entirely. The compact subagent receives the conversation via `spec_for_branch` (structured context spec, not a raw message dump), so base64 list-typed content is never serialized into a summarization prompt.
  - **Source:** `_todo/todo_2026-06-20.md` A2

- **`_estimate_tokens` base64 inflation causes over-aggressive compaction** · `done` · `2026-08-18` — Fixed in `tools/compact/_tail_boundary.py::estimate_tokens()`: list-typed content (`isinstance(content, list)`) returns a 200-token placeholder instead of inflating via `str(content)`.
  - **Source:** `_todo/todo_2026-06-25.md` C1

- **`session_end` JSONL record dumps full `raw_messages` with base64 images** · `priority:low` · `effort:XS` · `images-not-yet-supported`
  - **Files:** `agent/session.py:213-214`, `agent/loop.py:918`
  - **Problem:** A session with 5 images produces a 160KB+ `session_end` line — redundant data already stored in individual `tool_end` records.
  - **Fix:** Strip list-typed content from `raw_messages` before writing, or stop passing them entirely.
  - **Source:** `_todo/todo_2026-06-25_2.md` A3

- **Tests for image-content compaction** · `priority:low` · `effort:XS` · `images-not-yet-supported`
  - Insert a list-typed tool result and assert `_format_messages_for_summary` doesn't include raw base64.
  - **Source:** `_todo/todo_2026-06-20.md` E2

- **9 stale worktrees in `.claude/worktrees/`** · `priority:low` · `effort:XS`
  - Full repo copies from May 2026. Run `commit-commands:clean_gone` or manually remove.
  - **Source:** `_todo/todo_2026-06-20.md` C4

- **Session log rotation** · `priority:medium` · `effort:XS`
  - 250 JSONL files accumulating unboundedly. Add `max_session_logs` config field (default 100) and prune oldest files at `SessionTracker.__init__`.
  - **Source:** `_todo/todo_2026-06-19.md` C1

- **Add pre-flight path check to memory-ingest** · `priority:low` · `review-item`
  - Agent makes 6+ tool calls discovering failing `dagi-memory/` paths. Add pre-flight check to SKILL.md.
  - **Source:** Session `2026-04-26` self-review

- **Fix `pyproject.toml` dependencies** · `done` · `2026-07-20` — superseded by retiring `requirements.txt` entirely: `pyproject.toml` now declares the full dependency set (core + `pdf`/`docs`/`web`/`benchmark`/`telegram` extras), dropping the unused `nicegui`/`markdown`/`matplotlib` and picking up `typer`/`rich`/`textual`/`psutil`/`win11toast`.
  - **Source:** `_todo/todo_2026-06-16.md` F3

- **`langchain` + `langchain-openai` are dead dependencies** · `priority:low` · `open:22d` · `effort:XS`
  - **Escalated 2026-07-16:** Open 18 days with no fix commit. CVE-2026-34070 remains an exposure vector.
  - **Updated 2026-07-20:** CVE-2025-68664 (CVSS 9.3, deserialization "LangGrinch") now also affects the installed `langchain-core`. `requirements.txt` retired in favor of `pyproject.toml` (`0.1.0` consolidation) — dependency now lives at `pyproject.toml`'s core `dependencies` list. README's stale `pip install langchain` advice removed in the same pass.
  - **File:** `pyproject.toml` (core `dependencies`)
  - **Problem:** `langchain>=1.3.4` and `langchain-openai>=1.2.2` are listed as core required deps, but no Python file in the project imports from either package. They add ~100MB of transitive dependencies (numpy, pydantic, aiohttp, etc.) for zero value. Likely a remnant from an earlier architecture. Additionally, CVE-2026-34070 (CVSS 7.5) is a path traversal in `langchain_core/prompts/loading.py` — having the package installed exposes this vulnerability even though DAGI doesn't call it.
  - **Fix:** Remove both entries from `pyproject.toml`'s core `dependencies`.
  - **Source:** `review/2026-06-28`, CVE note added `review/2026-06-30`

- **Dead `ChatSession.lock` field in `tg/session.py`** · `priority:low` · `open:20d` · `effort:XS`
  - **File:** `tg/session.py:13`
  - **Problem:** `ChatSession` declares `lock: threading.Lock = field(default_factory=threading.Lock)` but no code in the `tg/` package ever acquires or releases it. The `busy` flag is the actual concurrency guard. The unused lock misleads readers into thinking thread-safe access patterns are in place when they are not.
  - **Fix:** Remove the `lock` field from `ChatSession` and its `import threading` if no other usage remains.
  - **Source:** `review/2026-06-30`

- **`config.example.yaml:85` stale BM25 reference in `memory_root` comment** · `priority:low` · `open:18d` · `effort:XS`
  - **File:** `config.example.yaml:85`
  - **Problem:** Comment says "persistent knowledge retrieval (BM25)" — BM25 was removed 2026-06-27 in favor of subagent-based grep+traversal. Stale reference confuses readers into thinking BM25 is still used.
  - **Fix:** Change to "persistent knowledge wiki (subagent-based retrieval)".
  - **Source:** `review/2026-07-02`

- **Telegram bot redundant `config.project_path` assignment** · `priority:low` · `open:20d` · `effort:XS`
  - **File:** `tg/bot.py:137`
  - **Problem:** `config.project_path = self._project_path` is redundant — `resolve_model_config` at line 134–136 already passes `project_path=self._project_path`, which calls `replace(cfg, project_path=project_path)` at `config_loader.py:235`. This is the exact pattern cleaned up in CLI/TUI call sites on 2026-06-13 but missed here because the Telegram bot was added later (2026-06-28).
  - **Fix:** Delete line 137 (`config.project_path = self._project_path`).
  - **Source:** `review/2026-06-30`

- **Dynamic tool descriptions** · `priority:medium` · `impact:medium`
  - Tool schemas are static. Prototype runtime tailoring in `agent/tools.py`.

- **Subagent pause propagation** · `priority:low` · `impact:low`
  - ESC pauses parent loop but subagent subprocess continues. Add pause/resume signalling via `proc.send_signal(signal.SIGSTOP)` (POSIX).

- **Sample project for testing** · `priority:medium` · `impact:medium`
  - No example task or expected output for regression testing. Define a representative task.

---

## Self-Improvement Queue

> Entries appended automatically by the `/improve-yourself` workflow after each test run.

> **Long-horizon ideation:** see [docs/fable/self_improve_moonshots.md](docs/fable/self_improve_moonshots.md) (2026-07-11) — 10 far-fetched architecture/process ideas for making DAGI self-learning and self-improving, with a phased roadmap. Recommended starting pair: counterfactual replay engine + experience distillation.

### [High] Bootstrap the self-improvement loop

**Type:** workflow | **Generated:** 2026-05-03

**Root cause:** The `/improve-yourself` workflow has never been run. Review items are waiting. 259 session logs have accumulated; self-review last ran 85 days ago (2026-04-26).

**Quick action:** Invoke `review-session` once ("review the 10 most recent sessions") to produce a single cross-session report, then invoke `/improve-yourself` in a DAGI session.

- [ ] Invoke `review-session` once against the 10 most recent `.dagi/logs/*.jsonl` files (single running report, not per-file)
- [ ] Invoke `/improve-yourself` in a DAGI session
- [ ] Review the verdict block appended below by the workflow
- [ ] Apply the implementation description in `## Tested Improvements`
- [ ] Mark the originating Work Queue item as done

---

## Tested Improvements

> Entries written by the `/improve-yourself` workflow.

---

## Done

(No items — all older entries moved to Archived.)

### Archived (> 30 days)
- BM25 wiki retrieval (superseded by subagent grep+traversal) · `done:2026-06-27`
- Harbor harness Fix A (tempfile.mkdtemp) · `done:2026-06-13`
- Harbor harness Fix B (system_prompt_preamble) · `done:2026-06-13`
- RAM watchdog in test suite · `done:~2026-06-13`
- Soul/agents.md re-injected after plan-mode transitions · `done:2026-06-17`
- TUI loop.finish() on agent completion · `done:2026-06-17`
- Harden compaction failure path · `done:2026-06-21`
- provider_order snapshot/restore on tier switch · `done:2026-06-21`
- DAGI_ROOT centralised in agent/__init__.py · `done:2026-06-21`
- tempfile.mktemp TOCTOU race fixed (3 sites) · `done:2026-06-26`
- SpawnCliSubagentTool migrated to run_subagent() · `done:2026-06-26`
- Temp file leak on subagent timeout · `done:2026-06-26`
- 3-site system-prompt divergence eliminated · `done:2026-06-27`
- Pipe-based subagent architecture · `done:~2026-06-06`
- Transient API error retry · `done:2026-06-08`
- Full Textual TUI · `done:~2026-05-30`
- TUI text wrap + multi-line input · `done:~2026-05-30`
- TUI submodule refactor · `done:~2026-05-30`
- ESC pause button in TUI · `done:~2026-05-31`
- Unified skill invocation · `done:~2026-05-31`
- Plan mode revision loop · `done:~2026-05-31`
- Single response flag (`<<END_OF_RESPONSE>>`) · `done:~2026-05-31`
- Direct `api_key` in config.yaml · `done:~2026-05-29`
- GNHF skill (`git_status`, `git_commit`, `git_rollback`) · `done:~2026-05-03`
- Prompt architecture refactor (`main_system.md`, `agents.md`, `soul.md`) · `done:~2026-05-14`
- Auto compaction (Pi-style) · `done:~2026-05-14`
- Plan mode (read-only planning) · `done:~2026-05-14`
- Web research tools (`web_search`, `web_fetch`, `web_research`, `explore_files`) · `done:~2026-05-14`
- Multi-root search (`FindTool`, `GrepTool`) · `done:~2026-05-14`
