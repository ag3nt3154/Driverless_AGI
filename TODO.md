# TODO

## Completed

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

### 🔴 HIGH — Bugs

- **`tg/bot.py` `UnboundLocalError` in `finally` block — masks original exception** · `priority:high` · `open:1d` · `effort:XS`
  - **File:** `tg/bot.py:163`
  - **Problem:** The uncommitted fix moves `if loop:` into a `finally` block, but `loop` is only assigned at line 147 (`loop = AgentLoop(...)`). If `resolve_model_config()` (line 134) or `build_callbacks()` (line 140) raises, the `finally` block hits `UnboundLocalError: cannot access local variable 'loop' before assignment`, which masks the original exception and crashes the handler without setting `session.busy = False`.
  - **Fix:** Add `loop = None` before the `try` block (line 133).
  - **Source:** `review/2026-07-04`

- **Scheduler `loop.finish()` races with daemon thread on timeout** · `priority:medium` · `open:6d` · `effort:XS`
  - **File:** `scheduler/runner.py:113`
  - **Problem:** `loop.finish()` is called unconditionally after `thread.join(timeout=...)`. On timeout, the daemon thread is still running `loop.run()` — mutating `loop._messages` concurrently. `finish()` calls `tracker.finish(raw_messages=self._messages)` which serializes `_messages` via `json.dumps`. The daemon thread may be appending to `_messages` at the same time — data race on the list. CPython's GIL prevents crashes but the serialized output can be inconsistent (missing or partial messages).
  - **Fix:** Only call `loop.finish()` after confirming `not thread.is_alive()`. On timeout, defer `finish()` or take a snapshot: `msgs_copy = list(loop._messages); tracker.finish(raw_messages=msgs_copy)`.
  - **Source:** `review/2026-06-29`

- **Telegram `build_callbacks` doesn't wire `on_subagent_event_factory` — subagent output invisible** · `priority:medium` · `open:7d` · `effort:S`
  - **File:** `tg/callbacks.py:82-97`
  - **Problem:** `build_callbacks()` in `tg/callbacks.py` doesn't set `on_subagent_event_factory`. The default is `None`, so subagent stdout (worker, review, explore_files, web_research) is silently discarded. When a Telegram user triggers plan-work-review, they see no progress from worker/review subagents — only the final result.
  - **Fix:** Add an `on_subagent_event_factory` that returns a callback forwarding subagent lines via `_send()` (with a `[subagent-type]` prefix and message batching to avoid Telegram rate limits).
  - **Source:** `review/2026-06-29`

---

### 🟠 Architecture Debt

- **`write_text()` CRLF inconsistency — 10 call sites lack `newline="\n"`** · `priority:medium` · `open:0d` · `effort:S`
  - **Files:** `cli.py:691,699,1141`, `agent/loop.py:627`, `tools/cli_subagent.py:82`, `tools/_subagent_runner.py:112`, `scheduler/runner.py:134`, `agent/config_loader.py:259`, `scheduler/models.py:110`, `tools/output_filter.py:72`
  - **Problem:** The 2026-07-05 CRLF fix added `newline="\n"` to `EditTool` and `WriteTool`, establishing the invariant "all DAGI-written files have LF on disk." But 10 other `write_text()` call sites still use the Windows default (`newline=None`), which adds `\r` to every `\n` on Windows. Most impactful: plan files (`loop.py:627`), agents.md stubs and handoff files (`cli.py`), and scheduler output (`runner.py:134`) — all persist on disk and may be read by tools.
  - **Fix:** Add `newline="\n"` to all 10 call sites. Grep `\.write_text\(` to ensure no new sites are missed.
  - **Source:** `review/2026-07-05`

