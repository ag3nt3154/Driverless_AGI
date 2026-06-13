# TODO

## Work Queue

- **Persistent Memory System** · `priority:high` · `impact:high` · `in-progress`
  - **Current:** `memory-query` skill uses BM25 (`bm25_query.py`) for fast topic retrieval. System prompt encourages agent to call `skill("memory-query")` after receiving any substantive task (agent uses judgement — skips for greetings/trivial requests).
  - **Ideal:** CLI slash commands for `memory-ingest`, `memory-lint`, `memory-query` (wiring into `cli.py`).
  - **Next:** Add `/memory-ingest`, `/memory-lint`, `/memory-query` slash commands to `cli.py`; ingest initial source material into `dagi-memory/raw/` and run `memory-ingest`.

- **Project / Folder Scoping** · `priority:high` · `impact:high`
  - **Current:** Path guard wired into Read/Write/Edit/Grep/Find (`tools/_path_guard.py`). Roots hardcoded to `[dagi_root, cwd]`. BashTool unsandboxed.
  - **Ideal:** `allowed_paths` and `blocked_commands` configurable in `config.yaml`; per-project scope UI; BashTool command blacklist.
  - **Next:** Add `allowed_paths` / `blocked_commands` keys to `config.yaml` and read them in `agent/tools.py`.

- **Error Handling & Retries** · `priority:high` · `impact:high` · `partial`
  - **Current:** Transient API error retry with exponential backoff (429, 500, 502, 503, connection/timeout). TUI now error-pauses (same semantics as ESC pause) when all retries are exhausted — session stays alive, user sends next message to retry. CLI path unaffected (already preserved context via `loop._messages` return). `_active_loop` pre-assigned in `_agent_work` so non-transient raises also preserve context. `api_error_retries` configurable in `config.yaml` (default 3).
  - **Ideal:** `os.killpg` on BashTool timeout; actionable empty-API-key error.
  - **Next:** Add `os.killpg` to `tools/bash.py`; improve API key validation at startup.

