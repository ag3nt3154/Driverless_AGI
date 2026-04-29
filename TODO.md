# TODO

## Done

- [x] Auto compaction for long contexts — Pi-style compaction in `agent/loop.py` (`_compact_context`). Summarizes middle history, preserves system prompt + recent tail, carries forward prior summaries.
- [x] Plan mode — Full read-only planning mode in `agent/loop.py` (`plan_mode` flag, `plan_file` path). BashTool omitted, WriteTool/EditTool restricted to plan document.

## In Progress

#### Persistent Memory System — Wiki infrastructure complete, not yet populated

**Status:** Infrastructure is fully built but empty. The agent does not yet use the memory system autonomously.

**What exists:**
- Wiki at `.dagi/memory/wiki/` — topic folders, entity pages, wikilinks, indexes
- Skill files under `.dagi/skills/`: `memory-add`, `memory-ingest`, `memory-lint`, `memory-query`, `create-skill`
- `SkillTool` registered in `create_tool_registry()` — skills loadable via the `skill` tool

**What is missing (next steps):**
- Ingest initial source material into `.dagi/memory/raw/` and run `memory-ingest`
- Populate the wiki with user context: environment, preferences, recurring decisions
- Wire memory-query into the system prompt so the agent consults the wiki on session start
- Add a `memory` CLI slash command for `memory-ingest`, `memory-lint`, `memory-query`

**Files:** `.dagi/skills/`, `agent/tools.py`, `agent/loop.py`, CLI

---

## Backlog

### High Impact

#### 1. Project / Folder Scoping _(partially done)_

Path validation infrastructure exists (`tools/_path_guard.py`, `validate_path`, `PathNotAllowedError`) and is wired into ReadTool, WriteTool, EditTool, GrepTool, FindTool. BashTool is intentionally excluded from sandboxing.

**What is missing:**
- `allowed_paths` / `blocked_commands` keys in `config.yaml` (currently hardcoded to `[dagi_root, cwd]`)
- UI to configure scope per-project
- BashTool command blacklist (only argument-path sandboxing exists today)

**Files:** `agent/tools.py`, `config.yaml`

---

#### 2. Error Handling & Retries _(partially done)_

`ToolRegistry.dispatch()` catches exceptions and returns error strings. `EditTool` returns errors rather than raising. BashTool uses `subprocess.run(timeout=)` but does not kill the process group.

**What is missing:**
- Exponential backoff for transient API errors (429, timeout, 5xx) — initial 1s, max 60s, 3 attempts
- Fail-fast for permanent errors (401, 400)
- `on_error_retry` callback for UIs
- `BashTool`: kill process group on timeout via `os.killpg`
- `EditTool`: raise exception on not-found instead of returning error string
- Empty API key → fail immediately with actionable message

**Files:** `agent/loop.py`, `tools/bash.py`, `tools/edit.py`

---

### Medium Impact

- [ ] Multi-agent / parallel clones — spawn independent copies of the agent to tackle separate tasks concurrently, each with their own tool access and loop. Useful for covering more ground simultaneously. Requires coordination to avoid file conflicts (e.g., each clone works on distinct files, or a shared queue/lock mechanism).

**Deliverables:**
- Clone/spawn function that creates independent agent loops
- Task queue or manifest to distribute work
- Conflict avoidance: per-clone file locks, or assign disjoint file sets
- Merge/consolidate results back to main agent
- UI support: show multiple agent threads in web UI

**Files:** `agent/loop.py`, `agent/tools.py`, web UIs

---

