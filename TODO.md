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

- **Error Handling & Retries** · `priority:high` · `impact:high`
  - **Current:** `ToolRegistry.dispatch()` catches exceptions. `EditTool` returns errors rather than raising. BashTool times out but doesn't kill process group. Continuation (mid-task stall recovery) implemented.
  - **Ideal:** Exponential backoff for 429/5xx (initial 1s, max 60s, 3 attempts); fail-fast for 401/400; `os.killpg` on BashTool timeout; actionable empty-API-key error.
  - **Next:** Add retry loop with backoff to `agent/loop.py`; add `os.killpg` to `tools/bash.py`.

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

- **Multi-agent / parallel clones** · `priority:medium` · `impact:high` · `in-progress`
  - **Current:** ALL subagents (`web_research`, `explore_files`, `plan`) spawn visible terminal windows via `subprocess.CREATE_NEW_CONSOLE`. Parent communicates via file-based IPC (`agent/ipc.py`); main terminal shows a Rich live spinner while waiting. Each terminal uses the appropriate model tier (worker / advanced) resolved from `config.yaml`. Terminal persists 5 minutes after task completion with a countdown banner. `cli_subagent.py` kept as a standalone tool for full-agent terminal use.
  - **Ideal:** Parallel spawning (multiple subagents concurrently); task queue / manifest structure; multi-pane UI in the main terminal showing all subagent outputs simultaneously.
  - **Next:** Prototype parallel dispatch (multiple terminal subagents in one agent turn); add a task manifest so subagents can coordinate without conflicts.

- **Subagent polling** · `priority:medium` · `impact:medium`
  - **Current:** Subagents run until completion with no oversight from the main agent.
  - **Ideal:** Main agent should be able to periodically inspect a running subagent's terminal output and make a judgment on whether it is stuck, then intervene or kill it.
  - **Next:** Design a polling mechanism (time-based or event-based); implement inspection tool in `agent/ipc.py`; add retry/kill logic to worker/review spawn wrappers.

- **Dynamic tool descriptions** · `priority:medium` · `impact:medium`
  - **Current:** Tool schemas are static — same description regardless of model or context.
  - **Ideal:** Tool descriptions tailored per model or context at runtime.
  - **Next:** Research approach; prototype in `agent/tools.py`.

- **Per-project config (work in projects)** · `priority:medium` · `impact:medium`
  - **Current:** No per-project config support. Depends on Project / Folder Scoping being completed first.
  - **Ideal:** Dedicated project folders with per-project `config.yaml` overrides; agent scoped to project on startup.
  - **Next:** Implement after Project / Folder Scoping is complete.

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
  - **Current:** `typer` and `rich` missing from declared deps; `crawl4ai` already added; `streamlit` dropped.
  - **Ideal:** `pyproject.toml` matches actual runtime requirements; `pip install -e .` installs all CLI dependencies.
  - **Next:** Add `typer`, `rich` to `pyproject.toml`.

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

- [x] Continuation via `<<TASK_END>>` flag — agent must include `<<TASK_END>>` in its final response; if it stops without the flag the harness auto-injects `"continue"` and resumes (safety valve: `max_continuations`, default 10). Implemented in `agent/loop.py`; prompt instruction in `.dagi/prompts/main/main_system.md`; 7 unit tests in `tests/test_continuation.py`.

- [x] GNHF skill — cross-session iterative development with committed milestones. New `tools/git.py` adds `git_status`, `git_commit`, `git_rollback` tools (branch-guarded to `dagi` branch). Skill at `.dagi/skills/gnhf/SKILL.md` teaches the loop: init → plan milestone → implement → verify → commit + append note → repeat. Scripts at `.dagi/skills/gnhf/scripts/init.py` and `append_note.py` manage `.dagi/gnhf/notes.md` — a per-commit freeform log that carries context across sessions.

- [x] Prompt architecture refactor — `main_system.md` trimmed to harness-only (tools, plan mode trigger). Behavioral guidelines, memory rules, and Plan-Work-Review Cycle moved to `.dagi/agents.md`. Persona stays in `soul.md`. Unified behavioral rules merged from `temp_system_prompt.txt` (ambiguity calibration, invariants checklist, hard stops, token budgets). Redundant "read agents.md" instruction removed — both files are auto-prepended by `loop.py`.

- [x] Terminal-spawned subagents with 5-minute persistence — `web_research`, `explore_files`, and `plan` subagents now spawn in visible `CREATE_NEW_CONSOLE` terminal windows instead of running in-process. Each terminal uses the correct model tier (worker/advanced) resolved from `config.yaml`. Main terminal shows a Rich live spinner with elapsed time. After each task, the terminal displays a 5-minute countdown and auto-closes. Shared spawning logic in `tools/_terminal_subagent.py`; tool registry for subprocess in `agent/tools.build_subagent_registry()`; `cli.py` extended with `--subagent-type` and `--plan-file` hidden args.
- [x] BM25 wiki retrieval in memory-query skill — `agent/memory_retriever.py` provides BM25 helpers; `.dagi/skills/memory-query/bm25_query.py` is a self-contained CLI script the agent runs in Step 3. Returns ranked `{score, path}` JSON. SKILL.md updated to call the script, review scores, and fall back to grep if needed. System prompt updated to encourage memory-query after receiving any substantive task.
- [x] Auto compaction for long contexts — Pi-style compaction in `agent/loop.py` (`_compact_context`). Summarizes middle history, preserves system prompt + recent tail, carries forward prior summaries.
- [x] Plan mode — Full read-only planning mode in `agent/loop.py` (`plan_mode` flag, `plan_file` path). BashTool omitted, WriteTool/EditTool restricted to plan document.
- [x] Web research tools — `web_search`, `web_fetch`, `web_research`, `explore_files` available in `tools/`. Powered by DuckDuckGo, httpx, beautifulsoup4, crawl4ai.
- [x] Multi-root search for find and grep — `FindTool` and `GrepTool` accept an optional `path` argument; when omitted, search all `allowed_roots` simultaneously (deduped). Implemented in `tools/find.py` and `tools/grep.py`.
- [x] Add path resolution warning to memory-ingest SKILL.md — "Path Roots" table at top of `.dagi/skills/memory-ingest/SKILL.md` documents tool vs. bash split for non-C: drives.
- [x] Add path resolution warning to memory-add SKILL.md — same "Path Roots" table added to `.dagi/skills/memory-add/SKILL.md`.
- [x] Fix redundant skill-load instruction in memory-ingest Step 6 — Step 6 now says "Call `skill("memory-add")` **once**… do NOT call `skill("memory-add")` again."
- [x] Add bash-based archiving template to memory-ingest Step 5 — explicit `mkdir`/`type … | Out-File`/`del` template in Step 5.
- [x] Add bash-fallback guidance to memory-ingest for G: path operations — covered by the Path Roots section added to the skill.
- [x] Recommend `dir` not `ls` in memory skills for Windows paths — both memory-ingest and memory-add Path Roots tables use `dir` in all bash examples for non-C: drives.