- **Validate project root in system prompt against actual filesystem** · `priority:high` · `impact:high` · `review-item`
  - **Current:** System prompt can contain an incorrect project root (e.g., inside `raw/` instead of actual `DAGI_ROOT`), causing all tool paths to resolve incorrectly.
  - **Ideal:** `cli.py` / `main.py` validates the project root at startup and warns if it looks wrong (e.g., path ends in `raw/`, `wiki/`, or similar data dirs).
  - **Next:** Review plan · implement · mark done
  - **Source:** Session `2026-04-26_15-20-10` · [review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) · [plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

- **Extend path guard to cover full dagi-memory tree on G:** · `priority:high` · `impact:high` · `review-item`
  - **Current:** Path guard allows only a single subdirectory of `G:\My Drive\black_grimoire\dagi-memory\`, blocking sibling dirs (e.g., `wiki/` blocked when only `raw/` was allowed).
  - **Ideal:** Path guard allows the full `dagi-memory/` tree (or whatever the configured `allowed_paths` list specifies) rather than individual subdirectories.
  - **Next:** Review plan · implement · mark done
  - **Source:** Session `2026-04-26_15-20-10` · [review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) · [plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

- **Multi-agent / parallel clones** · `priority:medium` · `impact:high`
  - **Current:** Subagents run sequentially as pipe subprocesses (`tools/_subagent_runner.py`). Output streams to the main TUI `ConversationPane` with a `[subagent-type]` label. Each subagent declares its own `tools:` list in `.dagi/subagents/<type>/subagent_config.yaml`. Agent can extend a timed-out subagent via `extend_subagent_timeout(pid, extra_seconds)`.
  - **Ideal:** Parallel spawning (multiple subagents concurrently); task queue / manifest structure; each subagent's output visible in TUI with distinct label simultaneously.
  - **Next:** Prototype parallel dispatch — agent calls `spawn_*` multiple times in one turn; `_active` dict already supports multiple PIDs concurrently; TUI relay callback already handles concurrent event streams from different subagent types.

- **Subagent pause propagation** · `priority:low` · `impact:low`
  - **Current:** ESC pauses the parent loop at its safe checkpoint, but the subagent subprocess continues running.
  - **Ideal:** Parent's pause signal propagates to the active subagent (e.g., via stdin signal or `proc.terminate()`).
  - **Next:** Design and implement pause/resume signalling into `_subagent_runner.py`.

- **Dynamic tool descriptions** · `priority:medium` · `impact:medium`
  - **Current:** Tool schemas are static — same description regardless of model or context.
  - **Ideal:** Tool descriptions tailored per model or context at runtime.
  - **Next:** Research approach; prototype in `agent/tools.py`.

- **Per-project config (work in projects)** · `priority:medium` · `impact:medium` · `partial`
  - **Current:** `resolve_model_config(project_path=...)` now loads `{project_path}/.dagi/config.yaml` and merges it over root. Project scalars win; model catalog entries are shallow-merged. `agent/prompts.py` resolves `main_system.md` and `soul.md` from the project folder first. Core config merge infra is complete (Tasks 1–3 done).
  - **Ideal:** Dedicated project folders with per-project `config.yaml` overrides; agent scoped to project on startup; TUI `/project <path>` command.
  - **Next:** Wire `project_path` into CLI/TUI startup (`cli.py`, `tui/app.py`) so the agent is automatically scoped when launched from a project directory.

- **Sample project for testing** · `priority:medium` · `impact:medium`
  - **Current:** No example task, source files, or reference output exists for validating agent behavior.
  - **Ideal:** Example task + source files + expected tool call sequence + expected output for regression testing.
  - **Next:** Define a representative task and document expected tool call sequence and output.

- **Add pre-flight path check to memory-ingest** · `priority:low` · `impact:low` · `review-item`
  - **Current:** Agent makes 6+ tool calls discovering that `dagi-memory/` paths fail — wastes turns on path discovery.
  - **Ideal:** SKILL.md includes a pre-flight check that sets a path-mode flag on the first operation, skipping wasted discovery.
  - **Next:** Review plan · implement · mark done
  - **Source:** Session `2026-04-26_15-24-09` · [review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) · [plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

- **Fix `pyproject.toml` dependencies** · `priority:low` · `impact:low`
  - **Current:** `typer`, `rich`, `textual` missing from declared deps; `crawl4ai` already added; `streamlit` dropped. `requirements.txt` now correctly documents hard vs optional deps.
  - **Ideal:** `pyproject.toml` matches actual runtime requirements; `pip install -e .` installs all CLI+TUI dependencies.
  - **Next:** Add `typer`, `rich`, `textual` to `pyproject.toml`; remove `nicegui`, `markdown`, `matplotlib` if unused.

---

## Self-Improvement Queue

> Entries appended automatically by the `/improve-yourself` workflow after each test run.
> Each entry has a verdict (APPROVED / REJECTED / INCONCLUSIVE), primary metrics, and an
> implementation description ready to apply.

### [High] Bootstrap the self-improvement loop

**Type:** workflow | **Generated:** 2026-05-03

**Root cause:** The `/improve-yourself` workflow has never been run. Review items in the Work Queue are waiting to be picked up, tested, and described.

**Quick action:** Start a DAGI session and invoke `/improve-yourself` — the workflow picks the highest-priority unimplemented `review-item` from the Work Queue, runs baseline and after tests in an isolated snapshot, and writes a verdict + implementation description here. (~15–30 min per item)

- [ ] Invoke `/improve-yourself` in a DAGI session
- [ ] Review the verdict block appended below by the workflow
- [ ] Apply the implementation description in `## Tested Improvements`
- [ ] Mark the originating Work Queue item as done

---

## Tested Improvements

> Entries written by the `/improve-yourself` workflow. Each entry contains a complete,
> evidence-backed implementation description ready to apply — exact diffs, test evidence,
> and verdict rationale. Apply the diffs listed, then check off the originating Work Queue item.

---

## Done

- [x] Pipe-based subagent architecture — replaced file-IPC + `CREATE_NEW_CONSOLE` terminal spawning with `subprocess.Popen(stdout=PIPE)`. Deleted `agent/ipc.py` and `tools/_terminal_subagent.py`. New `tools/_subagent_runner.py` runs the subprocess, relays newline-delimited JSON events to the main TUI `ConversationPane` (with `[subagent-type]` label), and polls `proc.poll()` every 2 s against a deadline. New `tools/extend_timeout.py` (`ExtendSubagentTimeoutTool`) lets the agent extend an in-flight subagent's deadline by PID. `SpawnSubagentTool` generates the handoff path at spawn time (`.dagi/handoffs/{type}_{uuid8}.md`), returns it as the tool result after the subagent exits. Each subagent type now declares its tools explicitly in `subagent_config.yaml`; `_scope_tools()` deleted, `_tools_from_list()` added. 81 tests pass.

- [x] TUI submodule refactor — `tui.py` (819 lines) decomposed into a `tui/` package: `utils.py` (helpers + `_Stats`), `conversation.py` (`ConversationPane`), `prompt_input.py` (`PromptInput`), `sidebar.py` (`Sidebar`), `commands.py` (`SlashCommandsMixin`), `callbacks.py` (`build_callbacks()` free function), `app.py` (`DagiApp`, ~180 lines), `__init__.py`. Root `tui.py` is now a 30-line launcher. All behaviour preserved; `python tui.py --help` and all imports verified.

- [x] Unified skill invocation — slash commands (`/plan-work-review`, etc.) in both CLI and TUI no longer eagerly inject skill content into the user message. They now produce a plain `"Invoke the \`skill-name\` skill."` instruction, causing the LLM to call `skill()` itself — identical to mid-task internal invocations. Removed `_inject_skill_content()` (cli.py) and `_inject_skill()` (tui.py); added single shared `_skill_invocation_message()` in cli.py imported by tui.py.

- [x] Plan mode revision loop — after writing a plan, agent calls `show_plan` to present it to the user. User can request revisions; agent revises and calls `show_plan` again until approved. On approval, agent calls `exit_plan_mode`, outputs one implementation-start sentence ("Starting implementation — Phase 1: …"), and immediately begins tool calls. Wired via `main_system.md` update; `show_plan` tool already handled the loop mechanics. Two bugs fixed in the same session: `_continuation_count` was never reset between `run()` calls (now reset at the start of each `run()`), and `plan_mode_exited` was dead code (field and check removed).

- [x] TUI text wrap + multi-line input — `ConversationPane(RichLog)` now renders with `wrap=True` so long lines fold instead of truncating. Input replaced with `PromptInput(TextArea)`: Enter submits the full (possibly multi-line) message; Shift+Enter inserts a newline. Input box height increased to 5 rows.

- [x] ESC pause button in TUI — pressing ESC pauses the agent at the end of the current iteration (safe checkpoint: all tool calls in one LLM response complete before blocking). `AgentLoop._pause_event: threading.Event` (set = running) is checked at the top of each `while True` iteration. `pause()` clears it; `inject_and_resume(message)` appends the user message to `_messages` then sets it. TUI sidebar shows `⏸ Paused`; re-enabling input lets the user type a redirect message to continue.

- [x] Full Textual TUI (`tui.py`) — vertical split layout with always-visible sidebar showing live token stats, context window breakdown by role (system/user/assistant/tools/reserve) with `~` estimates and 80%/95% colour warnings, model status indicator, and `/model <id>` switching. `ConversationPane(RichLog)` preserves Rich panel style and scrolls freely during agent runs. Agent runs on a daemon thread with `call_from_thread` bridging all `AgentCallbacks` to the Textual main loop. `cli.py` retained for piped/non-interactive use.

- [x] Single response flag — every no-tool-call response must end with `<<END_OF_RESPONSE>>` (applies to greetings, answers, and completions alike). `<<TASK_END>>` kept as a silent legacy alias. Recovery injection replaced hardcoded `"continue"` with a proper prompt in `.dagi/prompts/main/continue.md`. Flag rules placed at the end of `main_system.md` for reliable model compliance. 11 unit tests in `tests/test_continuation.py`.
- [x] Transient API error retry — 429, 500, 502, 503, connection errors, and timeout errors are retried with exponential backoff (`2^attempt` seconds, capped at 60s) up to `api_error_retries` times (default 3, configurable in `config.yaml`). Non-transient errors propagate immediately. Retry counter resets per loop iteration. Compaction in `tools/compact.py` now snapshots `_messages` before the API call and restores on failure. 11 new tests in `tests/test_continuation.py`.
- [x] Direct `api_key` in config.yaml — model entries now support `api_key: "sk-..."` as an alternative to `api_key_env`. Direct key takes precedence; empty string falls through to env var lookup. Prevents silent fallback to `OPENAI_API_KEY` env var. 3 unit tests in `tests/test_config_loader.py`.

- [x] GNHF skill — cross-session iterative development with committed milestones. New `tools/git.py` adds `git_status`, `git_commit`, `git_rollback` tools (branch-guarded to `dagi` branch). Skill at `.dagi/skills/gnhf/SKILL.md` teaches the loop: init → plan milestone → implement → verify → commit + append note → repeat. Scripts at `.dagi/skills/gnhf/scripts/init.py` and `append_note.py` manage `.dagi/gnhf/notes.md` — a per-commit freeform log that carries context across sessions.

- [x] Prompt architecture refactor — `main_system.md` trimmed to harness-only (tools, plan mode trigger). Behavioral guidelines, memory rules, and Plan-Work-Review Cycle moved to `.dagi/agents.md`. Persona stays in `soul.md`. Unified behavioral rules merged from `temp_system_prompt.txt` (ambiguity calibration, invariants checklist, hard stops, token budgets). Redundant "read agents.md" instruction removed — both files are auto-prepended by `loop.py`.

- [x] Terminal-spawned subagents with 5-minute persistence — `web_research`, `explore_files`, and `plan` subagents now spawn in visible `CREATE_NEW_CONSOLE` terminal windows instead of running in-process. Each terminal uses the correct model tier (worker/advanced) resolved from `config.yaml`. Main terminal shows a Rich live spinner with elapsed time. After each task, the terminal displays a 5-minute countdown and auto-closes. Shared spawning logic in `tools/_terminal_subagent.py`; tool registry for subprocess in `agent/tools.build_subagent_registry()`; `cli.py` extended with `--subagent-type` and `--plan-file` hidden args.
- [x] BM25 wiki retrieval in memory-query skill — `agent/memory_retriever.py` provides BM25 helpers; `.dagi/skills/memory-query/bm25_query.py` is a self-contained CLI script the agent runs in Step 3. Returns ranked `{score, path}` JSON. SKILL.md updated to call the script, review scores, and fall back to grep if needed. System prompt updated to encourage memory-query after receiving any substantive task.
- [x] Auto compaction for long contexts — Pi-style compaction in `agent/loop.py` (`_compact_context`). Summarizes middle history, preserves system prompt + recent tail, carries forward prior summaries.
- [x] Plan mode — Full read-only planning mode in `agent/loop.py` (`plan_mode` flag, `plan_file` path). BashTool omitted, WriteTool/EditTool restricted to plan document.
- [x] `web_search` and `web_fetch` in plan mode — direct web tools are now always registered in plan mode (`agent/tools.py`), alongside the `web_research`/`explore_files` subagent launchers. Previously they only appeared in the no-config fallback path (tests only).
- [x] Web research tools — `web_search`, `web_fetch`, `web_research`, `explore_files` available in `tools/`. Powered by DuckDuckGo, httpx, beautifulsoup4, crawl4ai.
- [x] Multi-root search for find and grep — `FindTool` and `GrepTool` accept an optional `path` argument; when omitted, search all `allowed_roots` simultaneously (deduped). Implemented in `tools/find.py` and `tools/grep.py`.
- [x] Add path resolution warning to memory-ingest SKILL.md — "Path Roots" table at top of `.dagi/skills/memory-ingest/SKILL.md` documents tool vs. bash split for non-C: drives.
- [x] Add path resolution warning to memory-add SKILL.md — same "Path Roots" table added to `.dagi/skills/memory-add/SKILL.md`.
- [x] Fix redundant skill-load instruction in memory-ingest Step 6 — Step 6 now says "Call `skill("memory-add")` **once**… do NOT call `skill("memory-add")` again."
- [x] Add bash-based archiving template to memory-ingest Step 5 — explicit `mkdir`/`type … | Out-File`/`del` template in Step 5.
- [x] Add bash-fallback guidance to memory-ingest for G: path operations — covered by the Path Roots section added to the skill.
- [x] Recommend `dir` not `ls` in memory skills for Windows paths — both memory-ingest and memory-add Path Roots tables use `dir` in all bash examples for non-C: drives.
- [x] RAM watchdog in test suite — `tests/conftest.py` auto-use fixture monitors system RAM via a daemon thread (0.5 s poll). At 70%: interrupts the running test with `pytest.fail()`. At 90%: hard-kills the process with `os._exit(1)` to protect the machine. Catches infinite-loop OOM bugs like the MagicMock + `yaml.safe_load` issue that previously killed the machine.
