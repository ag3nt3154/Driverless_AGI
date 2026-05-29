# PROJECT_CONTEXT.md

> Last updated: 2026-05-29 | [README](README.md) | [TODO](TODO.md)

---

## Project Description

Driverless AGI (dagi) is a self-hosted, OpenAI-compatible agentic coding assistant built entirely in Python. It takes a task from the user, runs a Plan→Act→Observe loop calling tools (read, write, edit, bash, grep, web search, etc.) until the task is complete, and surfaces results via a Rich interactive CLI or single-shot `main.py` entry point. See [README](README.md) for setup and usage.

## Objective / Problem Statement

Build a minimal but production-capable autonomous coding agent that can: work on arbitrary codebases, survive long tasks via context compaction, accumulate persistent knowledge via a wiki memory system, spawn specialist subagents for research/planning, and self-improve over time via the GNHF feedback loop.

Non-goals: cloud hosting, multi-user auth, UI beyond CLI/Rich.

## Architecture

```
cli.py / main.py          ← entry points (Rich REPL or single-shot)
    │
    └── AgentLoop (agent/loop.py)
            │
            ├── ToolRegistry (agent/registry.py)  ← dispatches tool calls
            ├── SessionTracker (agent/session.py)  ← logs all turns to JSONL
            ├── CompactTool (tools/compact.py)     ← Pi-style context compaction
            ├── SkillLoader (.dagi/skills/)         ← BM25/guidance docs
            └── AgentCallbacks                     ← CLI rendering hooks
```

**Config:** `config.yaml` → `agent/config_loader.py` → `AgentConfig` dataclass  
**Memory:** `dagi-memory/{raw,wiki,sources}/` + BM25 retrieval at session start  
**Subagents:** IPC-based terminal spawning (`agent/ipc.py` + `tools/_terminal_subagent.py`)

## Process Flow

1. User calls `cli.py` (REPL) or `main.py` (one-shot) with a task string
2. `resolve_model_config()` reads `config.yaml`, resolves API key (direct or via env var), builds `AgentConfig`
3. `AgentLoop.__init__()` loads skills, builds `ToolRegistry`, constructs system prompt
4. `AgentLoop.run(task)` enters `while True` loop:
   - Calls the LLM with current `_messages`
   - If tool calls present → dispatch each tool, append results, loop again
   - If no tool calls → check response for termination flags:
     - `<<WAIT_FOR_USER_RESPONSE>>` → strip flag, surface response, exit loop (wait for next user turn)
     - `<<TASK_END>>` → strip flag, surface response, call `on_done`, return
     - Neither → inject `"continue"` user message, loop again (up to `max_continuations`)
5. Context compaction triggers mid-loop if token count exceeds threshold
6. Session ends; `SessionTracker.finish()` writes summary to `.dagi/logs/`

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, `AgentConfig`, `AgentCallbacks`, `TASK_END_FLAG`, `WAIT_FOR_USER_FLAG` |
| `agent/config_loader.py` | Reads `config.yaml`; resolves `api_key` (direct or env var) and model catalog |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; defines plan-mode and subagent registry variants |
| `agent/registry.py` | Tool dispatch; OpenAI function-schema generation |
| `agent/session.py` | Append-only JSONL session logging with token/cost tracking |
| `agent/ipc.py` | File-based IPC for terminal subagent communication |
| `tools/_terminal_subagent.py` | Spawns `CREATE_NEW_CONSOLE` terminal for subagents |
| `tools/compact.py` | Pi-style context compaction |
| `tools/ask_user.py` | Blocking user-input tool with optional timeout |
| `cli.py` | Rich REPL with threaded/sync modes, plan mode, slash commands |
| `config.yaml` | Model catalog, API config, context window settings |
| `.dagi/prompts/main/main_system.md` | Agent system prompt (tools, termination flags, plan mode trigger) |
| `.dagi/agents.md` | Behavioral guidelines, Plan-Work-Review cycle instructions |
| `soul.md` | DAGI persona definition |
| `tests/test_continuation.py` | Unit tests for `<<TASK_END>>` and `<<WAIT_FOR_USER_RESPONSE>>` loop logic |
| `tests/test_config_loader.py` | Unit tests for direct `api_key` and `api_key_env` resolution |
| `requirements.txt` | Exact pip freeze of the `dagi` conda env (23 packages). **Does not match `pyproject.toml`** — see Notable Points. |