- [ ] Dynamic generation of tool descriptions — tailor tool schemas per model or context
- [ ] Ability to work in projects — dedicated project folders with per-project config (depends on #1)
- [ ] Sample project to test dagi — example task + source files + expected output for validation
- [ ] Fix `pyproject.toml` — missing `typer`, `rich`, `streamlit`, `streamlit-autorefresh` from deps

---

## Session Review Queue

> Entries added automatically by the review-session skill.
> Each entry links to the full review report and improvement plan.

<!-- Session review batch: 2026-04-28 — 2 sessions -->

### [high] Add path resolution warning to memory-ingest SKILL.md

**Source:** Session review `2026-04-26_15-24-09` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

**Observation:** The `read`, `write`, `edit`, and `find` tools resolve relative paths from `C:` but `dagi-memory/` lives on `G:` — every dagi-memory tool call failed, forcing bash fallback.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-24-09.md`
- [ ] Implement
- [ ] Mark as done

### [high] Add same path resolution warning to memory-add SKILL.md

**Source:** Session review `2026-04-26_15-24-09` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

**Observation:** `memory-add` uses the same `dagi-memory/...` relative paths and will fail identically when used directly (not via `memory-ingest`).

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-24-09.md`
- [ ] Implement
- [ ] Mark as done

### [high] Fix redundant skill-load instruction in memory-ingest Step 6

**Source:** Session review `2026-04-26_15-24-09` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

**Observation:** Step 6 instructs the agent to call `skill("memory-add")` again even though the full skill content is already embedded in the tool result from Step 6 of `memory-ingest` — agent called the skill twice.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-24-09.md`
- [ ] Implement
- [ ] Mark as done

### [medium] Add bash-based archiving template to memory-ingest Step 5

**Source:** Session review `2026-04-26_15-24-09` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

**Observation:** Agent spent tool calls figuring out the right bash/PowerShell commands to archive files to `G:` drive — the skill should provide this template explicitly.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-24-09.md`
- [ ] Implement
- [ ] Mark as done

### [low] Add pre-flight path check to memory-ingest

**Source:** Session review `2026-04-26_15-24-09` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-24-09.md](.dagi/self-review/review_2026-04-26_15-24-09.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-24-09.md](.dagi/self-review/plan_2026-04-26_15-24-09.md)

**Observation:** Agent made 6+ tool calls discovering that `dagi-memory/` paths fail — a pre-flight check would set a path-mode flag on the first operation, avoiding wasted discovery.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-24-09.md`
- [ ] Implement
- [ ] Mark as done

### [high] Validate project root in system prompt against actual filesystem

**Source:** Session review `2026-04-26_15-20-10` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

**Observation:** System prompt contained `Project root: G:\My Drive\black_grimoire\dagi-memory\raw` — inside `raw/` itself, not the actual project root `C:\Users\alexr\Driverless_AGI`. This caused all tool paths to resolve incorrectly. This is a session config error, not an agent error.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-20-10.md`
- [ ] Implement
- [ ] Mark as done

### [high] Extend path guard to cover full dagi-memory tree on G:

**Source:** Session review `2026-04-26_15-20-10` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

**Observation:** Path guard allowed `G:\My Drive\black_grimoire\dagi-memory\raw` only, blocking `G:\My Drive\black_grimoire\dagi-memory\wiki` when the agent used an absolute path.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-20-10.md`
- [ ] Implement
- [ ] Mark as done

### [medium] Add bash-fallback guidance to memory-ingest for G: path operations

**Source:** Session review `2026-04-26_15-20-10` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

**Observation:** When `read`/`find`/`write`/`edit` failed on G: paths, the agent stopped instead of falling back to `bash`. The skill should instruct agents to always use `bash` for dagi-memory file I/O on G:.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-20-10.md`
- [ ] Implement
- [ ] Mark as done

### [low] Recommend `dir` not `ls` in memory skills for Windows paths

**Source:** Session review `2026-04-26_15-20-10` | **Generated:** 2026-04-28 | **Review:** [.dagi/self-review/review_2026-04-26_15-20-10.md](.dagi/self-review/review_2026-04-26_15-20-10.md) | **Plan:** [.dagi/self-review/plan_2026-04-26_15-20-10.md](.dagi/self-review/plan_2026-04-26_15-20-10.md)

**Observation:** `ls "G:\My Drive\black_grimoire\dagi-memory\wiki"` failed while `dir` in the same bash tool succeeded — inconsistent behavior on Windows G: paths.

- [ ] Review plan at `.dagi/self-review/plan_2026-04-26_15-20-10.md`
- [ ] Implement
- [ ] Mark as done

## Self-Improvement Queue

### [High] Run the self-improve skill to bootstrap the improvement loop

**Type:** workflow | **Generated:** 2026-04-22 | **Skill:** `skill("self-improve")`

**Root cause:** The `self-improve` skill and `parse_session_log` tool have been deployed but never run — 50+ session logs are waiting to be analyzed for improvement signals.

**Quick action:** Start a DAGI session and invoke `skill("self-improve")` — the skill reads the last 5 substantive sessions, identifies errors/friction/inefficiency, and writes plan files + TODO entries. (~5 min to invoke, ~10–20 min for DAGI to run)

- [ ] Invoke `skill("self-improve")` in a DAGI session
- [ ] Review the Observations Report at `.dagi/self-improve/observations_*.md`
- [ ] Review generated plan files at `.dagi/plans/improvement_*.md`
- [ ] Implement highest-priority improvement plans
- [ ] Re-run `skill("self-improve")` after implementation to close the loop