- **`tui/commands.py` imports from `cli.py` — layering violation** · `priority:medium` · `open:22d` · `effort:XS`
  - **Escalated 2026-07-03:** Open 22 days — blocks the cli.py→cli/ package split (can't restructure cli.py while TUI imports from it).
  - **File:** `tui/commands.py:59,73`
  - **Problem:** TUI depends on the CLI entry-point module (`_skill_invocation_message`, `_cmd_init`). Future `cli.py` refactors will break TUI imports.
  - **Fix:** Extract the two shared functions into `agent/cli_utils.py`; import from both.
  - **Source:** `_todo/todo_2026-06-13.md` #7

- **Dead code: `PlanSubAgent`, `ExploreFilesTool`, `WebResearchTool`, `SubAgentRunner`** · `priority:high` · `open:22d` · `effort:S`
  - **Escalated 2026-07-02:** Open 22 days with no fix commit — raised to high.
  - **Files:** `tools/explore_files.py`, `tools/web_research.py`, `tools/plan_subagent.py`, `agent/sub_agent.py`
  - **Problem:** None of these are registered in `create_tool_registry()` or used anywhere. They duplicate patterns from active code and confuse readers.
  - **Fix:** Audit for external callers; delete if unused.
  - **Source:** `_todo/todo_2026-06-13.md` #4

- **Split `cli.py` (1355 lines) → `cli/` package** · `priority:high` · `open:19d` · `effort:M`
  - **Escalated 2026-07-02:** Open 19 days. **Corrected 2026-07-05:** cli.py is 1355 lines (2.7× over 500-line standard) — the 2026-07-03 "correction" to 1173 was wrong; `wc -l` confirms 1355.
  - **File:** `cli.py`
  - **Problem:** 2.7× over the 500-line coding standard. Mixes rendering, callbacks, slash command handlers, subagent orchestration, and the REPL entry point.
  - **Suggested split:** `cli/rendering.py`, `cli/callbacks.py`, `cli/commands.py`, `cli/dispatch.py`, `cli/main.py`; root `cli.py` becomes a ~30-line launcher.
  - **Source:** `_todo/todo_2026-06-16.md` A1

- **`agent/prompts.py` still uses independent `Path(__file__).parent.parent`** · `priority:medium` · `open:8d` · `effort:XS`
  - **File:** `agent/prompts.py:5-6`
  - **Problem:** `_PROMPTS_DIR` and `_SUBAGENTS_DIR` are computed via `Path(__file__).parent.parent` — the same pattern that caused 4 confirmed divergence bugs before centralisation in `agent/__init__.py:DAGI_ROOT`. These 2 sites were missed in the 2026-06-27 sweep (`cli.py` ×2, `tui/app.py`, `tui/commands.py`, `tools/spawn_subagent.py`). They work correctly today because `prompts.py` lives inside `agent/`, but any restructuring would break them silently.
  - **Fix:** Replace with `from agent import DAGI_ROOT; _PROMPTS_DIR = DAGI_ROOT / ".dagi" / "prompts"` (and same for `_SUBAGENTS_DIR`).
  - **Source:** `review/2026-06-27`

- **`_parse_frontmatter` duplicated verbatim between `agent/skills.py` and `agent/workflows.py`** · `priority:medium` · `open:15d` · `effort:XS`
  - **Files:** `agent/skills.py:30-42`, `agent/workflows.py:30-42`
  - **Problem:** Identical regex patterns and function body. Any bug fix must be applied twice.
  - **Fix:** Extract to `agent/_frontmatter.py`; import in both files.
  - **Source:** `_todo/todo_2026-06-20.md` B1

- **`_extra_body` construction duplicated in `__init__` and `_handle_switch_model`** · `priority:medium` · `open:16d` · `effort:XS`
  - **Files:** `agent/loop.py:311-317`, `agent/loop.py:732-738`
  - **Problem:** Identical 6-line block in two places. New OpenRouter extensions must be added in both or silently break after a tier switch.
  - **Fix:** Extract `_build_extra_body() -> dict` method.
  - **Source:** `_todo/todo_2026-06-19.md` B2

- **`ask_user` callback has no deadlock protection (infinite wait)** · `priority:medium` · `open:17d` · `effort:XS`
  - **Files:** `tui/callbacks.py:73-74`, `tg/callbacks.py:65-66`
  - **Problem:** When `ask_user` is called with `timeout=None` (default in plan mode), `evt.wait(timeout=None)` blocks the agent thread indefinitely. If the TUI closes, the agent thread hangs permanently. The Telegram bot has an identical pattern (tracked separately as HIGH because the impact is worse — no user kill switch).
  - **Fix:** Always use a finite safety timeout: `safety = (timeout + 60) if timeout is not None else 600`.
  - **Source:** `_todo/todo_2026-06-18.md` D1

- **`_tools_from_list` limited to 9 hardcoded tool names** · `priority:medium` · `open:17d` · `effort:S`
  - **File:** `agent/tools.py:51-81`
  - **Problem:** Subagent registries can only reference 9 tools. Any other tool name (e.g., `skill`, `ask_user`, `git_status`) is silently dropped with a warning.
  - **Fix:** Either expand the registry map to cover all tools, or drive subagent registration from `create_tool_registry(tool_names=[...])` and delete `_tools_from_list`.
  - **Source:** `_todo/todo_2026-06-18.md` D2

- **Sidebar `_system_breakdown` reads stale `soul.md` path** · `priority:medium` · `open:17d` · `effort:XS`
  - **File:** `tui/utils.py:66`
  - **Problem:** `_toks(dagi_root / "soul.md")` — `soul.md` was moved to `.dagi/prompts/soul.md`. The old path doesn't exist; sidebar understates system prompt token count by ~150–300 tokens.
  - **Fix:** Change to `dagi_root / ".dagi" / "prompts" / "soul.md"`.
  - **Source:** `_todo/todo_2026-06-18.md` A2

- **`_system_breakdown()` reads disk on every Textual render cycle** · `priority:medium` · `open:17d` · `effort:XS`
  - **File:** `tui/utils.py:58-70` (called from `sidebar.py` render)
  - **Problem:** 3 file reads per render cycle for files that never change during a session.
  - **Fix:** Compute once in `Sidebar.__init__` and cache as `self._sys_parts`.
  - **Source:** `_todo/todo_2026-06-18.md` B1

- **`SkillTool.run()` reloads all skills from disk on every invocation** · `priority:medium` · `open:10d` · `effort:S`
  - **File:** `tools/skill.py:41-46`
  - **Problem:** Every `skill("name")` call creates a new `SkillLoader`, scans all skill root dirs, reads and parses every SKILL.md. `AgentLoop` already has `self.skills` pre-loaded. ~30 file reads per call.
  - **Fix:** Pass the pre-loaded skills list to `SkillTool` at construction time, or cache after first load.
  - **Source:** `_todo/todo_2026-06-25_2.md` A2

- **`WebFetchTool` silently upgrades HTTP→HTTPS for private IP addresses** · `priority:medium` · `open:10d` · `effort:XS`
  - **File:** `tools/web_fetch.py:123`
  - **Problem:** HTTP→HTTPS upgrade excludes `localhost` and `127.0.0.1` but not `192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, or `[::1]`. Agent fails to fetch local dev servers with a misleading error.
  - **Fix:** Expand exclusion regex to cover all RFC-1918 and loopback ranges.
  - **Source:** `_todo/todo_2026-06-25_2.md` A4

- **`filter_tool_output` temp files never cleaned up — unbounded accumulation** · `priority:medium` · `open:3d` · `effort:XS`
  - **File:** `tools/output_filter.py:68-72`, `agent/loop.py:287`
  - **Problem:** `filter_tool_output()` writes `tool_output_*.txt` files into `.dagi/temp/` via `mkstemp()`. No code path (session finish, loop exit, periodic cleanup) ever removes them. After 2 days of testing, 8 files have accumulated. Over weeks of heavy tool use (grep on large codebases, verbose bash output), this directory will grow unboundedly.
  - **Fix:** Add cleanup in `AgentLoop.finish()`: `shutil.rmtree(self._filter_temp, ignore_errors=True)` — temp files are session-scoped and serve no purpose after the session ends.
  - **Source:** `review/2026-07-02`

- **`tg/bot.py:153` uses deprecated `asyncio.get_event_loop()` — Python 3.14 breakage risk** · `priority:medium` · `open:1d` · `effort:XS`
  - **File:** `tg/bot.py:153`
  - **Problem:** `asyncio.get_event_loop()` is deprecated since Python 3.10 and emits `DeprecationWarning` in 3.12+. In Python 3.14 (which this project's conda env runs), it may raise `DeprecationWarning` or behave unexpectedly when called inside a running coroutine. Line 61 already correctly uses `asyncio.get_running_loop()`. The method `_run_agent_task` is `async`, so a running loop is guaranteed.
  - **Fix:** Replace `asyncio.get_event_loop()` with `asyncio.get_running_loop()` at line 153.
  - **Source:** `review/2026-07-04`

- **`BashTool.run()` doesn't handle `subprocess.TimeoutExpired`** · `priority:medium` · `open:17d` · `effort:XS`
  - **File:** `tools/bash.py:26-37`
  - **Problem:** `subprocess.run(..., timeout=timeout)` raises `TimeoutExpired` uncaught; propagates to `ToolRegistry.dispatch()` as a terse generic error with no recovery guidance for the LLM.
  - **Fix:** Catch and return `f"[Command timed out after {timeout}s — command did not finish in time]"`.
  - **Source:** `_todo/todo_2026-06-18.md` A3

---

### 🟡 Token Efficiency & Observability

- **Session cost tracking always shows `$—`** · `priority:high` · `open:17d` · `effort:S`
  - **File:** `agent/session.py:108`
  - **Problem:** Most API providers (including OpenRouter for many models) don't populate `usage.cost`. Sidebar shows `$—`, `session_end` has `total_cost: null`. No cost visibility makes it impossible to benchmark model tiers.
  - **Fix:** Fall back to computing cost from token counts using a per-model `pricing` section in `config.yaml` (input/output cost per 1M tokens).
  - **Source:** `_todo/todo_2026-06-18.md` C1

- **`thinking_tokens` (reasoning tokens) not recorded in session JSONL** · `priority:high` · `open:15d` · `effort:S`
  - **File:** `agent/session.py:100-118`
  - **Problem:** `completion_tokens_details.reasoning_tokens` is never extracted from API responses. For extended-thinking models (DeepSeek, Claude with thinking), reasoning tokens can be 50%+ of the completion budget — invisible in post-session analysis.
  - **Fix:** Add `thinking_tokens: int | None = None` to `MessageNode`; extract in `record_assistant()`; include `total_thinking_tokens` in `session_end`.
  - **Source:** `_todo/todo_2026-06-20.md` C1

- **Cache hit visibility in TUI sidebar** · `priority:high` · `open:19d` · `effort:S`
  - **File:** `agent/loop.py:480-487`, `tui/sidebar.py`
  - **Problem:** `cache_prompt: true` is sent to OpenRouter, but `usage.prompt_tokens_details.cached_tokens` is never read. Users have no visibility into whether prompt caching is working.
  - **Fix:** Extract `cached_tokens` from `usage.prompt_tokens_details`; pass through `on_token_update`; display in sidebar as `{cached_tok}↩ cached`.
  - **Source:** `_todo/todo_2026-06-16.md` C1

- **Tool result content not truncated in JSONL logs** · `priority:medium` · `open:15d` · `effort:XS`
  - **File:** `agent/session.py:129-135`
  - **Problem:** `record_tool_end(name, result_str)` writes the full result. Compare with `record_subagent_end` which truncates to 500 chars. Large tool results (file reads, grep output, base64) are the primary driver of log disk consumption.
  - **Fix:** Truncate to 2000 chars in `record_tool_end`; record `result_length` for reference.
  - **Source:** `_todo/todo_2026-06-20.md` C2

- **Token efficiency benchmark harness** · `priority:high` · `open:16d` · `effort:M`
  - **Problem:** No way to measure whether code changes improve or degrade token efficiency. Harbor/Terminal-bench measure task correctness but not tokens/cost/continuation count per task.
  - **Fix:** `scripts/benchmark_token_efficiency.py` that parses session JSONL files and produces per-task metrics: `input_tokens`, `output_tokens`, `thinking_tokens`, `tool_call_count`, `continuation_count`, `cache_hit_tokens`.
  - **Source:** `_todo/todo_2026-06-19.md` D3

- **GNHF self-improvement loop — never bootstrapped (70 days stale)** · `priority:high` · `open:70d`
  - **Current:** The `review-session` skill (reworked 2026-07-03 to accept free-text session selection and accumulate cross-session findings into one running report) and `improve-yourself` workflow exist; `.dagi/self-review/` has 5 files all from April 2026; 209 session logs have accumulated. The entire GNHF feedback cycle has never run.
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

- **PDF reading support for `ReadTool`** · `priority:medium` · `effort:S`
  - Add PDF support using `PyMuPDF` (fitz) with page range support. Fall back gracefully if not installed.
  - **Source:** `_todo/todo_2026-06-19.md` D1

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
  - **Current:** Transient API error retry with exponential backoff. TUI error-pauses on retry exhaustion.
  - **Next:** Add `os.killpg` to `tools/bash.py`; improve API key validation at startup.

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
  - 198 JSONL files accumulating unboundedly. Add `max_session_logs` config field (default 100) and prune oldest files at `SessionTracker.__init__`.
  - **Source:** `_todo/todo_2026-06-19.md` C1

- **Add pre-flight path check to memory-ingest** · `priority:low` · `review-item`
  - Agent makes 6+ tool calls discovering failing `dagi-memory/` paths. Add pre-flight check to SKILL.md.
  - **Source:** Session `2026-04-26` self-review

- **Fix `pyproject.toml` dependencies** · `priority:low`
  - Add `typer`, `rich`, `textual`; remove `nicegui`, `markdown`, `matplotlib`.
  - **Source:** `_todo/todo_2026-06-16.md` F3

- **`langchain` + `langchain-openai` are dead dependencies in `requirements.txt`** · `priority:low` · `open:7d` · `effort:XS`
  - **File:** `requirements.txt:8-9`
  - **Problem:** `langchain>=1.3.4` and `langchain-openai>=1.2.2` are listed as core required deps, but no Python file in the project imports from either package. They add ~100MB of transitive dependencies (numpy, pydantic, aiohttp, etc.) for zero value. Likely a remnant from an earlier architecture. Additionally, CVE-2026-34070 (CVSS 7.5) is a path traversal in `langchain_core/prompts/loading.py` — having the package installed exposes this vulnerability even though DAGI doesn't call it.
  - **Fix:** Remove both lines from `requirements.txt`.
  - **Source:** `review/2026-06-28`, CVE note added `review/2026-06-30`

- **Dead `ChatSession.lock` field in `tg/session.py`** · `priority:low` · `open:5d` · `effort:XS`
  - **File:** `tg/session.py:13`
  - **Problem:** `ChatSession` declares `lock: threading.Lock = field(default_factory=threading.Lock)` but no code in the `tg/` package ever acquires or releases it. The `busy` flag is the actual concurrency guard. The unused lock misleads readers into thinking thread-safe access patterns are in place when they are not.
  - **Fix:** Remove the `lock` field from `ChatSession` and its `import threading` if no other usage remains.
  - **Source:** `review/2026-06-30`

- **`config.example.yaml:85` stale BM25 reference in `memory_root` comment** · `priority:low` · `open:3d` · `effort:XS`
  - **File:** `config.example.yaml:85`
  - **Problem:** Comment says "persistent knowledge retrieval (BM25)" — BM25 was removed 2026-06-27 in favor of subagent-based grep+traversal. Stale reference confuses readers into thinking BM25 is still used.
  - **Fix:** Change to "persistent knowledge wiki (subagent-based retrieval)".
  - **Source:** `review/2026-07-02`

- **Telegram bot redundant `config.project_path` assignment** · `priority:low` · `open:5d` · `effort:XS`
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

> **Long-horizon ideation:** see [fable_docs_self_improve_moonshots.md](fable_docs_self_improve_moonshots.md) (2026-07-11) — 10 far-fetched architecture/process ideas for making DAGI self-learning and self-improving, with a phased roadmap. Recommended starting pair: counterfactual replay engine + experience distillation.

### [High] Bootstrap the self-improvement loop

**Type:** workflow | **Generated:** 2026-05-03

**Root cause:** The `/improve-yourself` workflow has never been run. Review items are waiting. 209 session logs have accumulated; self-review last ran 70 days ago (2026-04-26).

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

- [x] Pipe-based subagent architecture — replaced file-IPC + `CREATE_NEW_CONSOLE` terminal spawning with `subprocess.Popen(stdout=PIPE)`. New `tools/_subagent_runner.py` with event relay, PID tracking, and `extend_timeout` tool. (~2026-06-06)

- [x] BM25 wiki retrieval in memory-query skill — `agent/memory_retriever.py` + `.dagi/skills/memory-query/bm25_query.py`. (Superseded 2026-06-27 — replaced with subagent-based grep+traversal)

- [x] Transient API error retry — exponential backoff (2^n s, cap 60s) for 429/5xx; configurable `api_error_retries`; compaction snapshots messages before API call. (2026-06-08)

- [x] Harbor harness Fix A — `DagiAgent.run()` uses `tempfile.mkdtemp()` for `config.project_path`. (2026-06-13)

- [x] Harbor harness Fix B — `system_prompt_preamble` field in `AgentConfig`; injected first in system prompt at all 3 build sites. (2026-06-13)

- [x] RAM watchdog in test suite — `tests/conftest.py` auto-use fixture monitors system RAM; 70% → `pytest.fail()`; 90% → `os._exit(1)`. (~2026-06-13)

- [x] Soul/agents.md re-injected after plan-mode transitions — `_build_preamble(dagi_root)` extracted; called from `__init__`, `_rebuild_for_normal_mode`, `_rebuild_for_plan_mode`. (2026-06-17)

- [x] TUI `loop.finish()` now called on agent work completion — session logs properly finalized with `session_end` record. (2026-06-17)

- [x] Harden compaction failure path — `_compact_context()` catches all exceptions from `compact_tool.compact()`, emits a warning, and returns `_NO_COMPACTION`. (2026-06-21)

- [x] `provider_order` snapshotted and restored on tier switch — 6th field in `_base_config_snapshot`; copied from `tier_cfg`; restored on "default" switch. (2026-06-21)

- [x] `DAGI_ROOT` centralised in `agent/__init__.py` — replaced 4 independent `Path(__file__).parent.parent` expressions in `agent/tools.py`, `tools/cli_subagent.py`, `tools/_subagent_runner.py`, `agent/loop.py`. (2026-06-21)

- [x] `tempfile.mktemp()` TOCTOU race fixed at 3 sites — replaced with atomic `mkstemp()` + `os.close(fd)` in `tools/_subagent_runner.py:96` and `tools/cli_subagent.py:70,73`. (2026-06-26)

- [x] `SpawnCliSubagentTool` migrated to `run_subagent()` — pipe deadlock fixed, TUI relay wired, PID tracking added, timeout returns resumable dict, prompt-file cleanup in `try/finally`. (2026-06-26)

- [x] Temp file leak on subagent timeout fixed — `task_file: Path` added to `_SubagentState`; `_poll_until` now calls `state.task_file.unlink()` on process exit, covering both normal and resume paths. (2026-06-26)

- [x] 3-site system-prompt divergence eliminated — `_assemble_system_string(dagi_root)` is the single assembly point; all 3 build sites delegate to it. Eliminates the class of divergence bugs (soul dropped, memory_root missing, etc.). (2026-06-27)

### Archived (> 30 days)
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
