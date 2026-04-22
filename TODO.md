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
