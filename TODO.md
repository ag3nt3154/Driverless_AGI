# TODO

## Done

- [x] Auto compaction for long contexts — Pi-style compaction in `agent/loop.py` (`_compact_context`). Summarizes middle history, preserves system prompt + recent tail, carries forward prior summaries.

## In Progress

_(nothing active)_

## Backlog

### High Impact

#### 1. Project / Folder Scoping _(safety)_

Tools can currently read, write, and execute anywhere on disk. Add configurable path boundaries so the agent only operates within a designated project.

**Deliverables:**
- `allowed_paths` list per tool type in `config.yaml` (whitelist)
- `blocked_commands` list for `bash` (blacklist patterns like `rm -rf /`)
- Path validation in `BaseTool.run()` before dispatch — reject with clear error
- Default: current working directory if unset

**Files:** `agent/base_tool.py`, `agent/tools.py`, `config.yaml`

---

#### 2. Error Handling & Retries _(reliability)_

A single 429 or network timeout kills the entire run. Bash timeouts don't actually kill the child process.

**Deliverables:**
- Exponential backoff for transient API errors (429, timeout, 5xx) — initial 1s, max 60s, 3 attempts
- Fail-fast for permanent errors (auth 401, bad request 400)
- `on_error_retry(error, attempt, backoff_ms)` callback for UIs
- `BashTool`: kill process group on timeout via `os.killpg`
- `EditTool`: raise exception on not-found instead of returning error string
- Empty API key → fail immediately with actionable message

**Files:** `agent/loop.py`, `agent/tools.py`

---

#### 3. Persistent Memory System _(capability)_

The agent forgets everything between sessions. A memory system lets it accumulate knowledge about the user's environment, preferences, and past decisions.

**Deliverables:**
- Per-project JSON store at `.dagi/memory.json` — sections: `environment`, `preferences`, `decisions`
- New `memory` tool (read/write/search) registered alongside existing tools
- Auto-inject relevant memory into system prompt on session start
- Compact older entries when file exceeds threshold
- Agent can write to memory unprompted when it learns something useful

**Files:** new `agent/memory.py`, `agent/tools.py`, `agent/loop.py`

---

### Medium Impact

- [ ] Plan mode / ask mode — agent outlines steps and waits for confirmation before executing
- [ ] Dynamic generation of tool descriptions — tailor tool schemas per model or context
- [ ] Ability to work in projects — dedicated project folders with per-project config (depends on #1)
- [ ] Sample project to test dagi — example task + source files + expected output for validation
- [ ] Fix `pyproject.toml` — missing `typer`, `rich`, `streamlit`, `streamlit-autorefresh` from deps
