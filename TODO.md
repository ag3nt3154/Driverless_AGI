# TODO

## Completed

- **Decompose monolithic `plan-work-review` skill into `grilling` → `plan` → `to-spec` → `dagi-execute`** · `done` · `2026-07-18`
  - **Problem:** `.dagi/skills/plan-work-review/SKILL.md` was a single 200+ line document owning the entire planning lifecycle (interrogation, spec synthesis, exploration, plan authoring, approval, and the per-subtask worker/review execution cycle) — hard to reason about or reuse pieces of independently, and duplicated planning guidance was scattered across `tools/plan_mode.py` descriptions, `main_system.md`, and the plan-file template in `agent/loop.py`.
  - **Fix:** Executed the pre-approved 8-task plan via subagent-driven development (implementer → spec-compliance review → code-quality review per task): added `get_current_branch()`/`AgentConfig.previous_branch` (`agent/_git_branch.py`, `agent/loop.py`) so `enter_plan_mode` records the branch active before its `dagi/*` branch is created; stripped planning prose out of `tools/plan_mode.py` tool descriptions, `main_system.md`, and the plan-file template; replaced `grill-me` with `grilling` (Mode A interrogation only, chains to `plan`); added `to-spec` (`disable-model-invocation: true`, conversation→`spec.md`); added `plan` (7-step orchestration: enter_plan_mode → `to-spec` → explore_files subagent → author plan.md → approval loop → exit_plan_mode → `dagi-execute`); added `dagi-execute` (write-tests/spawn-worker/spawn-review per-subtask cycle, 2-attempt retry budget, escalation handling, `previous_branch` checkout on completion) and deleted `plan-work-review`. Blind-oracle test model (worker never sees tests, only review subagent does) preserved unchanged — structure-only decomposition.
  - **Post-implementation fix:** the final whole-implementation review (covering the full diff, not caught by any single task's diff) found `tui/commands.py:63` still hardcoded `/plan` to invoke the deleted `plan-work-review` skill by name — the file was untouched by all 8 tasks, so no per-task review could see it. Fixed by removing the special-cased branch so `/plan` falls through to the existing generic `self._skill_map` dispatch, which already resolves it to the new `plan` skill.
  - **Deferred (spun off separately):** code review also flagged that the `disable-model-invocation` SKILL.md frontmatter flag has no enforcement in `agent/skills.py` — any user phrasing can still trigger a skill meant to be programmatic-only (e.g. `to-spec`). This predates the decomposition and is out of scope for a structure-only change; flagged as a standalone follow-up task rather than fixed inline.
  - **Test:** Full suite `pytest tests/ -q` → 514 passed, no regressions, run after every task and again after the post-implementation fix.
  - Spec: `docs/superpowers/specs/2026-07-18-plan-skill-decomposition-design.md`. Plan: `docs/superpowers/plans/2026-07-18-plan-skill-decomposition.md`.

- **PDF parallel conversion (map-reduce) — large PDFs convert across multiple worker processes** · `done` · `2026-07-18`
  - **Problem:** `convert_pdf()` ran the docling pipeline single-process regardless of PDF length — a large multi-hundred-page PDF paid the full model-load + inference cost serially, with no way to use available CPU/RAM headroom.
  - **Fix:** `tools/_pdf_convert.py` gained a map-reduce orchestrator: `_get_page_count`, `_estimate_worker_count` (caps: `os.cpu_count()`, page count, free-RAM budget via `psutil`, optional `max_workers`), `_split_into_chunks`/`ChunkSpec` (page-range splitting via `fitz`), `_convert_chunk` (top-level, picklable, one docling load per worker), `_convert_pdf_parallel` (split → dispatch to `ProcessPoolExecutor` → merge → `_renumber_markers` → cleanup). `convert_pdf()` now detects scanned-vs-digital as before, then checks page count: PDFs over `PDF_PARALLEL_MIN_PAGES = 8` (hardcoded, not config-exposed) route through the parallel path when the estimated worker count exceeds 1; everything else falls back to the original single-process path unchanged.
  - **Config:** new optional `pdf:` key in `config.yaml` — `worker_ram_gb` (default 2.0) and `max_workers` (default `null`/uncapped), loaded via `PdfConfig`/`load_pdf_config()` in `agent/config_loader.py`.
  - **Dependency:** `psutil` added as a **core** (required) dependency in `requirements.txt`, used for free-RAM probing in `_estimate_worker_count`.
  - **Test:** Full suite `pytest tests/ -q` → 510 passed, no regressions.
  - Spec: `docs/superpowers/specs/2026-07-18-pdf-parallel-conversion-design.md`. Plan: `docs/superpowers/plans/2026-07-18-pdf-parallel-conversion.md`.

- **Long-document auto-summarization via document-reader subagent** · `done` · `2026-07-18`
  - **Problem:** When `ReadTool` output exceeded `reserve_tokens`, `output_filter.py` truncated it and told the LLM to "read chunk by chunk with offset/limit" — resulting in 5+ sequential tool calls per large document, each creating new cache artifacts, without the LLM ever gaining holistic understanding. Cascading truncation chains triggered premature context compaction.
  - **Fix:** New auto-summarization gate in `tools/read.py::ReadTool.run()`: when a default read (`offset=1`, `limit=2000`) produces output exceeding `reserve_tokens`, it spawns a `document-reader` subagent (worker-tier model) that reads the full document in ~2000-line chunks with accumulative summarization, performs a verification pass (grep/read to fact-check critical details), and writes a sectioned digest to `.dagi/hash_cache/document_summary/<sha256>_summary.md`. The parent receives this digest instead of truncated output. Digest format: per-section headings with line ranges, token estimates, summaries, and key excerpts — enabling the parent LLM to identify areas of interest and drill in with targeted `read(path, offset, limit)` calls.
  - **New files:** `tools/_document_reader.py` (orchestration: cache check, full-text dump, subagent spawn, result read-back), `.dagi/subagents/document-reader/prompt.md` and `subagent_config.yaml` (subagent definition with read/grep/write tools).
  - **Modified:** `tools/read.py` (added `reserve_tokens`/`project_path` constructor params, auto-summarization gate at end of `run()`), `agent/tools.py` (wires `reserve_tokens`/`project_path` from `AgentConfig` into `ReadTool` constructor in `build_registry`; subagent's `ReadTool` intentionally gets `reserve_tokens=0` via `_tools_from_list` to prevent recursive summarization).
  - **Caching:** Content-addressed via SHA-256 of the numbered full text. Cache hits return instantly. Uses the shared `.dagi/hash_cache/` layout established by the hash cache consolidation.
  - **Test:** `tests/test_document_reader.py` (5 tests: cache hit, cache miss with subagent spawn, fallback on subagent failure, end-to-end via ReadTool, second-read cache hit). `tests/test_read_tool.py` (3 new tests in `TestAutoSummarization`: large file triggers summarization, small file skips, failure falls back to raw text). Full suite passing.
  - Spec: `docs/superpowers/specs/2026-07-18-long-document-reader-design.md`. Plan: `docs/superpowers/plans/2026-07-18-long-document-reader.md`.

- **`StreamPreview` expands to fill the full window during active streaming** · `done` · `2026-07-18`
  - **Problem:** `StreamPreview` (added in the streaming feature, `2026-07-17`) was permanently capped at `max-height: 14` / `TAIL_LINES = 12`, regardless of terminal size — on a tall terminal, most of the window sat empty while a long response streamed in, and only the last 12 lines of the in-progress reply were ever visible.
  - **Fix:** `tui/streaming.py::StreamPreview` gained `expand()` (sets `height: 1fr`, clears `max_height` via `clear_rule` — required moving `max_height` out of `DEFAULT_CSS` into an inline `__init__` rule, since Textual's `clear_rule()` falls back to a CSS-declared value rather than `None`) and an extended `finish()` that restores the collapsed `height: auto`/`max-height: 14` defaults. `_render_tail` is now size-aware only while expanded (uses `self.size.height` instead of the fixed `TAIL_LINES` constant), unchanged while collapsed. `tui/app.py::DagiApp` gained `_expand_stream_preview()`/`_collapse_stream_preview()`, hiding/showing `ConversationPane` in lockstep (mirroring the existing compose-mode toggle). `tui/callbacks.py` defers the expand trigger to the *first rendered delta* of a stream segment (inside `_flush_stream`, not `on_stream_start`) to avoid a blank-screen flash on segments that go straight to a tool call with no visible content; a per-segment `_stream["expanded"]` flag gates the matching collapse on `on_stream_end` so a segment that never expanded doesn't spuriously toggle `ConversationPane` visibility.
  - **Test:** `tests/test_stream_preview.py` (+4 — expand/finish CSS state transitions, size-aware tail rendering via a real `run_test(size=(80, 40))` layout; +1 follow-up — `test_expand_collapse_cycle_on_real_dagi_app` instantiates a real `DagiApp` via `run_test()` and drives `_expand_stream_preview()`/`_collapse_stream_preview()`/`preview.finish()` end-to-end, asserting the real `ConversationPane` and `StreamPreview` widgets transition together, closing the gap left by the callback-wiring tests using a fully mocked `app`), `tests/test_tui_callbacks.py` (+5 — first-delta expand trigger, once-per-segment, collapse-only-if-expanded, per-segment independence). Full suite `pytest tests/ -q` → 475 passed, no regressions.
  - **Not done:** the plan's manual TUI smoke test in a real interactive terminal was not performed — this session had no interactive TTY to drive the live app. All mechanics are covered by the 9 new unit tests above plus the pre-existing streaming test suite; a human should do a quick visual pass before relying on this in daily use.
  - Spec: `docs/superpowers/specs/2026-07-18-stream-preview-expand-design.md`. Plan: `docs/superpowers/plans/2026-07-18-stream-preview-expand.md`.

- **Shared content-addressed hash cache replaces `pdf_cache`/`mkstemp` schemes — fixes unbounded `.dagi/temp/` growth** · `done` · `2026-07-18`
  - **Problem:** Two independent, duplicated content-addressed caching schemes existed: `tools/_pdf_convert.py` wrote to `.dagi/pdf_cache/<sha256>.md`, while `tools/output_filter.py` wrote randomly-named files (`tool_output_*.txt`) into `.dagi/temp/` via `tempfile.mkstemp()`. The latter was never cleaned up by any code path (session finish, loop exit, periodic cleanup) and accumulated unboundedly over heavy tool use (previously tracked as a separate open TODO item).
  - **Fix:** New shared module `tools/_hash_cache.py` exposes `cache_path()`/`get_or_compute()`, a generic SHA-256-content-addressed cache. Both subsystems now write into one unified layout: `.dagi/hash_cache/{pdf,tool_output}/<sha256>.<ext>`. Because cache filenames are now derived from content hash rather than a random suffix, identical tool output is naturally deduplicated instead of re-written — eliminating the unbounded-growth problem without needing eviction logic. `tools/_pdf_convert.py::convert_pdf()` and `tools/output_filter.py::filter_tool_output()` were rewired onto the shared module; `agent/loop.py`'s call site was updated to pass `project_root` directly (dropping the now-unused `self._filter_temp` attribute). Scope is dedup-only by design — no eviction, no migration of old cache directories (they're simply no longer written to), no cross-project sharing.
  - **Test:** `tests/test_hash_cache.py` (9 new tests: path derivation, SHA-256 filenames, dedup on cache hit, LF-only writes, fail-open on `OSError`). `tests/test_read_tool.py` and `tests/test_output_filter.py` updated for the new cache layout. Full suite `pytest tests/ -q` — 465 passed, no regressions (was 422 baseline for this branch).
  - Spec: `docs/superpowers/specs/2026-07-18-shared-hash-cache-design.md`. Plan: `docs/superpowers/plans/2026-07-18-shared-hash-cache.md`.

- **`ReadTool` reads PDF documents (converted to markdown via docling)** · `done` · `2026-07-18`
  - **Problem:** `ReadTool` had no PDF support — PDFs were attempted as UTF-8 text (garbage) or blocked. The prior DOCX/XLSX/PPTX work (also 2026-07-18) deliberately excluded PDF because `markitdown`'s PDF backend had no OCR and collapsed complex tables.
  - **Fix:** New `tools/_pdf_convert.py` module implements a dual pipeline: digital-native PDFs go through `docling` (IBM's deep-learning converter with TableFormer for high-fidelity table extraction including merged/split cells); scanned PDFs are first OCR'd via `ocrmypdf` (tesseract-based, injects invisible text layer at x,y coordinates) then passed through the same docling pipeline. Detection uses `pymupdf` to probe first 3 pages for extractable text (< 50 chars = scanned). Results are cached in `.dagi/pdf_cache/` keyed by SHA-256 of PDF content — repeat reads are instant. New `pages` parameter (e.g. `'1-5,10'`) filters output by `<!-- Page N -->` markers. Output includes a metadata header with cache path for LLM reference. All four dependencies (`docling`, `pymupdf`, `ocrmypdf`, `tesseract`) are optional with graceful degradation.
  - **Test:** `tests/test_read_tool.py` (~33 tests total including prior DOCX/XLSX/PPTX tests) — all via faked modules (`sys.modules` injection), no real PDF fixtures. Covers: page-spec parsing, page selection, scanned-vs-digital detection, digital and scanned conversion pipelines, cache hit/miss/invalidation, dependency degradation, ReadTool integration with pages parameter, error messages. Full suite `pytest tests/ -q --ignore=tests/dagi_eval` — 426 passed, no regressions.
  - Spec: `docs/superpowers/specs/2026-07-18-read-tool-pdf-support-design.md`. Plan: `docs/superpowers/plans/2026-07-18-read-tool-pdf-support.md`.

- **`ReadTool` reads DOCX, XLSX, and PPTX documents (converted to markdown)** · `done` · `2026-07-18`
  - **Problem:** `tools/read.py::ReadTool.run()` only supported UTF-8 text files. `.docx`, `.xlsx`, and `.pptx` files either fell through to `p.read_text(encoding="utf-8")` (garbage/`UnicodeDecodeError`) or were explicitly blocked — the user had to open them outside DAGI to read their content.
  - **Fix:** New optional dependency `markitdown` (Microsoft, MIT) converts all three formats to a single markdown string in memory. `tools/read.py` gained `_MARKITDOWN_EXTS = {".docx", ".xlsx", ".pptx"}` and a `_convert_document(p: Path) -> str` helper (lazy import, raises `RuntimeError` with an install hint if `markitdown` isn't installed); `run()` branches on `ext in _MARKITDOWN_EXTS` before the existing UTF-8 path, then both branches converge on the same `lines` list feeding the existing offset/limit slicing and `cat -n` numbering — so document reads look identical to text reads from the caller's perspective, no new tool parameters. Conversion failures (corrupt file, missing dependency) are caught and returned as a friendly `"Error: Could not convert '<name>': ..."` string, never a raw traceback. `markitdown` is optional — `dagi` starts and runs without it; affected files just return the friendly error until it's installed (`pip install markitdown`).
  - **Scope decision:** PDF was evaluated and explicitly deferred (see below) — `markitdown`'s PDF backend uses layout-heuristic text extraction with no OCR and documented table-fidelity gaps, unlike DOCX/XLSX/PPTX which are structured XML formats with reliable native parsers (`mammoth` for DOCX).
  - **Test:** `tests/test_read_tool.py` (7 tests — per-format conversion success, offset/limit windowing over converted output, missing-dependency friendly error, conversion-exception friendly error, existing text-file behavior unaffected). All via a faked `markitdown` module (`sys.modules` injection) — no real dependency required to run the suite. Full suite `pytest tests/ -q --ignore=tests/dagi_eval` → 400 passed, no regressions (was 393).
  - Spec: `docs/superpowers/specs/2026-07-18-read-tool-document-formats-design.md`. Plan: `docs/superpowers/plans/2026-07-18-read-tool-document-formats.md`.

- **TUI streaming support — assistant text/reasoning render incrementally as they're generated** · `done` · `2026-07-17`
  - **Problem:** `agent/loop.py`'s `AgentLoop.run()` called `client.chat.completions.create()` without `stream=True` — the full model response only became available after generation finished, so the TUI sat idle for the entire generation time and then showed the whole reply at once.
  - **Config:** new `stream` key in `config.yaml`, global + per-model override (same pattern as `thinking`). `AgentConfig.stream` dataclass default is `False` (so the ~25 existing test files / benchmark harness that construct `AgentConfig(...)` directly and mock a blocking `create()` response keep working unchanged); `agent/config_loader.py::_build_config_from_entry` resolves the config-file default to `True`, so every real entry point (TUI, `main.py`, `telegram_bot.py`, scheduler) streams unless `config.yaml` explicitly sets `stream: false`.
  - **Core accumulator:** `AgentLoop._consume_stream()` (new, `agent/loop.py`) turns a chat-completions chunk iterator into the exact same `(message, usage)` shapes the blocking path already produced — `message.content`/`.tool_calls`/`.reasoning_content`, `usage.prompt_tokens` etc. — so every line of code after the API call (ghost-response retry check, tool dispatch, `tracker.record_assistant`, `on_token_update`, compaction trigger) runs completely unchanged, streaming or not. Fires 4 new no-op-default `AgentCallbacks` fields (`on_stream_start`, `on_stream_end`, `on_assistant_text_delta`, `on_reasoning_delta`) as chunks arrive — defaults mean `main.py`/`telegram_bot.py`/scheduler need zero changes. `run()`'s API-call block now branches on `config.stream`, requesting `stream_options={"include_usage": True}`; mid-stream transport drops (the except tuple now also catches `httpx.HTTPError`, not just `openai.APIConnectionError`/`APITimeoutError`) retry the whole call via the pre-existing connection-error backoff path, discarding partial accumulation; an empty/ghost stream is caught by the pre-existing ghost-response retry unchanged.
  - **TUI rendering:** `ConversationPane` extends Textual's `RichLog`, which is append-only — repeatedly writing partial text would leave dozens of stale partial-markdown copies in scrollback instead of one clean message. New `tui/streaming.py::StreamPreview` widget (hidden via `DEFAULT_CSS` until first shown) renders a live tail (reasoning before text, trimmed to the last 12 lines) below the conversation pane while a turn streams, then hides again on `on_stream_end` — the same final `Panel`/`Markdown` write into `ConversationPane` that existed before streaming still happens via the unchanged `on_assistant_text`/`on_reasoning` calls. `tui/callbacks.py::build_callbacks` wires the 4 delta callbacks to the widget, throttled to ≥50 ms **per delta kind** (text and reasoning tracked with separate clocks — a single shared clock silently drops the first delta of one kind whenever it lands microseconds after a delta of the other kind in the same burst) so fast token streams don't flood the UI thread; every flush (throttled or not) sends the full accumulated string, so a skipped refresh never loses data, and `on_stream_end` forces one final unthrottled flush before hiding.
  - **Test:** `tests/test_config_loader.py::TestStreamResolution` (4), `tests/test_agent_callbacks.py::TestStreamingCallbackDefaults` (1), `tests/test_streaming_loop.py` (15 — chunk accumulation, streaming `run()` end-to-end, tool-call reassembly across chunks, mid-stream `openai.APIConnectionError`/raw `httpx.HTTPError` retry-then-succeed and exhausts-and-raises, ghost-stream retry, non-streaming path byte-for-byte unchanged), `tests/test_stream_preview.py` (5 — widget visibility/rendering/tail-trimming), `tests/test_tui_callbacks.py::TestStreamingWiring` (4 — reset-on-start, per-kind-throttle accumulation, forced-flush-on-end, no cross-turn leakage). Full suite `pytest tests/ -q --ignore=tests/dagi_eval` → 393 passed, no regressions (`tests/dagi_eval/` excluded — pre-existing, unrelated `ModuleNotFoundError: numpy` in this conda env).
  - **Not done:** the plan's manual TUI smoke test with a real billed model call was intentionally skipped, per explicit standing instruction not to make real LLM calls without permission — declined when asked. All mechanics are covered by the 29 mocked unit tests above.
  - Spec: `docs/superpowers/specs/2026-07-17-dagi-streaming-design.md`. Plan: `docs/superpowers/plans/2026-07-17-dagi-streaming.md`.

- **Unit test coverage added for 6 previously-untested core modules** · `done` · `2026-07-17`
  - **Problem:** `agent/registry.py` (`ToolRegistry`), `agent/session.py` (`SessionTracker`), `tools/_path_guard.py` (`validate_path`) had no dedicated test files at all. `tools/compact.py` (`CompactTool`) and `agent/loop.py`'s tool-dispatch/compaction-trigger paths only had incidental coverage (2-3 tests each) buried inside `tests/test_continuation.py`. `agent/config_loader.py` had key-resolution tests (`tests/test_config_loader.py`) but no coverage for `load_raw_config`, `list_model_ids`, `_load_project_config`, `_merge_configs`, `resolve_model_config`'s resolution order/worker-model wiring, or `save_config`.
  - **Added:** `tests/test_registry.py` (16 tests — register/duplicate, schema listing, `filter_to`, dispatch incl. unknown-tool and exception-swallowing), `tests/test_session_tracker.py` (14 tests — JSONL record shape, child-tracker roll-up/depth-tagging, `finish()` aggregation), `tests/test_path_guard.py` (10 tests — sandbox-mode bypass, directory vs. exact-file allow-roots, `..`-traversal rejection, multi-root matching), `tests/test_compact_tool.py` (18 tests — unbound-`RuntimeError`, no-safe-cut-point, threshold gating, progressive re-summarisation, callback firing, failure rollback, `run()` wrapper, module-level helpers), `tests/test_agent_loop.py` (12 tests — tool-call dispatch/message-history/callbacks/tracker recording, unknown-tool handling, multi-tool-call turns, compaction-trigger token-budget gating), `tests/test_config_resolution.py` (17 tests — raw config loading, project-config merge/override, `resolve_model_config` resolution order and worker/advanced model wiring, `save_config` round-trip).
  - **Gotcha found while writing tests:** `CompactTool.compact()`'s safe-cut-point scan (`tools/compact.py` lines ~166-173) requires at least 2 full user/assistant exchanges after the system message before any cut point exists — a 3-message conversation (system+user+assistant) can never compact even with `force=True`, since the scan never considers the *last* message as a candidate cut boundary (no tail would remain). Not a bug — by design there must be something left in the kept tail — but any test (or future caller) using a short synthetic conversation needs to account for it.
  - **Gotcha found in `AgentLoop`:** the token-budget compaction check (`agent/loop.py` lines ~607-614) only runs after a tool-calling turn; a turn that ends via `<<TASK_END>>`/`<<END_OF_RESPONSE>>` with no tool calls returns immediately beforehand and never reaches the compaction check that iteration.
  - **Test:** all 6 new files pass standalone (`pytest tests/test_registry.py tests/test_session_tracker.py tests/test_path_guard.py tests/test_compact_tool.py tests/test_agent_loop.py tests/test_config_resolution.py -q` → 81 passed). Full suite `pytest tests/ -q` (excluding `tests/dagi_eval/`) → 369 passed, no regressions.

- **`read` tool now returns `cat -n` style line numbers** · `done` · `2026-07-16`
  - **Problem (user report):** dagi "often has to resort to bash to get the correct line numbers of a file" — `tools/read.py::ReadTool.run()` sliced and rejoined lines with no numbering at all, while `grep.py` already emits correct `file:line` output. Any time dagi read a chunk and needed to cite or `edit` a specific line, it had to fall back to a separate `bash` call (`grep -n`/`cat -n`) to recover line numbers.
  - **Fix:** `ReadTool.run()` now enumerates the selected slice starting at `offset` and prefixes each line `{lineno:6d}\t{content}`, matching Claude Code's own `Read` tool convention. Tool description updated to state the prefix isn't part of file content (so it isn't mistaken for something to include in `edit`'s `oldText`). Confirmed `tools/output_filter.py`'s truncation logic is format-agnostic (size-based only), so no downstream breakage.
  - **Test:** manual verification (offset=1 and offset=50 both number correctly); full suite `pytest tests/ -q` → 312 passed.

- **`Esc` now force-kills the active bash process (main loop and subagents)** · `done` · `2026-07-16`
  - **Problem:** `Esc` only set `AgentLoop._pause_event`, checked between iterations — a hung or long-running `bash` command (main loop or inside a worker/review subagent) couldn't be interrupted; you had to wait out its timeout.
  - **Fix:** Extracted `BashTool._kill_tree` into a shared `agent/_process_kill.py::kill_process_tree()`. `BashTool` gained a lock-protected `force_kill()` that kills its in-flight `Popen` and makes `run()` return `[killed by user]`. `tools/_subagent_runner.py` gained `force_kill_active_subagents()`, which kills every process tree in the existing `_active` dict. `tui/app.py::action_pause()` calls both before `loop.pause()`.
  - **Scope:** at most one of "main-loop bash" or "an active subagent" is ever running at once (the main loop blocks synchronously on subagent polling), so `Esc` doesn't need to disambiguate — it attempts both kills unconditionally and whichever has nothing active is a no-op.
  - **Test:** `tests/test_process_kill.py` (shared helper, real subprocess kill), `tests/test_bash_tools.py::TestForceKill` (2 tests — real subprocess interrupted mid-run, no-op when idle), `tests/test_subagent_runner.py::TestForceKillActiveSubagents` (2 tests — kills every tracked process tree, no-op when none active). Full suite `pytest tests/ -q`: 305 passed (7 pre-existing failures in `tests/dagi_eval/` are unrelated — missing `numpy` in this env, not caused by this change).
  - Spec: `docs/superpowers/specs/2026-07-16-esc-force-kill-bash-design.md`. Plan: `docs/superpowers/plans/2026-07-16-esc-force-kill-bash.md`.

- **Main agent could complete a subagent handoff without ever reading it — now automatic** · `done` · `2026-07-16`
  - **User request:** "when the subagent is done, the main agent should always read the subagent's handoff.md -> this should be default behavior." Previously this relied entirely on prompt-following — `spawn_*_subagent` tools returned only `"Subagent completed. Handoff written to: <path>"`, and `.dagi/skills/plan-work-review/SKILL.md` had to separately instruct "Once the tool returns, read the handoff file it reports." Nothing enforced it in code.
  - **Fix:** `tools/spawn_subagent.py::SpawnSubagentTool.run()` now reads the handoff file and inlines its full content directly into the tool result via a new `_format_ok_result()` static method, instead of just the path — so the content is always present in the main agent's context the moment the tool call returns, with no separate `read` call needed. Falls back to a `(could not read handoff file: ...)` note (never raises) if the file is missing/unreadable. `tools/extend_timeout.py::ExtendSubagentTimeoutTool.run()` (the resume-after-timeout path) now calls the same `_format_ok_result()` so both entry points to an "ok" subagent result behave identically. Large handoffs still go through the existing `filter_tool_output` truncation in `agent/loop.py` like any other tool result.
  - **Test:** `tests/test_spawn_subagent_tool.py::TestRunMethod::test_run_includes_handoff_content_by_default` and `::test_run_reports_unreadable_handoff_without_raising` — written first, confirmed RED, then GREEN after the fix. Full file: 25/25 pass (verified via direct invocation — see RAM watchdog note below).
  - **Note:** same `pytest` RAM-watchdog environment issue as the entry above — verified via direct test invocation instead of `pytest`.

- **TUI went silent after a subagent handoff — looked like the main loop stopped, but it had actually completed normally with no visible signal** · `done` · `2026-07-16`
  - **Symptom (user report):** "subagents sometimes stopped the main loop after handing over" — observed across worker, review, and explore_files subagents. Follow-up confirmed: input was re-enabled (worker thread had exited normally, no exception, no pause), but nothing appeared in the conversation pane — total silence.
  - **Root cause:** three independently-reasonable behaviors converged. (1) `agent/loop.py`'s `<<END_OF_RESPONSE>>` flag handling legitimately ends a turn — including right after a subagent hands off, when the model may have nothing further to add that turn. (2) `tui/callbacks.py`'s `on_assistant_text` silently no-ops when the stripped text is empty/whitespace. (3) `on_done` (also in `tui/callbacks.py`) never wrote anything to the conversation pane — it only called `notify()`, an OS toast. (4) `tui/notifications.py::notify()` itself skips the toast whenever the console window has OS focus (added 2026-07-14 to avoid redundant popups) — the common case, since the user is actively watching the subagent stream. Net effect: a terse/empty final turn + a focused window = zero visible indication the turn ended, indistinguishable from a hang.
  - **Fix:** `tui/callbacks.py::on_done` now always writes a `"— turn complete —"` marker to the conversation pane via `conv.append_info`, in addition to the (possibly-suppressed) toast — so turn completion is never silent regardless of window focus or response text.
  - **Test:** `tests/test_tui_callbacks.py::TestNotifyWiring::test_on_done_always_writes_visible_conversation_marker` — written first, confirmed RED (`on_done` only called `notify`), then GREEN after the fix.
  - **Note:** `pytest` could not be run directly in this environment during this fix — `tests/conftest.py`'s RAM watchdog fires on setup whenever system RAM is above 70%, which it was throughout (72–75%), unrelated to this change. Verified instead by invoking the test bodies directly (`TestNotifyWiring` methods called without the pytest runner) — all 5 tests in the file pass.

- **Review subagent could stall the main agent loop indefinitely — `bash` tool had no timeout, and Windows timeouts didn't work anyway** · `done` · `2026-07-15`
  - **Symptom (user report):** "review subagent stops the main agent loop for dagi."
  - **Root cause 1:** `tools/bash.py`'s `BashTool.run()` passed `timeout=None` to `subprocess.run` whenever the LLM omitted an explicit `timeout` arg. The review subagent's prompt (`.dagi/subagents/review/prompt.md`) says to "run the unit tests" with no instruction to always pass a timeout. A hanging test command (dev server, watch mode, stdin wait) blocked the review subagent's own inner `AgentLoop` forever, so its subprocess never exited/wrote a handoff — which meant `tools/_subagent_runner.py::_poll_until()` (called synchronously from the *main* `AgentLoop.run()` loop via `spawn_review_subagent`) blocked the entire main loop for up to the 30-minute subagent timeout, repeatable per call.
  - **Root cause 2 (deeper, Windows-specific):** even when an explicit `timeout` *was* passed, `subprocess.run(shell=True, capture_output=True, timeout=X)` on Windows did not reliably enforce it for command trees with grandchild processes (e.g. `npm test` → `node.exe`). Killing the immediate `cmd.exe` shell on timeout doesn't release the grandchild's inherited stdout/stderr pipe handles, so `communicate()`'s pipe-drain blocks until the grandchild naturally exits — timeout raised only after the full runtime, not the configured deadline. Reproduced directly: `subprocess.run(cmd, shell=True, capture_output=True, timeout=0.5)` took 5.1s to raise `TimeoutExpired` for a 5s child.
  - **Fix:** `tools/bash.py` rewritten to use `subprocess.Popen` + `communicate(timeout=...)` directly (not `subprocess.run`), with a default timeout (`BashTool.DEFAULT_TIMEOUT = 120.0`, still overridable per-call). On `TimeoutExpired`, kills the *whole* process tree — `taskkill /F /T /PID <pid>` on Windows, `os.killpg(..., SIGKILL)` on POSIX (process started with `CREATE_NEW_PROCESS_GROUP` / `start_new_session=True` respectively) — then drains the pipes with a bounded 5s grace period before giving up and returning a clear `[timed out after Xs and was terminated]` message instead of hanging.
  - **Test:** `tests/test_bash_tools.py::test_hanging_command_is_bounded_by_default_timeout` — spawns a 5s Python sleep with `default_timeout=0.5` and asserts it returns within 4s. Written first, confirmed RED (`TypeError: unexpected keyword argument 'default_timeout'`), then GREEN after the fix. Full suite: 297 passed (7 pre-existing failures in `tests/dagi_eval/` are unrelated — missing `numpy` in this env, not caused by this change).
  - **Resolves TODO items:** "`BashTool.run()` doesn't handle `subprocess.TimeoutExpired`" and the `os.killpg` half of "Error Handling & Retries" (both below, now removed/updated).

- **DAGI Eval Benchmark — coding speedup + DS scorecard harness** · `done` · `2026-07-13`
  - New `benchmarks/dagi_eval/` package: subprocess entry executor, `scoring.py` (output-match/timing/ROC-AUC), `harness.py` (workspace prep, canned-solver + real-agent invocation), `run.py` CLI (`--model`, `--task`, `--solver agent|gold|naive`, `--label`, `--results`).
  - 6 tasks: `coding_01_logpipe`, `coding_02_querymini`, `coding_03_simgrid`, `coding_04_dedup`, `coding_05_sheetcalc` (coding-speedup, each with a naive baseline + a fast gold solution and a `gold_min_speedup` gate), and `ds_01_tabular` (DS, ROC-AUC vs. a frozen synthetic dataset with a deliberate leaky-feature trap column).
  - No composite score by design — a scorecard row (`coding_score`, `ds_score`, tokens/cost/wall-time) is appended to `benchmarks/dagi_eval/results.jsonl` per run.
  - `--solver naive|gold` self-test modes make zero real LLM calls (canned solutions only) — used throughout development and for the final full-sweep self-test instead of a real agent run.
  - Full harness self-test (`--solver naive` then `--solver gold`, all 6 tasks): naive speedups 0.81-1.01 / `ds_score=1.0`, gold speedups 49.8-1628.5 (all clearing their task's `gold_min_speedup`) / `ds_score=1.537`; `errors: []` on both runs. Full suite `pytest tests/ -q` → 280 passed.
  - Added `numpy`/`pandas`/`scipy`/`scikit-learn` as an optional dependency group in `requirements.txt` (used by `coding_03/04/05` gold solutions and `ds_01_tabular`).
  - Spec: `docs/superpowers/specs/2026-07-06-dagi-eval-benchmark-design.md`. Plan: `docs/superpowers/plans/2026-07-06-dagi-eval-benchmark.md`.
  - **Not done / follow-up**: Task 11's optional "first real benchmark run" smoke test (Step 4 of the plan, needs an API key and makes a real billed LLM call) was intentionally skipped per explicit standing instruction not to make real LLM calls without permission — the harness is otherwise fully self-tested and ready for a real `--model` run whenever budget is available.

- **plan-work-review: grill-me thoroughness + explore_files scope creep into planning** · `done` · `2026-07-14`
  - **Problem 1 — shallow grilling:** `.dagi/skills/plan-work-review/SKILL.md` Step 2 let a user saying "ready"/"proceed" end the grill-me interrogation regardless of how few branches had actually been covered, and grill-me's own Stage 5 closure criterion ("remaining unknowns are non-blocking") was subjective enough to let it converge after a couple questions.
  - **Fix:** `.dagi/skills/grill-me/SKILL.md` Stage 2 now requires tracking every decision-tree branch explicitly and resolving each with a decision or a stated out-of-scope reason; Stage 5 requires re-checking that full branch list before closing and explicitly says user impatience ("ready"/"let's go") isn't a substitute. `plan-work-review/SKILL.md` Step 2 now only exits on grill-me's own Phase 3 closing summary or an explicit override ("skip the grilling").
  - **Problem 2 — explore_files writing plan-shaped content:** `.dagi/subagents/explore_files/prompt.md` had no explicit ban on plan-shaped output, and `plan-work-review/SKILL.md` Step 3 told the main agent to look for "Findings and Recommendations" sections that don't exist in the actual handoff template (Summary/Citations/Notes) — encouraging solution-proposing content instead of pure exploration. Confirmed via `tools/subagent_main.py:_build_subagent_system_prompt` that `.dagi/subagents/<type>/prompt.md` is the live system prompt, not just documentation.
  - **Fix:** `explore_files/prompt.md` now explicitly bans ordered steps/todo lists/"recommended approach" content with a self-check example; `plan-work-review/SKILL.md` Step 3 section names corrected to match the real template and instructs the main agent to treat any plan-shaped subagent output as raw findings, not the plan itself.

- **Windows toast notifications for TUI** · `done` · `2026-07-14`
  - **Fires at three points:** `ask_user`, interactive `show_plan`, and end-of-response (`on_done`) via `tui/notifications.py::notify()`
  - **New callback:** `AgentCallbacks.on_plan_shown` distinguishes plan review from a generic question
  - **Scope:** `tui.py` only — `cli.py`, `telegram_bot.py`, subagents, and the scheduler are unaffected
  - **Dependency:** `win11toast`, lazily imported and exception-guarded — degrades to silent no-op if missing or non-Windows
  - **Foreground check (2026-07-14):** `notify()` skips the toast when the TUI's own console window already has OS focus (`_tui_window_is_foreground()` compares `GetForegroundWindow()` to `GetConsoleWindow()` via `ctypes`). If the check itself fails for any reason, it fails open and still sends the notification.

- **Subagent spawning broken after `cli.py` deprecation — `CliConfig` import error** · `done` · `2026-07-13`
  - **Symptom:** every `spawn_*_subagent` tool call failed with `ImportError: cannot import name 'CliConfig' from 'agent.config_loader'`. The 2026-07-12 "deprecate cli" commit (`d6f7f25`) moved `cli.py` → `archives/cli.py` and removed `CliConfig`/`load_cli_config` from `agent/config_loader.py`, but `tools/_subagent_runner.py` still shelled out to `archives/cli.py` to run piped subagents — a live path, not just the deprecated interactive REPL.
  - **Fix:** extracted the pipe-mode subagent runner (`_run_subagent_pipe_mode` and its helpers — `_apply_worker_config`, `_apply_advanced_config`, `_extract_final_assistant_text`, `_build_pipe_callbacks`, `_build_subagent_system_prompt`) out of `archives/cli.py` into a new standalone entry point, `tools/subagent_main.py`, with a plain `argparse` CLI (`--subagent-type`, `--task-file`, `--handoff`, `--project`, `--model`, `--system-prompt-file`). `tools/_subagent_runner.py` now spawns it via `python -m tools.subagent_main` (module invocation, not a file path — running it by path would put `tools/` at `sys.path[0]` and let `tools/copy.py` shadow the stdlib `copy` module, which `dataclasses` imports internally). `archives/cli.py` is now truly dead — nothing in the live codebase imports or executes it.
  - **Related:** also fixed `/init` and `/plan` in the TUI, which had the same "still imports from deprecated `cli.py`" problem — see `agent/cli_utils.py`.

- **`ctrl+o` compose mode in TUI** · `done` · `2026-07-12`
  - `DagiApp._input_expanded: bool = False` state added to `__init__`.
  - `BINDINGS` gains `("ctrl+o", "toggle_compose", "Compose")`.
  - `action_toggle_compose()` hides `ConversationPane` and expands `PromptInput` to full height (`"1fr"`); second press restores normal layout (height=8, conversation visible).
  - `on_prompt_input_submitted` auto-collapses compose mode at the very top, before any submit-path branching, so all paths (ask_user, inject_and_resume, slash commands, agent dispatch) receive the normal layout.
  - All 260 tests pass. Commit: `f4ac818`.

- **`ctrl+n` / `ctrl+enter` as universal newline bindings in `PromptInput`** · `done` · `2026-07-12`
  - Windows Terminal sends identical bytes for `shift+enter` and `enter`, making the existing `shift+enter` newline binding unreliable.
  - Fixed by collapsing `shift+enter`, `ctrl+n`, `ctrl+enter` into one `elif event.key in (...)` branch in `tui/prompt_input.py`.
  - `ctrl+n` (ASCII 0x0E) is always distinct from Enter (0x0D), making it a reliable newline key.
  - New: `tests/test_prompt_input_multiline.py` — 5 Textual pilot tests covering all three newline keys, submit on non-empty, and no-submit on empty. All passing.

- **DAGI git workflow — expanded git toolkit, auto-branch per plan, dagi/\* guard, per-subtask commits** · `done` · `2026-07-12`
  - `tools/git.py` rewritten: `git_diff`, `git_log`, `git_branch`, `git_checkout`, `git_add`, `git_reset` added; `git_commit` now requires explicit `git_add` staging first (no more implicit `add -A`); `git_rollback` removed from the agent registry entirely (no replacement tool).
  - `agent/_git_branch.py` (new): `create_task_branch(cwd, task_summary, plan_id)` auto-creates and checks out `dagi/<slug>_<plan_id>` from HEAD when `enter_plan_mode` is called; skips silently (not an error) outside a git repo.
  - `_dagi_branch_guard()` whitelist restricts `git_add`/`git_commit`/`git_reset` to `dagi/*` branches; `git_status`/`git_diff`/`git_log`/`git_branch`/`git_checkout` remain unrestricted on any branch.
  - `.dagi/skills/plan-work-review/SKILL.md` updated for per-subtask commits (stage+commit after each subtask's review passes) and an explicit reminder that DAGI never merges, switches off, or deletes the task branch — that's a manual user step.
  - Accepted limitation: `BashTool` remains an unrestricted bypass of the `dagi/*` guard (can run raw `git` commands). This was accepted, not overlooked, when the plan was implemented.
  - Spec: `docs/superpowers/specs/2026-07-12-dagi-git-workflow-design.md`. Plan: `docs/superpowers/plans/2026-07-12-dagi-git-workflow.md`.

- **Telegram bot `ask_user` hangs forever when `timeout=None`** · `done` · `2026-07-05`
  - Fix committed in `e39e146`: `safety = (timeout + 60) if timeout is not None else 600`.

- **Telegram bot `loop.finish()` skipped on exception — session log lost** · `done` · `2026-07-05`
  - Fix committed in `e39e146`: moved `loop.finish()` and `session.messages` to `finally` block, guarded by `if loop:`. Note: introduces `UnboundLocalError` risk (tracked separately).

- **`python-dotenv` CVE-2026-28684 — symlink file overwrite** · `done` · `2026-07-05`
  - Fix committed in `e39e146`: bumped from `>=1.0` to `>=1.2.2` in `requirements.txt`.

- **Windows line-ending triple-bug fix in `EditTool` / `WriteTool`** · `done` · `2026-07-05`
  - Root cause: `write_text()` default text-mode on Windows added `\r\n` to every file; bash/grep tool output returned CRLF bytes to LLM; LLM copied them into `oldText`; `read_text()` normalised file content to LF but `oldText` was not normalised → `content.count(CRLF_oldText) == 0` → silent "not found". Secondary: `\r\n` in `newText` + `write_text()` CRLF translation → `\r\r\n` on disk → phantom blank line on next read.
  - `tools/edit.py`: normalise `oldText`/`newText` via `.replace("\r\n","\n").replace("\r","\n")` before match/replace; pass `newline="\n"` to `write_text()`.
  - `tools/write.py`: same normalisation + `newline="\n"`. All DAGI-written files now have LF endings on disk regardless of OS. 184/184 tests pass.

- **`review-session` skill reworked — free-text selection + single running cross-session report** · `done` · `2026-07-03`
  - Full rewrite of `.dagi/skills/review-session/SKILL.md`. Replaces the old rigid selection grammar (session ID / `latest` / time filter / count / min-length / unreviewed-re-review) with free-text descriptions DAGI interprets itself via `find` and `chunk_session.py --list`.
  - Replaces per-session output files (`review_{session-id}.md`) with one running report per invocation (`review_{run-datetime}.md`); findings from later sessions are deduped against the report and merged as tag-accumulation on existing bullets rather than duplicated.
  - Shortcomings/improvement-item synthesis moved from per-session to once, at the end of the run, in plan mode — enables real cross-session pattern-spotting (e.g. the same error recurring across N sessions surfaces as one item citing all evidence sessions).
  - Dropped the `TODO.md` auto-append step (old Step 7) — this skill now only produces the review report.
  - `parse_jsonl_logs.py` and `chunk_session.py` unchanged — reused as-is inside the new per-session loop.
  - Old per-session `review_*.md` files left untouched on disk; skill no longer produces that format.

- **`requirements.txt` crawl4ai CVE patch** · `done` · `2026-07-01` — bumped to `>=0.8.7`, fixing 3 CVEs (SSRF, JWT auth bypass, path traversal); synced `PROJECT_CONTEXT.md`.
- **5 remaining `DAGI_ROOT` independent computations in cli/tui** · `done` · `2026-06-27` — replaced with `from agent import DAGI_ROOT` across `cli.py` (×2), `tui/app.py`, `tui/commands.py`, `tools/spawn_subagent.py`.
- **`json.loads(tc.function.arguments)` parsed up to 4 times per tool call** · `done` · `2026-06-27` — single parse reused at all 4 dispatch branches in `agent/loop.py`.
- **Subagent discovery only scans project path — misses DAGI root types** · `done` · `2026-06-27` — `_discover_subagent_tools` now scans both DAGI root and project path; project types override built-ins.
- **Persistent Memory System** · `done` · `2026-06-27` — BM25 removed in favor of subagent-based memory-query/memory-add; wiki restructured; simplified frontmatter schema; `/init` updated.
- **Tool Output Filter — Task 2: wire `filter_tool_output` into `AgentLoop`** · `done` · `2026-06-30`
  - Added `from tools.output_filter import filter_tool_output` import to `agent/loop.py`
  - Replaced the `result_str` dispatch block (lines 556–568) with the filter call: `context_result, full_str = filter_tool_output(result, self.config.reserve_tokens, DAGI_ROOT / ".dagi" / "temp")`
  - `context_result` → `_messages` and `on_tool_end`; `full_str` → `tracker.record_tool_end` and `ToolCallRecord.result`
  - Added `TestLoopIntegration` class to `tests/test_output_filter.py` — 1 integration test green; 184 tests total, all pass
  - Fixed test to use `AgentConfig(base_url=...)` not `api_url=`; `loop.client` not `loop._client`
  - Task 3 (TUI callback threading) still pending

- **Tool Output Filter — Task 1: `filter_tool_output()` pure function + tests** · `done` · `2026-06-30`
  - Created `tools/output_filter.py`: `filter_tool_output(result, reserve_tokens, temp_dir) → (context_result, full_str)`
  - 16 unit tests in `tests/test_output_filter.py` — all green
  - Fails open on `OSError`; zero/negative `reserve_tokens` skips filtering; `builtins.open` does not intercept `mkstemp` — patch `tools.output_filter.Path.write_text` instead

- **`<<END_OF_RESPONSE>>` position relaxed + continue prompt visibility** · `done` · `2026-06-28`
  - Flag can now appear anywhere in the response (not required to be last token)
  - `main_system.md` and `continue.md` prompts updated accordingly
  - `on_continue_injected(cur, max)` callback added to `AgentCallbacks`; TUI shows `↩ No exit flag — continue prompt injected (N/max)` in ConversationPane

- **Telegram bot interface** · `done` · `2026-06-28`
  - New `tg/` package: `bot.py` (TelegramBot class, handlers), `callbacks.py` (AgentCallbacks wired to Telegram), `session.py` (per-chat state), `utils.py` (message chunking)
  - Entry point: `telegram_bot.py` (thin typer launcher, mirrors `tui.py`)
  - Async/sync bridge: `run_in_executor` (Harbor pattern) + `run_coroutine_threadsafe` (callback bridge)
  - `load_telegram_config()` added to `agent/config_loader.py` (reads `telegram.bot_token_env` from config.yaml)
  - Package named `tg/` (not `telegram/`) to avoid shadowing `python-telegram-bot`'s own `telegram` module

- **Unified `_rebuild_system_prompt()` — eliminate 3-site divergence** · `done` · `2026-06-27`
  - Extracted `_assemble_system_string(dagi_root) -> str` in `agent/loop.py` — all 8 assembly steps in one method
  - Called from `__init__`, `_rebuild_for_normal_mode`, `_rebuild_for_plan_mode`; each site only handles `_messages` assignment and `compact_tool.bind()`
  - Also fixes: `system_parts` now refreshed on every rebuild; `_effective_memory_root` inline recomputation removed; `active_plan_file` block now also injected at init time when set

- **`_rebuild_for_reload` silently resets autonomous plan mode to interactive** · `done` · `2026-06-27`
  - Derived `interactive = self.config.plan_mode_initiated_by == "user"` before `_rebuild_for_plan_mode` call at `agent/loop.py:910`
  - Autonomous agents no longer flip to infinite `ask_user` wait on skill reload

- **`build_subagent_registry` fails for non-DAGI projects** · `done` · `2026-06-27`
  - `_load_subagent_config` now tries `project_path` first, then `_DAGI_ROOT` fallback (`agent/tools.py:43`)
  - Plan-work-review subagents now work from any project directory

- **Plan skeleton missing `## Execution Protocol` heading** · `done` · `2026-06-27`
  - Added `"## Execution Protocol\n\n"` after `"## Verification\n\n"` in scaffold at `agent/loop.py:631`
  - Plan document now self-contained regardless of compaction timing

- **`_subagent_runner.py` pipe buffer deadlock in CLI mode** · `done` · `2026-06-26`
  - Added `_drain_stdout()` to `tools/_subagent_runner.py`
  - Drain thread now always started — `_stream_stdout` with relay, `_drain_stdout` without
  - Added `extra_argv` param to `run_subagent()` for caller-supplied CLI flags

- **`SpawnCliSubagentTool` pipe buffer deadlock** · `done` · `2026-06-26`
  - Replaced hand-rolled `Popen`+`proc.wait()` with `run_subagent()` in `tools/cli_subagent.py`
  - Wired `on_event_factory` and `tracker` through constructor + `agent/tools.py` call site
  - Prompt-file cleanup in `try/finally`; timeout returns resumable PID dict
  - Custom subagents now appear in TUI, tracked in session logs, resumable after timeout

- **`_handle_complete_plan` uses stale `Path(__file__).parent.parent` instead of `DAGI_ROOT`** · `done` · `2026-06-26`
  - Replaced `Path(__file__).parent.parent` with `DAGI_ROOT` at `agent/loop.py:677`
  - Last stale site in `loop.py` — all `_rebuild_for_normal_mode` call sites now use the canonical constant

- **`_rebuild_for_normal_mode` missing `memory_root=` in `create_tool_registry`** · `done` · `2026-06-26`
  - Added `memory_root=self._effective_memory_root,` at `agent/loop.py:790`
  - All three `create_tool_registry` call sites now consistently forward custom memory root
  - Custom `memory_root` no longer silently reverts to default after plan→normal transition

- **README install & troubleshooting update** · `done` · `2026-06-21`
  - Added conda + venv install paths using `requirements.txt`
  - Added troubleshooting section: OpenAI credential errors, proxy/auth issues (`no_proxy`)
  - Added TUI-first workflow (`/wd` to navigate after launch, then `/init`)

---

## Work Queue

### 🔴 CRITICAL — Security / Data Loss

- **Telegram bot has no authorization — unauthenticated remote code execution** · `priority:critical` · `open:7d` · `effort:S`
  - **File:** `tg/bot.py:102-122` (`_handle_message`), `agent/tools.py:285` (BashTool always registered)
  - **Problem:** `_handle_message` dispatches input from *any* `chat_id` straight into `AgentLoop` with the full tool registry (`bash` = `subprocess.run(shell=True)`, unrestricted `write`/`edit`/`copy`). No allowlist, no owner check. Anyone who finds/guesses the bot can run arbitrary shell commands on the host.
  - **Fix:** Add an allowlist (`TELEGRAM_ALLOWED_CHAT_IDS`) checked before dispatch; reject others. Consider restricting `config.tools` on the remote surface via the existing `registry.filter_to`.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#3)

- **Memory-subagent wiki sandbox fails open when `memory_root` is unset (the default)** · `priority:critical` · `open:7d` · `effort:S`
  - **File:** `agent/tools.py:436-443`; interacts with `agent/config_loader.py:142-143`, `cli.py:1116,974`
  - **Problem:** `root: memory_root` restriction only applies when `memory_root is not None`, but `config.memory_root` defaults to `None` (`config.example.yaml:87` ships it commented out). In the default config, `memory-add`/`memory-query` subagents fall through to full project scope with `write`+`edit` — they can modify `agent/loop.py`, `.env`, anything. The resolved root (`loop.py:254`) is not the value threaded into `build_subagent_registry`; the raw `None` is.
  - **Fix:** Pass the resolved effective memory root into `build_subagent_registry`, or default the fallback to `project_path / "dagi-memory"` when `root == "memory_root"` and `memory_root is None`. Never fall through to full scope on a sandbox request.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#4)

- **`requirements.txt` floor pins allow installing vulnerable pymupdf/docling-core** · `priority:high` · `open:0d` · `effort:XS`
  - **File:** `requirements.txt:45-46`
  - **Problem:** `pymupdf>=1.24` permits installing versions vulnerable to CVE-2026-3029 (path traversal, arbitrary file write via `embed-extract`, fixed in 1.26.6). `docling>=2.0` permits installing docling-core versions vulnerable to CVE-2026-24009 (RCE via unsafe PyYAML deserialization, fixed in docling-core 2.48.4) and CVE-2026-44023 (SSRF, CVSS 8.6, fixed in docling-core 2.74.1, published 2026-07-16). Installed versions are safe (pymupdf 1.28.0, docling-core 2.87.1), but a fresh `pip install -r requirements.txt` on a clean env may resolve vulnerable versions.
  - **Fix:** Bump floors: `pymupdf>=1.26.6`, `docling>=2.75` (pulls docling-core >= 2.74.1). Consider pinning docling-core directly.
  - **Source:** `review/2026-07-18`

### 🔴 HIGH — Bugs

- **Reading any image file crashes the agent loop (`AttributeError` on list result)** · `priority:medium` · `open:7d` · `effort:XS` · `needs-verification`
  - **File:** `agent/loop.py:562-564`
  - **Problem (original):** `ReadTool.run()` returns a `list` for image files. The sentinel-detection chain's `else` branch was reported to call `parse_switch_sentinel(result)` without a type guard, crashing with `AttributeError`.
  - **Status 2026-07-14:** Current code at line 563 has `if isinstance(result, str):` guard before `parse_switch_sentinel()` — the crash path described appears to be already guarded. All upstream sentinel checks (lines 549–558) use `==` comparisons that return False for lists. `filter_tool_output` at line 568 also handles lists via `_serialise()`. **Needs a manual test with an actual image file to confirm the bug is unreproducible.** Downgraded from CRITICAL pending verification.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#1)

- **`archives/cli.py:1240` `plan_mode_exited` — AttributeError (dead code)** · `priority:low` · `open:7d` · `effort:XS`
  - **File:** `archives/cli.py:1240`
  - **Problem:** `active_loop.plan_mode_exited` is referenced but the attribute was removed on 2026-05-31. **However, `cli.py` was moved to `archives/cli.py` on 2026-07-12 (`d6f7f25`) and is no longer imported or executed by any live code.** This bug exists only in dead code. The live entry points are `tui.py` and `telegram_bot.py`.
  - **Fix:** Delete `archives/cli.py` entirely (tracked under dead code cleanup).
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#2) · Downgraded 2026-07-14: cli.py archived, bug unreachable.

- **`tg/bot.py` `UnboundLocalError` in `finally` block — masks original exception** · `priority:high` · `open:14d` · `effort:XS`
  - **File:** `tg/bot.py:163`
  - **Problem:** The uncommitted fix moves `if loop:` into a `finally` block, but `loop` is only assigned at line 147 (`loop = AgentLoop(...)`). If `resolve_model_config()` (line 134) or `build_callbacks()` (line 140) raises, the `finally` block hits `UnboundLocalError: cannot access local variable 'loop' before assignment`, which masks the original exception and crashes the handler without setting `session.busy = False`.
  - **Fix:** Add `loop = None` before the `try` block (line 133).
  - **Escalated 2026-07-18:** Open 14 days with no fix commit. XS effort, one-line fix.
  - **Source:** `review/2026-07-04`

- **`grep` Python fallback silently drops all matches under dotted directories** · `priority:high` · `open:7d` · `effort:XS`
  - **File:** `tools/grep.py:96-101`
  - **Problem:** When ripgrep is unavailable, the fallback filters out files where *any* `p.parts` component starts with `.` — but `p.parts` includes the absolute path. Grepping inside `.dagi/skills/` (a normal operation) returns zero matches because `.dagi` is in the path. ripgrep masks this on most machines, making it hard to diagnose when it bites.
  - **Fix:** Filter only path components *below* `search_path`: `rel_parts = p.relative_to(search_path).parts`.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#7)

- **`is_scanned_pdf` / `_get_page_count` leak fitz document handle on exception** · `priority:medium` · `open:0d` · `effort:XS`
  - **File:** `tools/_pdf_convert.py:43-53,56-63`
  - **Problem:** Both functions call `fitz.open(str(pdf_path))` and `doc.close()` with no `try/finally` or context manager. If `doc[i].get_text()` raises (corrupt page, `MemoryError`), or `len(doc)` fails on a malformed PDF, the file handle is leaked. pymupdf's `fitz.Document` supports the context manager protocol.
  - **Fix:** Replace `doc = fitz.open(...); ...; doc.close()` with `with fitz.open(...) as doc:` in both functions.
  - **Source:** `review/2026-07-18`

- **`_estimate_worker_count` ZeroDivisionError when `worker_ram_gb` is 0** · `priority:medium` · `open:0d` · `effort:XS`
  - **File:** `tools/_pdf_convert.py:77`
  - **Problem:** `available_bytes // (cfg.worker_ram_gb * 1024**3)` raises `ZeroDivisionError` if the user sets `pdf.worker_ram_gb: 0` in `config.yaml`. `PdfConfig` has no validation — `load_pdf_config()` passes through any value from the config file. The function is not yet called from production code (only tests), but it was written for the upcoming parallel PDF conversion feature.
  - **Fix:** Validate in `load_pdf_config()`: `max(cfg.worker_ram_gb, 0.1)`, or guard in `_estimate_worker_count` with `if cfg.worker_ram_gb > 0`.
  - **Source:** `review/2026-07-18`

- **`_convert_pdf_scanned` OCR temp file path collides across same-stem PDFs** · `priority:low` · `open:0d` · `effort:XS`
  - **File:** `tools/_pdf_convert.py:107`
  - **Problem:** `searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"` uses the source filename's stem, not the content hash. `cache_dir` is the flat `.dagi/hash_cache/pdf/` directory. Two different scanned PDFs with the same filename stem (e.g., `A/report.pdf` and `B/report.pdf`) produce the same OCR temp path. The `finally` block cleans up the temp file, so sequential calls are safe, but concurrent calls (relevant when parallel conversion is wired up) would corrupt each other's OCR output.
  - **Fix:** Use the content hash for the temp file name: `searchable_path = cache_dir / f"{content_hash}_ocr.pdf"` (pass `content_hash` from the caller).
  - **Source:** `review/2026-07-18`

- **`BashTool._killed_by_user` race between `run()` and `force_kill()`** · `priority:medium` · `open:2d` · `effort:XS`
  - **File:** `tools/bash.py:54-56,78,84-92`
  - **Problem:** `_killed_by_user` is read at line 78 *outside* the lock, after `self._proc = None` is set inside the lock at line 75. Two race windows exist: (1) `force_kill()` fires after `communicate()` returns but before the flag check at line 78 — a normal completion is reported as `[killed by user]`. (2) `force_kill()` fires between `Popen()` (line 45) and the lock acquisition (line 54), setting `_killed_by_user = True` on a previous `_proc` that's already `None` — `force_kill` returns `False` (correct), but the flag sticks and the *new* run inherits it because `_killed_by_user = False` only runs at line 56, inside the lock that `force_kill` may have already exited.
  - **Fix:** Read `_killed_by_user` inside the `finally` lock block and store it in a local; reset the flag there too: `with self._lock: self._proc = None; was_killed = self._killed_by_user; self._killed_by_user = False`. Use `was_killed` at line 78.
  - **Source:** `review/2026-07-16`

- **Scheduler `loop.finish()` races with daemon thread on timeout** · `priority:medium` · `open:19d` · `effort:XS`
  - **File:** `scheduler/runner.py:113`
  - **Problem:** `loop.finish()` is called unconditionally after `thread.join(timeout=...)`. On timeout, the daemon thread is still running `loop.run()` — mutating `loop._messages` concurrently. `finish()` calls `tracker.finish(raw_messages=self._messages)` which serializes `_messages` via `json.dumps`. The daemon thread may be appending to `_messages` at the same time — data race on the list. CPython's GIL prevents crashes but the serialized output can be inconsistent (missing or partial messages).
  - **Fix:** Only call `loop.finish()` after confirming `not thread.is_alive()`. On timeout, defer `finish()` or take a snapshot: `msgs_copy = list(loop._messages); tracker.finish(raw_messages=msgs_copy)`.
  - **Source:** `review/2026-06-29`

- **Telegram `build_callbacks` doesn't wire `on_subagent_event_factory` — subagent output invisible** · `priority:medium` · `open:19d` · `effort:S`
  - **Escalated 2026-07-11:** Open 14 days with no fix commit.
  - **File:** `tg/callbacks.py:82-97`
  - **Problem:** `build_callbacks()` in `tg/callbacks.py` doesn't set `on_subagent_event_factory`. The default is `None`, so subagent stdout (worker, review, explore_files, web_research) is silently discarded. When a Telegram user triggers plan-work-review, they see no progress from worker/review subagents — only the final result.
  - **Fix:** Add an `on_subagent_event_factory` that returns a callback forwarding subagent lines via `_send()` (with a `[subagent-type]` prefix and message batching to avoid Telegram rate limits).
  - **Source:** `review/2026-06-29`

---

### 🟠 Architecture Debt

- **`disable-model-invocation` SKILL.md frontmatter flag has no code-level enforcement** · `priority:medium` · `open:0d` · `effort:S`
  - **File:** `agent/skills.py`
  - **Problem:** The flag is intended to mean "never auto-trigger via ordinary user phrasing, only invoke programmatically via `skill(name)`" — used by `to-spec` (SKILL.md frontmatter sets it). Discovered during the 2026-07-18 `plan-work-review` decomposition that `agent/skills.py` parses the flag but never checks it anywhere in the invocation path — any user phrasing that happens to match a skill's trigger words can still fire it, defeating the purpose of the flag for `to-spec` and any future programmatic-only skill.
  - **Fix:** Add an enforcement check at the skill-dispatch site in `agent/skills.py` (or wherever skill triggers are matched against user/model input) that skips skills with `disable-model-invocation: true` unless the invocation is the explicit programmatic `skill(name)` call path.
  - **Source:** code review during `docs/superpowers/plans/2026-07-18-plan-skill-decomposition.md` Task 5, spun off as a standalone follow-up rather than fixed inline (out of scope for a structure-only decomposition).

- **`write_text()` CRLF inconsistency — 10 call sites lack `newline="\n"`** · `priority:medium` · `open:13d` · `effort:S`
  - **Files:** `agent/loop.py:637`, `agent/cli_utils.py:132,140`, `agent/config_loader.py:244`, `tools/cli_subagent.py:82`, `tools/_subagent_runner.py:138`, `tools/subagent_main.py:206`, `tools/escalate_issue.py:57`, `tools/output_filter.py:72`, `scheduler/runner.py:134`, `scheduler/models.py:110`
  - **Problem:** The 2026-07-05 CRLF fix added `newline="\n"` to `EditTool` and `WriteTool`, establishing the invariant "all DAGI-written files have LF on disk." But 10 other `write_text()` call sites still use the Windows default (`newline=None`), which adds `\r` to every `\n` on Windows. Most impactful: plan files (`loop.py:637`), handoff fallbacks (`subagent_main.py:206`), escalation files (`escalate_issue.py:57`), and scheduler output (`runner.py:134`) — all persist on disk and may be read by tools.
  - **Fix:** Add `newline="\n"` to all 10 call sites. Grep `\.write_text\(` to ensure no new sites are missed.
  - **Updated 2026-07-14:** 3 old `cli.py` sites are now dead (archived). 3 new sites added: `agent/cli_utils.py:132,140` (extracted from cli.py), `tools/subagent_main.py:206`, `tools/escalate_issue.py:57`.
  - **Source:** `review/2026-07-05`

- **`tui/commands.py` imports from `cli.py` — layering violation** · `done` · `2026-07-13`
  - **Fix applied:** `cli.py` was deprecated and moved to `archives/cli.py`, which broke `/init` and `/plan` at runtime (`ModuleNotFoundError: No module named 'cli'`). Extracted `_cmd_init` and `_skill_invocation_message` into `agent/cli_utils.py`; `tui/commands.py:62,75,78` now import from there instead of the archived module.
  - **Source:** `_todo/todo_2026-06-13.md` #7

- **`explore_files` / `memory-query` subagents fail with `ModuleNotFoundError: No module named 'agent'`** · `done` · `2026-07-13`
  - **Root cause:** The 2026-07-12 "deprecate cli" commit (`d6f7f25`) moved `cli.py` from the project root to `archives/cli.py` but only updated the path string in `tools/_subagent_runner.py:21`. Python sets `sys.path[0]` to a script's own directory when run directly (`python archives/cli.py`), so once the entry point moved one level deeper, `from agent.config_loader import ...` in `archives/cli.py:35` could no longer resolve — breaking every subagent spawned via `run_subagent()` (`explore_files`, `web_research`, memory-query/memory-add, worker/review, custom CLI subagents).
  - **Fix applied:** Subagent entry point moved from `archives/cli.py` to `tools/subagent_main.py`, invoked as `python -m tools.subagent_main` with `cwd=_DAGI_ROOT`. Module invocation puts `cwd` on `sys.path` automatically, so root-level packages are always resolvable. The intermediate `PYTHONPATH` env approach (mentioned in PROJECT_CONTEXT.md) was superseded by this cleaner module-invocation pattern.
  - **Source:** user report, 2026-07-13

- **Dead code: `ExploreFilesTool`, `WebResearchTool`, `SubAgentRunner`** · `priority:high` · `open:38d` · `effort:S`
  - **Escalated 2026-07-02:** Open 22 days with no fix commit — raised to high.
  - **Files:** `tools/explore_files.py`, `tools/web_research.py`, `agent/sub_agent.py`
  - **Problem:** None of these are registered in `create_tool_registry()` or used anywhere. They are remnants of the old direct-spawn architecture replaced by pipe-based subagents.
  - **Fix:** Audit for external callers; delete if unused.
  - **Updated 2026-07-14:** Removed `tools/plan_subagent.py` (already deleted in `bfbdd63`) and `cli.py:77 _resolve_option` (only exists in `archives/cli.py`, dead code).
  - **Source:** `_todo/todo_2026-06-13.md` #4, `docs/fable/code_review_2026-07-11.md` (#6, #12)

- **Split `agent/loop.py` (1112 lines) into focused modules** · `priority:high` · `open:4d` · `effort:M`
  - **File:** `agent/loop.py` (1112 lines — 2× over 500-line standard)
  - **Problem:** Mixes core loop execution, plan-mode handling, system-prompt assembly, wiki injection, sentinel parsing, model switching, tool dispatch, compaction, streaming response accumulation, and the live plan-status board rendering. Largest Python file in the live codebase.
  - **Suggested split:** Extract `_handle_enter_plan_mode`/`_handle_exit_plan_mode`/`_handle_complete_plan` → `agent/_plan_mode.py`; extract `_assemble_system_string`/`_build_active_plan_tail`/`_render_plan_status_section`/`_refresh_active_plan_tail` → `agent/_system_prompt.py`; extract `_handle_switch_model`/`_base_config_snapshot` → `agent/_model_switch.py`; extract `_consume_stream` → `agent/_streaming.py`.
  - **Note:** Replaces the old "Split cli.py" item — `cli.py` was moved to `archives/cli.py` on 2026-07-12 and is dead code.
  - **Updated 2026-07-17:** Line count rose from 1013 → 1112 with the addition of `_consume_stream` (streaming support) — added `_consume_stream` to the suggested-split list above rather than treating it as a new backlog item.
  - **Source:** `review/2026-07-14`

- **`agent/prompts.py` still uses independent `Path(__file__).parent.parent`** · `priority:medium` · `open:21d` · `effort:XS`
  - **Escalated 2026-07-16:** Open 19 days with no fix commit.
  - **File:** `agent/prompts.py:5-6`
  - **Problem:** `_PROMPTS_DIR` and `_SUBAGENTS_DIR` are computed via `Path(__file__).parent.parent` — the same pattern that caused 4 confirmed divergence bugs before centralisation in `agent/__init__.py:DAGI_ROOT`. These 2 sites were missed in the 2026-06-27 sweep (`cli.py` ×2, `tui/app.py`, `tui/commands.py`, `tools/spawn_subagent.py`). They work correctly today because `prompts.py` lives inside `agent/`, but any restructuring would break them silently.
  - **Fix:** Replace with `from agent import DAGI_ROOT; _PROMPTS_DIR = DAGI_ROOT / ".dagi" / "prompts"` (and same for `_SUBAGENTS_DIR`).
  - **Source:** `review/2026-06-27`

- **`_parse_frontmatter` duplicated verbatim between `agent/skills.py` and `agent/workflows.py`** · `priority:medium` · `open:28d` · `effort:XS`
  - **Files:** `agent/skills.py:30-42`, `agent/workflows.py:30-42`
  - **Problem:** Identical regex patterns and function body. Any bug fix must be applied twice.
  - **Fix:** Extract to `agent/_frontmatter.py`; import in both files.
  - **Source:** `_todo/todo_2026-06-20.md` B1

- **`_extra_body` construction duplicated in `__init__` and `_handle_switch_model`** · `priority:medium` · `open:29d` · `effort:XS`
  - **Files:** `agent/loop.py:311-317`, `agent/loop.py:732-738`
  - **Problem:** Identical 6-line block in two places. New OpenRouter extensions must be added in both or silently break after a tier switch.
  - **Fix:** Extract `_build_extra_body() -> dict` method.
  - **Source:** `_todo/todo_2026-06-19.md` B2

- **`ask_user` callback has no deadlock protection (infinite wait)** · `priority:high` · `open:30d` · `effort:XS`
  - **Escalated 2026-07-18:** Open 30 days with no fix commit — raised to high.
  - **Files:** `tui/callbacks.py:73-74`, `tg/callbacks.py:65-66`
  - **Problem:** When `ask_user` is called with `timeout=None` (default in plan mode), `evt.wait(timeout=None)` blocks the agent thread indefinitely. If the TUI closes, the agent thread hangs permanently. The Telegram bot has an identical pattern (tracked separately as HIGH because the impact is worse — no user kill switch).
  - **Fix:** Always use a finite safety timeout: `safety = (timeout + 60) if timeout is not None else 600`.
  - **Source:** `_todo/todo_2026-06-18.md` D1

- **`_tools_from_list` limited to 9 hardcoded tool names** · `priority:medium` · `open:30d` · `effort:S`
  - **File:** `agent/tools.py:51-81`
  - **Problem:** Subagent registries can only reference 9 tools. Any other tool name (e.g., `skill`, `ask_user`, `git_status`) is silently dropped with a warning.
  - **Fix:** Either expand the registry map to cover all tools, or drive subagent registration from `create_tool_registry(tool_names=[...])` and delete `_tools_from_list`.
  - **Source:** `_todo/todo_2026-06-18.md` D2

- **Sidebar `_system_breakdown` reads stale `soul.md` path** · `priority:medium` · `open:30d` · `effort:XS`
  - **File:** `tui/utils.py:66`
  - **Problem:** `_toks(dagi_root / "soul.md")` — `soul.md` was moved to `.dagi/prompts/soul.md`. The old path doesn't exist; sidebar understates system prompt token count by ~150–300 tokens.
  - **Fix:** Change to `dagi_root / ".dagi" / "prompts" / "soul.md"`.
  - **Source:** `_todo/todo_2026-06-18.md` A2

- **`_system_breakdown()` reads disk on every Textual render cycle** · `priority:medium` · `open:30d` · `effort:XS`
  - **File:** `tui/utils.py:58-70` (called from `sidebar.py` render)
  - **Problem:** 3 file reads per render cycle for files that never change during a session.
  - **Fix:** Compute once in `Sidebar.__init__` and cache as `self._sys_parts`.
  - **Source:** `_todo/todo_2026-06-18.md` B1

- **`SkillTool.run()` reloads all skills from disk on every invocation** · `priority:medium` · `open:23d` · `effort:S`
  - **File:** `tools/skill.py:41-46`
  - **Problem:** Every `skill("name")` call creates a new `SkillLoader`, scans all skill root dirs, reads and parses every SKILL.md. `AgentLoop` already has `self.skills` pre-loaded. ~30 file reads per call.
  - **Fix:** Pass the pre-loaded skills list to `SkillTool` at construction time, or cache after first load.
  - **Source:** `_todo/todo_2026-06-25_2.md` A2

- **Falsy-zero coercion in config — `reserve_tokens: 0` silently becomes `16384`** · `priority:medium` · `open:7d` · `effort:XS`
  - **File:** `agent/config_loader.py:133-135`
  - **Problem:** `entry.get("context_window") or raw.get(...)` treats a legitimately configured `0` as "unset" and falls through to the default. `reserve_tokens: 0` (explicitly supported to disable output filtering) and `keep_recent_tokens: 0` can never be set from a per-model entry.
  - **Fix:** Replace `X or Y` with explicit presence check: `entry[k] if k in entry else raw.get(k, default)`.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#9)

- **`AskUserTool` double-timeout race — user answers but tool already returned fallback** · `priority:medium` · `open:7d` · `effort:XS`
  - **File:** `tools/ask_user.py:89-96`
  - **Problem:** The callback (`on_ask_user`) already enforces its own timeout (+60s safety). Wrapping it in a *second* `t.join(timeout=effective_timeout)` means the tool can return the fallback while the user is still in the callback's safety window. The daemon thread is left dangling with a result nobody reads.
  - **Fix:** Let the callback own the timeout. Drop the `t.join` timeout (join without timeout) or call `_on_ask_user` synchronously and rely on the single timeout inside the callback.
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#10)

- **`explore_files` schema requires `handoff_file` param the code ignores — token waste** · `priority:medium` · `open:7d` · `effort:XS`
  - **File:** `.dagi/subagents/explore_files/subagent_config.yaml`
  - **Problem:** `parameters` marks both `task` and `handoff_file` as `required`, but `SpawnSubagentTool.run()` generates the handoff path internally (line 162) and discards the LLM-supplied value. The model is forced to invent a path that's thrown away — wasting tokens.
  - **Fix:** Remove `handoff_file` from `parameters`/`required` in the config (matching how `web_research` is defined).
  - **Source:** `docs/fable/code_review_2026-07-11.md` (#11)

- **`WebFetchTool` silently upgrades HTTP→HTTPS for private IP addresses** · `priority:medium` · `open:23d` · `effort:XS`
  - **File:** `tools/web_fetch.py:123`
  - **Problem:** HTTP→HTTPS upgrade excludes `localhost` and `127.0.0.1` but not `192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, or `[::1]`. Agent fails to fetch local dev servers with a misleading error.
  - **Fix:** Expand exclusion regex to cover all RFC-1918 and loopback ranges.
  - **Source:** `_todo/todo_2026-06-25_2.md` A4

- **`tg/bot.py:153` uses deprecated `asyncio.get_event_loop()` — Python 3.14 breakage risk** · `priority:medium` · `open:14d` · `effort:XS`
  - **File:** `tg/bot.py:153`
  - **Problem:** `asyncio.get_event_loop()` is deprecated since Python 3.10 and emits `DeprecationWarning` in 3.12+. In Python 3.14 (which this project's conda env runs), it may raise `DeprecationWarning` or behave unexpectedly when called inside a running coroutine. Line 61 already correctly uses `asyncio.get_running_loop()`. The method `_run_agent_task` is `async`, so a running loop is guaranteed.
  - **Fix:** Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` at line 153.
  - **Source:** `review/2026-07-04`

---

### 🟡 Token Efficiency & Observability

- **Session cost tracking always shows `$—`** · `priority:high` · `open:30d` · `effort:S`
  - **File:** `agent/session.py:108`
  - **Problem:** Most API providers (including OpenRouter for many models) don't populate `usage.cost`. Sidebar shows `$—`, `session_end` has `total_cost: null`. No cost visibility makes it impossible to benchmark model tiers.
  - **Fix:** Fall back to computing cost from token counts using a per-model `pricing` section in `config.yaml` (input/output cost per 1M tokens).
  - **Source:** `_todo/todo_2026-06-18.md` C1

- **`thinking_tokens` (reasoning tokens) not recorded in session JSONL** · `priority:high` · `open:28d` · `effort:S`
  - **File:** `agent/session.py:100-118`
  - **Problem:** `completion_tokens_details.reasoning_tokens` is never extracted from API responses. For extended-thinking models (DeepSeek, Claude with thinking), reasoning tokens can be 50%+ of the completion budget — invisible in post-session analysis.
  - **Fix:** Add `thinking_tokens: int | None = None` to `MessageNode`; extract in `record_assistant()`; include `total_thinking_tokens` in `session_end`.
  - **Source:** `_todo/todo_2026-06-20.md` C1

- **Cache hit visibility in TUI sidebar** · `priority:high` · `open:32d` · `effort:S`
  - **Escalated 2026-07-16:** Open 30 days with no fix commit.
  - **File:** `agent/loop.py:480-487`, `tui/sidebar.py`
  - **Problem:** `cache_prompt: true` is sent to OpenRouter, but `usage.prompt_tokens_details.cached_tokens` is never read. Users have no visibility into whether prompt caching is working.
  - **Fix:** Extract `cached_tokens` from `usage.prompt_tokens_details`; pass through `on_token_update`; display in sidebar as `{cached_tok}↩ cached`.
  - **Source:** `_todo/todo_2026-06-16.md` C1

- **Tool result content not truncated in JSONL logs** · `priority:medium` · `open:28d` · `effort:XS`
  - **File:** `agent/session.py:129-135`
  - **Problem:** `record_tool_end(name, result_str)` writes the full result. Compare with `record_subagent_end` which truncates to 500 chars. Large tool results (file reads, grep output, base64) are the primary driver of log disk consumption.
  - **Fix:** Truncate to 2000 chars in `record_tool_end`; record `result_length` for reference.
  - **Source:** `_todo/todo_2026-06-20.md` C2

- **Wiki index system messages accumulate across `run()` calls — unbounded token waste** · `priority:medium` · `open:9d` · `effort:XS`
  - **File:** `agent/loop.py:370-372`
  - **Problem:** `_build_wiki_index_context()` is called at the top of every `run()` call and appends a new system message to `_messages`. In multi-turn CLI/TUI sessions, `initial_messages` carries forward previous messages, so each user turn adds another copy of the wiki index (~200–500 tokens) without removing prior copies. After 10 turns, that's 2000–5000 tokens of redundant context. Compaction will eventually consume them, but they inflate token counts and can trigger premature compaction.
  - **Fix:** Before injecting, scan `_messages` for the last wiki-index system message (identifiable by a prefix like `"## Wiki Index"`) and replace it in-place; or guard with a flag so it's only injected once per `AgentLoop` instance.
  - **Source:** `review/2026-07-09`

- **Token efficiency benchmark harness** · `priority:high` · `open:29d` · `effort:M`
  - **Problem:** No way to measure whether code changes improve or degrade token efficiency. Harbor/Terminal-bench measure task correctness but not tokens/cost/continuation count per task.
  - **Fix:** `scripts/benchmark_token_efficiency.py` that parses session JSONL files and produces per-task metrics: `input_tokens`, `output_tokens`, `thinking_tokens`, `tool_call_count`, `continuation_count`, `cache_hit_tokens`.
  - **Source:** `_todo/todo_2026-06-19.md` D3

- **GNHF self-improvement loop — never bootstrapped (83 days stale)** · `priority:high` · `open:83d`
  - **Current:** The `review-session` skill (reworked 2026-07-03 to accept free-text session selection and accumulate cross-session findings into one running report) and `improve-yourself` workflow exist; `.dagi/self-review/` has 5 files all from April 2026; 250 session logs have accumulated (last: 2026-07-18). The entire GNHF feedback cycle has never run. Now 83 days dormant.
  - **Next:** Invoke `review-session` once with "review the 10 most recent sessions" to bootstrap a single cross-session report. Then schedule a weekly run.
  - **Source:** `_todo/todo_2026-06-16.md` C2

---

### 🟢 Features

- **Task scheduler** · `done` · `2026-06-28`
  - `scheduler/` package: `models.py` (ScheduledTask, parse_interval), `tracker.py` (RunTracker), `runner.py` (entry point)
  - `tools/schedule_tools.py`: `schedule_task`, `list_scheduled_tasks`, `remove_scheduled_task` (interactive sessions only)
  - `run_scheduler.bat`: Windows trigger; wire into Task Scheduler
  - `AgentConfig.ask_user_timeout` field; `create_tool_registry` respects it
  - `.dagi/scheduler/schedule.yaml` for task definitions (hours-based intervals)
  - `.dagi/scheduler/runs.jsonl` for execution log; per-task `output_file` support
  - 40 unit tests — all passing; float-only `interval` (seconds) throughout

- **`/stats` slash command for live session diagnostics** · `priority:medium` · `effort:S`
  - Show total tokens (in/out/thinking), cost, tool call histogram, continuation count, compaction count, and session duration. All data already available on `loop.tracker._messages` and `app._stats`.
  - **Source:** `_todo/todo_2026-06-17.md` D1

- **Worker model for compaction (cheaper)** · `priority:medium` · `effort:XS`
  - **File:** `tools/compact.py:222`
  - `compact()` uses `config.model` (the main task model). Summarization is a low-complexity task; prefer `config.worker_config.model` if available.
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

- **Full Harbor benchmark run (89 tasks)** · `priority:medium` · `impact:high`
  - **Next:** `set DAGI_BENCH_MODEL=claude-sonnet-openrouter && benchmarks\run_harbor.bat`; record results.

---

### 🔵 Testing

- **Tests for compaction failure recovery** · `priority:medium` · `effort:XS`
  - Verify graceful degradation path (the 2026-06-21 fix) — mock a failing summarization call and assert session continues.
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

- **`tests/test_read_tool.py` exceeds 500-line coding standard** · `priority:low` · `open:0d` · `effort:S`
  - **File:** `tests/test_read_tool.py` (473 lines committed + 68 uncommitted = 541 lines)
  - **Problem:** File has grown with each ReadTool feature (DOCX/XLSX/PPTX, PDF, auto-summarization, `_estimate_worker_count` tests). Exceeds the project's 500-line maximum.
  - **Fix:** Split into `tests/test_read_tool.py` (core read + document conversion) and `tests/test_pdf_convert.py` (PDF-specific: page parsing, scanned detection, conversion pipelines, worker estimation).
  - **Source:** `review/2026-07-18`

---

### ⚪ LOW — Housekeeping & Dead Code

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

- **Base64 image data dumped into compaction summarization prompt** · `priority:low` · `effort:XS` · `images-not-yet-supported`
  - **File:** `tools/compact.py:68-71`
  - **Problem:** `_format_messages_for_summary()` calls `str(msg["content"])` on list-typed content (vision tool results), dumping ~32K tokens of raw base64 per image into the summarization prompt.
  - **Fix:** Guard with `isinstance(content, list)` and replace with `[image omitted]` placeholder.
  - **Source:** `_todo/todo_2026-06-20.md` A2

- **`_estimate_tokens` base64 inflation causes over-aggressive compaction** · `priority:low` · `effort:XS` · `images-not-yet-supported`
  - **File:** `tools/compact.py:45-52`
  - **Problem:** `str(content)` on list-typed content inflates token estimates by ~8K tokens per image, shortening the "recent tail" preserved during compaction.
  - **Fix:** `isinstance(content, list)` guard — use 200 token placeholder per image.
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

- **Fix `pyproject.toml` dependencies** · `priority:low`
  - Add `typer`, `rich`, `textual`; remove `nicegui`, `markdown`, `matplotlib`.
  - **Source:** `_todo/todo_2026-06-16.md` F3

- **`langchain` + `langchain-openai` are dead dependencies in `requirements.txt`** · `priority:low` · `open:20d` · `effort:XS`
  - **Escalated 2026-07-16:** Open 18 days with no fix commit. CVE-2026-34070 remains an exposure vector.
  - **File:** `requirements.txt:8-9`
  - **Problem:** `langchain>=1.3.4` and `langchain-openai>=1.2.2` are listed as core required deps, but no Python file in the project imports from either package. They add ~100MB of transitive dependencies (numpy, pydantic, aiohttp, etc.) for zero value. Likely a remnant from an earlier architecture. Additionally, CVE-2026-34070 (CVSS 7.5) is a path traversal in `langchain_core/prompts/loading.py` — having the package installed exposes this vulnerability even though DAGI doesn't call it.
  - **Fix:** Remove both lines from `requirements.txt`.
  - **Source:** `review/2026-06-28`, CVE note added `review/2026-06-30`

- **Dead `ChatSession.lock` field in `tg/session.py`** · `priority:low` · `open:18d` · `effort:XS`
  - **File:** `tg/session.py:13`
  - **Problem:** `ChatSession` declares `lock: threading.Lock = field(default_factory=threading.Lock)` but no code in the `tg/` package ever acquires or releases it. The `busy` flag is the actual concurrency guard. The unused lock misleads readers into thinking thread-safe access patterns are in place when they are not.
  - **Fix:** Remove the `lock` field from `ChatSession` and its `import threading` if no other usage remains.
  - **Source:** `review/2026-06-30`

- **`config.example.yaml:85` stale BM25 reference in `memory_root` comment** · `priority:low` · `open:16d` · `effort:XS`
  - **File:** `config.example.yaml:85`
  - **Problem:** Comment says "persistent knowledge retrieval (BM25)" — BM25 was removed 2026-06-27 in favor of subagent-based grep+traversal. Stale reference confuses readers into thinking BM25 is still used.
  - **Fix:** Change to "persistent knowledge wiki (subagent-based retrieval)".
  - **Source:** `review/2026-07-02`

- **Telegram bot redundant `config.project_path` assignment** · `priority:low` · `open:18d` · `effort:XS`
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

**Root cause:** The `/improve-yourself` workflow has never been run. Review items are waiting. 250 session logs have accumulated; self-review last ran 83 days ago (2026-04-26).

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