## Encountered Errors & Solutions

- **2026-05-29 Error**: `api_key` field in config.yaml silently ignored; dagi fell back to OpenAI env vars causing auth errors when `OPENAI_API_KEY` was unset.
  **Cause**: `_build_config_from_entry()` only read `api_key_env` (env var pointer), never a direct `api_key` literal.
  **Fix**: Added direct-key check first (`entry.get("api_key", "")`); falls back to `api_key_env` path only when empty. Warning block in `resolve_model_config()` similarly skips warning when direct key present.

- **2026-05-29 Error**: DAGI did not return `<<WAIT_FOR_USER_RESPONSE>>` on conversational/greeting responses, causing the harness to inject "continue" and confuse the model.
  **Cause**: System prompt listed `<<WAIT_FOR_USER_RESPONSE>>` examples only as "clarifying questions / options / intermediate results" — the model's pattern-matching excluded greetings and casual replies. The instruction was present but under-specified.
  **Fix**: Rewrote the flag section in `.dagi/prompts/main/main_system.md` to make the rule unconditional — every no-tool-call response must carry a flag; `<<WAIT_FOR_USER_RESPONSE>>` is now explicitly listed as the catch-all including greetings and conversational turns.

- **2026-05-29 Error**: Agent responses that ask a question or surface intermediate results immediately triggered auto-continue injection, preventing genuine conversational turns.
  **Cause**: Only two exit conditions existed — `<<TASK_END>>` (done) and no flag (inject "continue").
  **Fix**: Added `<<WAIT_FOR_USER_RESPONSE>>` as a third flag: exits the loop cleanly like `<<TASK_END>>` but semantically signals "waiting for user reply." CLI multi-turn history is preserved across `run()` calls, so the conversation continues naturally.

## Notable Points

- **Flag ordering matters**: `WAIT_FOR_USER_FLAG` is checked *before* `TASK_END_FLAG` in the loop. If both appear in a response (accidental), `WAIT_FOR_USER_RESPONSE` wins.
- **`api_key` vs `api_key_env`**: Direct `api_key` in config.yaml overrides env var lookup. Empty string `""` still falls through to env var — only a truthy value short-circuits. Security note: putting the key in yaml means it could be committed; prefer `api_key_env` for production use.
- **Multi-turn message history**: The CLI passes `loop._messages` as `conversation_msgs` into the next `_run_task()` call. `<<WAIT_FOR_USER_RESPONSE>>` works without any CLI changes because of this existing design.
- **`max_continuations` is per-`run()` call**, not per session — resets to 0 on each new task.
- **Subagents run in `CREATE_NEW_CONSOLE` terminal windows** on Windows; parent polls via `agent/ipc.py` file-based IPC. This is Windows-specific and will not work on Linux/macOS without changes.
- **`pyproject.toml` is incomplete**: `typer` and `rich` are missing from declared deps. `pip install -e .` will fail on a clean environment for CLI use.
- **There is a stale test directory** `C:UsersalexrDriverless_AGItests` (bad path) at the repo root — likely a Windows path mangling artifact, harmless but odd.
- **`requirements.txt` ≠ `pyproject.toml`**: `requirements.txt` is a `pip freeze` of the actual `dagi` conda env (23 packages). `pyproject.toml` declares ~10 additional runtime deps (`ddgs`, `crawl4ai`, `beautifulsoup4`, `nicegui`, `markdown`, `matplotlib`, `typer`, `rich`) that are **not** present in the env. The project cannot use web search, web fetch, or the interactive CLI on a clean install from `requirements.txt` alone.

## Terms & Language

- **TASK_END / `<<TASK_END>>`**: Sentinel string the agent includes in its final response to signal task completion to the harness.
- **WAIT_FOR_USER_RESPONSE / `<<WAIT_FOR_USER_RESPONSE>>`**: Sentinel the agent includes when it wants to surface a response and pause for user input without triggering auto-continue.
- **continuation**: The harness injecting a `"continue"` user message when the agent stops without a termination flag — recovery mechanism for mid-task stalls.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds the token budget, preserving system prompt and recent tail.
- **tier**: One of `default`, `worker`, `plan` — the three model slots in `config.yaml` (`default_model`, `worker_model`, `advanced_model`). The loop switches tiers via `switch_model` sentinel.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow. Committed milestones, iterative development, freeform notes log at `.dagi/gnhf/notes.md`.
- **BM25**: Sparse keyword ranking algorithm used for memory retrieval in `agent/memory_retriever.py`.
- **IPC**: File-based inter-process communication (`agent/ipc.py`) used between main agent and terminal subagents.

---

## Claude's Insights

> Independent observations — not highlighted by the user.

### User Tendencies

- Ships incrementally and tests at each step; does not batch large refactors.
- Has a strong preference for maintaining backward compatibility — new features are additive, never breaking.
- Tends to work directly on `main` rather than feature branches; all three fixes today were committed to main without a PR.
- README and TODO are kept scrupulously up-to-date — the user treats them as living documents, not afterthoughts.
- Prefers explicit, non-magical configuration (env var pointers in yaml rather than magic env var names) but occasionally wants the escape hatch of inlining secrets directly.

### Project Shortcomings

- **No retry/backoff for transient API errors** — a single 429 or 5xx will abort the task. The TODO acknowledges this but it hasn't been implemented. Long tasks in production will hit rate limits.
- **Dependency split between `requirements.txt` and `pyproject.toml`** — `requirements.txt` (pip freeze of actual `dagi` conda env) has only 23 packages; `pyproject.toml` declares ~10 more (`ddgs`, `crawl4ai`, `beautifulsoup4`, `nicegui`, `markdown`, `matplotlib`, `typer`, `rich`). Neither file alone produces a working install. The `dagi` conda env is missing several declared runtime deps, meaning tools like `web_search`, `web_fetch`, and the Rich CLI may silently fail until those packages are installed.
- **BashTool is unsandboxed** — no command blacklist, no process group kill on timeout. An agent could run destructive bash commands. Path guard protects file tools but not bash.
- **Subagent architecture is Windows-only** (`CREATE_NEW_CONSOLE`). Cross-platform support would require a different IPC mechanism.
- **No integration tests** — all tests are unit tests with mocked LLM clients. There is no end-to-end test that runs a real agent loop against a live or recorded API response.
- **`temp_system_prompt.txt`, `temp_test.ipynb`, `plan.md` at root** are stale scratch files that should be cleaned up or archived.

### Assumptions to Challenge

- **Single-user, single-session**: no locking on `config.yaml` or session logs; running two dagi instances simultaneously against the same project could corrupt state.
- **OpenAI-compatible API contract**: assumes the provider's `/chat/completions` response schema matches the OpenAI SDK's expectations exactly. Providers sometimes diverge (e.g., `reasoning_content` field is non-standard).
- **English-only tasks**: system prompt and skill docs are English-only; non-English tasks may produce degraded results depending on the underlying model.

### Dependencies & Risks

- **OpenRouter** is the primary API gateway for most catalog models. A rate limit, outage, or pricing change would affect all non-OpenAI models simultaneously.
- **`ddgs` (DuckDuckGo search)**: unofficial API wrapper, no SLA, can break on site changes. Already listed as `>=2.0` which suggests prior breakage.
- **`crawl4ai`**: heavy dependency (Playwright-based), version-pinned at `>=0.4`. Breaks are likely as the web changes.
- **Python 3.14** in the `dagi` conda env — this is a pre-release / bleeding-edge version. Some packages may not have wheels for 3.14 yet (observed: `pytest` was missing, `pyyaml`/`openai` had to be installed manually).

### Potential Areas of Exploration

- **Streaming responses**: currently using non-streaming API calls; streaming would enable real-time token display and reduce perceived latency for long responses.
- **Structured output / tool-call validation**: the agent currently relies on the model to produce valid JSON for tool arguments. A schema-level validator at the registry layer would catch malformed calls early.
- **Session replay / dry-run mode**: the JSONL session log has everything needed to replay a session deterministically — useful for debugging and regression testing.
- **Cross-platform subagent spawning**: replacing `CREATE_NEW_CONSOLE` with a platform-agnostic approach (e.g., tmux panes, named pipes, or asyncio subprocess) would open dagi to Linux/macOS users.
