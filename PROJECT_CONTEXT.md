# PROJECT_CONTEXT.md

> Last updated: 2026-06-04 (session 12) | [README](README.md) | [TODO](TODO.md)

---

## Project Description

Driverless AGI (dagi) is a self-hosted, OpenAI-compatible agentic coding assistant built entirely in Python. It takes a task from the user, runs a Plan→Act→Observe loop calling tools (read, write, edit, bash, grep, web search, etc.) until the task is complete, and surfaces results via a Rich interactive CLI or single-shot `main.py` entry point. See [README](README.md) for setup and usage.

## Objective / Problem Statement

Build a minimal but production-capable autonomous coding agent that can: work on arbitrary codebases, survive long tasks via context compaction, accumulate persistent knowledge via a wiki memory system, spawn specialist subagents for research/planning, and self-improve over time via the GNHF feedback loop.

Non-goals: cloud hosting, multi-user auth, UI beyond CLI/Rich.

## Architecture

```
tui.py / cli.py / main.py ← entry points (Textual TUI | Rich REPL | single-shot)
    │
    tui.py → tui/ package:
        tui/app.py           ← DagiApp (lifecycle, threading)
        tui/commands.py      ← SlashCommandsMixin (_handle_slash + _cmd_*)
        tui/callbacks.py     ← build_callbacks() free function
        tui/conversation.py  ← ConversationPane(RichLog)
        tui/sidebar.py       ← Sidebar(Widget) — top header, 3-column layout
        tui/prompt_input.py  ← PromptInput(TextArea)
        tui/utils.py         ← helpers + _Stats
    │
    └── AgentLoop (agent/loop.py)
            │
            ├── ToolRegistry (agent/registry.py)  ← dispatches tool calls
            ├── SessionTracker (agent/session.py)  ← logs all turns to JSONL
            ├── CompactTool (tools/compact.py)     ← Pi-style context compaction
            ├── SkillLoader (.dagi/skills/)         ← BM25/guidance docs
            └── AgentCallbacks                     ← rendering hooks (TUI/CLI)
```

**Config:** `config.yaml` → `agent/config_loader.py` → `AgentConfig` dataclass  
**Memory:** `dagi-memory/{raw,wiki,sources}/` + BM25 retrieval at session start  
**Subagents:** IPC-based terminal spawning (`agent/ipc.py` + `tools/_terminal_subagent.py`)  
**TUI rendering bridge:** `AgentCallbacks` fire on agent thread → `App.call_from_thread()` → Textual main loop → widget `refresh()`

## Process Flow

1. User calls `cli.py` (REPL) or `main.py` (one-shot) with a task string
2. `resolve_model_config()` reads `config.yaml`, resolves API key (direct or via env var), builds `AgentConfig`
3. `AgentLoop.__init__()` loads skills, builds `ToolRegistry`, constructs system prompt
4. `AgentLoop.run(task)` enters `while True` loop:
   - Checks `_pause_event` at top of each iteration — blocks if user pressed ESC (TUI only)
   - Calls the LLM with current `_messages`
   - If tool calls present → dispatch each tool, append results, loop again
   - If no tool calls → check response for termination flags:
     - `<<END_OF_RESPONSE>>` → strip flag, surface response, exit loop (wait for next user turn)
     - `<<TASK_END>>` → strip flag, surface response, call `on_done`, return (legacy alias)
     - Neither → inject continue prompt, loop again (up to `max_continuations`)
5. Context compaction triggers mid-loop if token count exceeds threshold
6. Session ends; `SessionTracker.finish()` writes summary to `.dagi/logs/`

## Key Files & Directories

| Path | Purpose |
|------|---------|
| `agent/loop.py` | Core agent loop, `AgentConfig`, `AgentCallbacks`, `TASK_END_FLAG`, `AWAIT_USER_FLAG`; pause/resume via `_pause_event` |
| `agent/config_loader.py` | Reads `config.yaml`; resolves `api_key` (direct or env var) and model catalog |
| `agent/tools.py` | Wires all tools into `ToolRegistry`; defines plan-mode and subagent registry variants |
| `agent/registry.py` | Tool dispatch; OpenAI function-schema generation |
| `agent/session.py` | Append-only JSONL session logging with token/cost tracking |
| `agent/ipc.py` | File-based IPC for terminal subagent communication |
| `tools/_terminal_subagent.py` | Spawns `CREATE_NEW_CONSOLE` terminal for subagents |
| `tools/compact.py` | Pi-style context compaction |
| `tools/ask_user.py` | Blocking user-input tool with optional timeout |
| `tui.py` | Thin launcher (~30 lines) — loads `.env`, imports `DagiApp` from `tui/`, defines typer entry point |
| `tui/app.py` | `DagiApp(SlashCommandsMixin, App[None])` — lifecycle only: compose, on_mount, dispatch, callbacks wiring, poll; ~180 lines |
| `tui/commands.py` | `SlashCommandsMixin` — `_handle_slash` + all `_cmd_*` methods + `_load_maps`; mixed into `DagiApp` via MRO |
| `tui/callbacks.py` | `build_callbacks(app, loop_ref) → AgentCallbacks` free function; uses `TYPE_CHECKING` guard to avoid circular import |
| `tui/conversation.py` | `ConversationPane(RichLog, wrap=True)` — scrollable Rich log widget |
| `tui/sidebar.py` | `Sidebar(Widget)` — fixed 6-line top header; 3-column Rich `Table`: left=emote+status+model, center=tokens+condensed-context, right=plan subtasks; 2 s plan-poll via `set_interval` in `DagiApp.on_mount` |
| `tui/prompt_input.py` | `PromptInput(TextArea)` + inner `Submitted` message |
| `tui/utils.py` | `_colour`, `_truncate`, `_resolve_option`, `_breakdown`, `_system_breakdown`, `_Stats`, `_TOOL_COLOURS`, `_SLASH_HELP` |
| `cli.py` | Rich REPL with threaded/sync modes, plan mode, slash commands |
| `config.yaml` | Model catalog, API config, context window settings |
| `.dagi/prompts/main/main_system.md` | Agent system prompt (tools, termination flags, plan mode trigger) |
| `tools/_plan_parser.py` | Utilities for parsing plan.md: `extract_global_sections`, `extract_subtask`, `parse_subtask_statuses` |
| `.dagi/agents.md` | Behavioral guidelines, Plan-Work-Review cycle instructions |
| `soul.md` | DAGI persona definition |
| `tests/test_continuation.py` | Unit tests for `<<TASK_END>>` and `<<WAIT_FOR_USER_RESPONSE>>` loop logic |
| `tests/test_config_loader.py` | Unit tests for direct `api_key` and `api_key_env` resolution |
| `requirements.txt` | Exact pip freeze of the `dagi` conda env (23 packages). **Does not match `pyproject.toml`** — see Notable Points. |
| `tools/emote.py` | `EmoteTool(BaseTool)` — agent calls `emote(emote)` to update sidebar face; fires `on_emote` callback |
| `.dagi/emotes/` | Five emote face files (`default`, `confused`, `happy`, `serious`, `funny`), one line each, plain text |

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

- **2026-05-30 Note**: `conda run -n dagi python -c "..."` with multi-line strings fails on Windows with `NotImplementedError` (newlines in args not supported). Write multi-line scripts to a temp file and run that instead.

- **2026-05-31 Change**: Renamed `<<AWAIT_USER_RESPONSE>>` → `<<END_OF_RESPONSE>>`.
  **Cause**: Models kept omitting the flag on conversational turns (greetings, etc.) because `AWAIT_USER_RESPONSE` reads as something said only after asking a question. The instruction was also too soft.
  **Fix**: Renamed the flag to `<<END_OF_RESPONSE>>` (semantically: "I am done with my turn") and rewrote the system-prompt instruction block with examples, explicit consequences, and a bold header. Constant renamed in `agent/loop.py`; tests were unaffected (they import the constant).

- **2026-05-31 Bug**: `_continuation_count` never reset between `run()` calls — PROJECT_CONTEXT.md incorrectly stated it reset per task; the code did not.
  **Cause**: `_continuation_count = 0` was set only in `__init__`, never at the start of `run()`. Accumulated across all tasks in a multi-turn session, silently eroding the continuation budget.
  **Fix**: Added `self._continuation_count = 0` at the top of `run()` (after `tracker.record_user`). Updated notable point to reflect corrected behavior.

- **2026-05-31 Bug**: Ghost-response cascade — DAGI silently ran 10 continuation loops and went idle after a null API response.
  **Cause**: DeepSeek v4 Flash via OpenRouter returned HTTP 200 with `content=None`, no tool calls, and `usage=None`. The loop appended `{"role":"assistant","content":null}` to `_messages`, causing every subsequent call to also return empty (malformed history triggered consistent null responses). The outer loop consumed all 10 `max_continuations` slots silently.
  **Fix**: Wrapped the API call in an inner ghost-response retry loop. Ghost = `content=None` AND `prompt_tokens==0`. On ghost: discard the response, do NOT append to `_messages`, retry up to `null_response_retries` (default 3, configurable in `config.yaml`). After all retries fail: surface "Error: model returned null N times" in TUI and return — user sees the error and can retry.

- **2026-05-31 Bug**: `plan_mode_exited` field was dead code — initialized `False` in `__init__`, never set `True` anywhere. The check at the end of the tool-call loop could never trigger.
  **Cause**: `_handle_exit_plan_mode` set `self.exited_plan_file` (a different field) rather than `self.plan_mode_exited`. Plan mode exit worked incidentally via the extra API round-trip.
  **Fix**: Removed the `plan_mode_exited` field and its unreachable check block. Accepted the natural flow (extra API call, agent reads plan context and starts implementing) as canonical.

- **2026-05-31 Feature**: ESC pause button added to TUI. `AgentLoop` now has `_pause_event: threading.Event` (set = running), checked at the top of each `while True` iteration. `pause()` clears the event; `inject_and_resume(message)` appends the user message to `_messages` then sets the event. TUI wires ESC to `action_pause()` and re-enables input; next typed message calls `inject_and_resume()` to unblock the loop. This is semantically equivalent to a user-initiated `ask_user` without a question.

- **2026-05-31 Refactor**: Unified skill invocation entry points. Previously, user slash commands (`/plan-work-review`, etc.) eagerly loaded full skill content into the user message via `_inject_skill_content()` (cli.py) / `_inject_skill()` (tui.py), bypassing the `skill` tool entirely. Now, slash commands produce a plain instruction (`"Invoke the \`skill-name\` skill."`) and the LLM calls `skill()` itself — identical to mid-task internal invocations. Removed both helper functions; added `_skill_invocation_message()` in cli.py as the single shared formatter, imported by tui.py.

## Notable Points

- **Flag ordering matters**: `AWAIT_USER_FLAG` (`<<END_OF_RESPONSE>>`) is checked *before* `TASK_END_FLAG` in the loop. If both appear in a response (accidental), `<<END_OF_RESPONSE>>` wins.
- **`api_key` vs `api_key_env`**: Direct `api_key` in config.yaml overrides env var lookup. Empty string `""` still falls through to env var — only a truthy value short-circuits. Security note: putting the key in yaml means it could be committed; prefer `api_key_env` for production use.
- **Multi-turn message history**: The CLI passes `loop._messages` as `conversation_msgs` into the next `_run_task()` call. `<<WAIT_FOR_USER_RESPONSE>>` works without any CLI changes because of this existing design.
- **`null_response_retries` is per-API-call** — the inner retry loop resets for every new LLM call. A ghost response during tool-call processing (e.g. after a large skill result) retries that specific call up to N times. This is independent of `max_continuations`.
- **`max_continuations` is per-`run()` call** — `_continuation_count` resets to 0 at the start of each `run()` call, so every task gets a fresh budget of `max_continuations` (default 10).
- **Subagents run in `CREATE_NEW_CONSOLE` terminal windows** on Windows; parent polls via `agent/ipc.py` file-based IPC. This is Windows-specific and will not work on Linux/macOS without changes.
- **`pyproject.toml` is incomplete**: `typer`, `rich`, and now `textual` are missing from declared deps. `pip install -e .` will fail on a clean environment for CLI/TUI use.
- **TUI thread safety**: `tui/app.py` runs `AgentLoop` on a daemon `threading.Thread`. All widget mutations from callbacks use `App.call_from_thread()`. The Sidebar widget uses instance attributes + `self.refresh()` — NOT Textual `reactive` — because Textual's reactive equality check on dicts can miss updates when the dict reference changes but content matches. Always use `dict(buckets)` (copy) when updating `_buckets` to force reference inequality.
- **Sidebar is now a top header, not a right column**: `Sidebar` is yielded first in `DagiApp.compose()` with CSS `height: 6; border-bottom: solid $panel`. The `Horizontal`/`Vertical` container wrappers (`#main-row`, `#conversation-col`) are gone — `ConversationPane` fills `height: 1fr` directly. `Sidebar.render()` returns a 3-column `rich.table.Table(expand=True, box=None)` with columns `ratio=2/4/3`: left=status col (`_status_col()`), center=tokens+context (`_tokens_context_col()`), right=plan (`_plan_col()`). The ASCII-art logo border is removed; the emote face is rendered inline in the left column. The center column condenses the 9-row context breakdown to 4 rows (sys / msgs-aggregated / reserve / total).
- **`SlashCommandsMixin` accesses `DagiApp` state freely**: `tui/commands.py` defines `SlashCommandsMixin` with no `__init__`. Its methods reference `self._active_loop`, `self._project_path`, `self.query_one(...)`, etc. — these resolve to `DagiApp` instance attributes at runtime via Python's MRO. Adding new instance attributes in the mixin requires no boilerplate; they must be initialized in `DagiApp.__init__` as usual.
- **`build_callbacks` circular import guard**: `tui/callbacks.py` imports `DagiApp` only inside `if TYPE_CHECKING:` to enable the type annotation `app: DagiApp`. At runtime no import of `tui/app.py` occurs from `callbacks.py`, breaking the cycle. The function accesses `app._stats`, `app._verbose`, `app.query_one(...)`, and `app.call_from_thread(...)` — all resolved dynamically.
- **TUI pause state**: ESC pauses at end-of-iteration (safe checkpoint). `_current_loop_ref: list` on `DagiApp` holds the running loop reference during execution (populated once `AgentLoop` is constructed in the worker thread). `action_pause()` guards against: idle (no live worker), pending `ask_user`, already paused. Resume requires explicit user input — no silent resume. The input branch in `on_prompt_input_submitted` detects paused state via `not loop._pause_event.is_set()` and routes to `inject_and_resume()` rather than spawning a new `AgentLoop`.
- **`PromptInput` replaces `Input`**: The TUI input widget is now `PromptInput(TextArea)` — a custom subclass that intercepts `enter` (submit, clears via `load_text("")`) and `shift+enter` (insert `"\n"` for multi-line composition). `TextArea` has no `.placeholder` attribute — the `_show_ask_user` and pending-ask branches no longer set a placeholder. The message handler is `on_prompt_input_submitted` (Textual routing: `on_{class_snake}_{message_snake}`).
- **Plan subtask status format**: `### Subtask N: [marker] name` in plan.md headings. Four valid markers: `[ ]` pending, `[~]` in-progress, `[x]` complete, `[!]` failed. The plan skeleton pre-populates `[ ]` at `enter_plan_mode` time. `parse_subtask_statuses()` in `tools/_plan_parser.py` parses these.
- **`[~]` orphan semantics**: The plan-work-review skill marks a subtask `[~]` before spawning a worker subagent. If the loop is interrupted mid-execution, `[~]` persists in plan.md indefinitely — no auto-reset. On session resume, the user or agent must inspect the subtask and decide whether to retry or mark complete. The TUI sidebar displays `[~]` in amber as "interrupted."
- **TUI plan panel poll**: `DagiApp` runs a 2 s `set_interval` poll (`_poll_plan`) that reads `loop.config.plan_file or loop.config.active_plan_file` on the Textual main thread. Both attributes are plain strings set once by the agent thread; Python's GIL makes the read safe without an explicit lock. The poll is a no-op when no loop is active.
- **TUI scrolling**: `RichLog.auto_scroll = True` by default. Textual pauses auto-scroll when the user scrolls up and resumes when they reach the bottom — this is built-in behaviour requiring no custom scroll handling.
- **Skill slash commands are LLM-delegated**: `/skill-name [args]` no longer pre-injects skill content. It produces `"Invoke the \`skill-name\` skill.\n\n{args}"` and sends it as the user message. The agent must call `skill("skill-name")` to load the content — same path as mid-task internal invocations. This means one extra LLM round-trip per slash command, but both code paths are now unified through `SkillTool`.
- **Sidebar emote system**: `Sidebar._status_col()` calls `_load_face()` on every `refresh()`, which reads `.dagi/emotes/{_emote}.md` (one-line plain text face expression). Falls back to `(◉ ᴗ ◉)` on `OSError`. The agent can switch emotes via `EmoteTool` → `AgentCallbacks.on_emote` → `App.call_from_thread(sidebar.update_emote, emote)`. Emote files are live-editable. Controlled by `emote_tool: true/false` in `config.yaml`. The decorative ASCII-art hair border (`╭≋≋╮`) was removed in the top-header redesign (2026-06-04); the face glyph itself is preserved inline in the left column.
- **ANSI `[blue]` renders as purple**: Rich's `[blue]` maps to ANSI color 4, which most modern terminal emulators render as violet/purple (inherited from CGA). Use hex colors (`[#4da6ff]`) or `[bright_blue]` (ANSI 12) for a perceptually blue result. This bit the sidebar logo — all color markup now uses hex.
- **Plan mode revision loop**: After writing a plan, the agent is instructed (via `main_system.md`) to call `show_plan` before `exit_plan_mode`. `show_plan` shows the plan, asks "Do you have any modifications?", and returns either "Plan approved — call `exit_plan_mode`" or "Modifications requested — revise and call `show_plan` again." The revision cycle repeats until approval. After `exit_plan_mode`, the agent outputs one implementation-start sentence and immediately begins tool calls without waiting for user confirmation.
- **Running indicator lifecycle**: `tui/app.py` has a 1-line `Static` widget (`#running-indicator`, `display: none` by default) between `#main-row` and `#prompt`. It is shown by `_show_running_indicator()` and hidden by `_hide_running_indicator()` (called from `_enable_input()`). The braille spinner (`_SPINNER` class var, 10 frames) is advanced by a `set_interval(0.1, _tick_spinner)` timer that no-ops when the bar is hidden. Show/hide call sites: `_dispatch_agent` (new task), `on_prompt_input_submitted` inject-and-resume branch (pause → resume), `on_prompt_input_submitted` ask_user answer branch (agent resumes after answer), `action_pause` (explicit hide without enabling input). Because `_enable_input` is always called via `call_from_thread`, `_hide_running_indicator` runs on the Textual main thread — safe.
- **`/hist` in TUI writes to hidden buffer**: `hist.run()` calls `console.print()` which writes to a Rich console that is not the Textual RichLog. Output appears in the terminal's hidden scroll buffer (behind Textual). This is a known limitation — `/hist` is functional but not displayed in the conversation pane.
- **There is a stale test directory** `C:UsersalexrDriverless_AGItests` (bad path) at the repo root — likely a Windows path mangling artifact, harmless but odd.
- **`requirements.txt` ≠ `pyproject.toml`**: `requirements.txt` is a `pip freeze` of the actual `dagi` conda env (23 packages). `pyproject.toml` declares ~10 additional runtime deps (`ddgs`, `crawl4ai`, `beautifulsoup4`, `nicegui`, `markdown`, `matplotlib`, `typer`, `rich`) that are **not** present in the env. The project cannot use web search, web fetch, or the interactive CLI on a clean install from `requirements.txt` alone.

## Terms & Language

- **TASK_END / `<<TASK_END>>`**: Legacy sentinel string for task completion; kept as alias for `<<END_OF_RESPONSE>>`.
- **END_OF_RESPONSE / `<<END_OF_RESPONSE>>`**: Primary sentinel the agent appends to every no-tool-call response to signal it has finished its turn. The harness strips it before displaying output and exits the run loop cleanly. Formerly `<<AWAIT_USER_RESPONSE>>`.
- **continuation**: The harness injecting a `"continue"` user message when the agent stops without a termination flag — recovery mechanism for mid-task stalls.
- **compaction**: Pi-style summarization of the middle of `_messages` when context exceeds the token budget, preserving system prompt and recent tail.
- **tier**: One of `default`, `worker`, `plan` — the three model slots in `config.yaml` (`default_model`, `worker_model`, `advanced_model`). The loop switches tiers via `switch_model` sentinel.
- **TUI**: The new Textual-based terminal UI (`tui.py`). "Full TUI" in this project means a fixed-canvas multi-pane layout (unlike `cli.py` which is a scrolling REPL). Requires `textual>=0.80.0`.
- **GNHF**: "Good and not horrible feedback" — dagi's self-improvement workflow. Committed milestones, iterative development, freeform notes log at `.dagi/gnhf/notes.md`.
- **BM25**: Sparse keyword ranking algorithm used for memory retrieval in `agent/memory_retriever.py`.
- **IPC**: File-based inter-process communication (`agent/ipc.py`) used between main agent and terminal subagents.
- **emote**: One of five named expressions (`default`, `confused`, `happy`, `serious`, `funny`) dagi-chan can display in the sidebar. Stored as plain-text `.md` files in `.dagi/emotes/`; switched by the agent via the `emote` tool.

---

## Claude's Insights

> Independent observations — not highlighted by the user.

### User Tendencies

- Invests in structural cleanup (refactoring tui.py → tui/ package) proactively once a module exceeds ~800 lines, rather than waiting for it to become unmanageable. Refactors are purely organizational — behaviour is preserved exactly.
- Ships incrementally and tests at each step; does not batch large refactors.
- Has a strong preference for maintaining backward compatibility — new features are additive, never breaking (`cli.py` kept alongside `tui.py`).
- Tends to work directly on `main` rather than feature branches.
- README and TODO are kept scrupulously up-to-date — the user treats them as living documents, not afterthoughts.
- Prefers explicit, non-magical configuration (env var pointers in yaml rather than magic env var names) but occasionally wants the escape hatch of inlining secrets directly.
- Engages deeply in design grilling before implementation — responds well to adversarial questioning about trade-offs and commits to concrete choices before coding begins. Does not want vague or open-ended design left to implementation time.
- Prefers pause semantics that preserve agent context (inject & resume) over simpler cancel-and-restart approaches, even at slightly higher implementation cost. Favours architectural correctness over convenience shortcuts.
- Will accept dead-code cleanup (removal) when shown the evidence; prefers the simpler behavior (accept the extra round-trip) over adding new flag logic when the outcome is equivalent.
- Prefers behavioral unification over performance micro-optimisation — accepted Option C (one extra LLM round-trip per slash command) because it eliminates divergent code paths, rather than synthetic-prefill options that would save the round-trip at the cost of message-history surgery.

### Project Shortcomings

- **`/hist` slash command in TUI is broken** — it writes to a `rich.Console` behind Textual's canvas. Needs reimplementing to write to `ConversationPane`.
- **`PromptInput` has no placeholder**: Textual's `TextArea` (which `PromptInput` subclasses) does not expose a `.placeholder` property. The "Your answer…" cue shown during `ask_user` prompts was silently dropped. A future improvement could overlay a `Label` or use the TUI's conversation pane to communicate prompt context.
- **No retry/backoff for transient API errors** — a single 429 or 5xx will abort the task. The TODO acknowledges this but it hasn't been implemented. Long tasks in production will hit rate limits.
- **Dependency split between `requirements.txt` and `pyproject.toml`** — `requirements.txt` (pip freeze of actual `dagi` conda env) has only 23 packages; `pyproject.toml` declares ~10 more (`ddgs`, `crawl4ai`, `beautifulsoup4`, `nicegui`, `markdown`, `matplotlib`, `typer`, `rich`). Neither file alone produces a working install. The `dagi` conda env is missing several declared runtime deps, meaning tools like `web_search`, `web_fetch`, and the Rich CLI may silently fail until those packages are installed.
- **BashTool is unsandboxed** — no command blacklist, no process group kill on timeout. An agent could run destructive bash commands. Path guard protects file tools but not bash.
- **Subagent architecture is Windows-only** (`CREATE_NEW_CONSOLE`). Cross-platform support would require a different IPC mechanism.
- **No integration tests** — all tests are unit tests with mocked LLM clients. There is no end-to-end test that runs a real agent loop against a live or recorded API response.
- **`temp_system_prompt.txt`, `temp_test.ipynb`, `plan.md` at root** are stale scratch files that should be cleaned up or archived.
- **`show_plan` tool was underused** — it already implemented the full plan revision loop (show → ask → revise → repeat), but `main_system.md` never instructed the agent to call it before `exit_plan_mode`. The tool was wired correctly; the orchestration was missing from the prompt.

- **2026-05-31 Bug**: Input pane invisible/disabled during `ask_user` tool invocation — user could see the question but could not type an answer.
  **Cause**: `_dispatch_agent()` disables the input pane (line 644 in `tui.py`) when the agent starts. `_show_ask_user()` displayed the question but never called `_enable_input()`, so the input remained disabled for the duration of the ask. The input was only re-enabled in the `finally` block when the agent finished entirely.
  **Fix**: Added `self._enable_input()` at the end of `_show_ask_user()`. Added `self.query_one("#prompt", PromptInput).disabled = True` in `on_prompt_input_submitted()` after the pending-ask branch resolves, so the input is disabled again while the agent continues running.

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

- **Fix `/hist` in TUI**: reimplement `_cmd_hist()` in `tui.py` to write session history directly to `ConversationPane` rather than calling `hist.run()` (which uses a bare `rich.Console`).
- **`ask_user` UX in TUI**: the input pane is now correctly re-enabled during `ask_user`. However, since `PromptInput` has no placeholder support, there is still no visual cue distinguishing a normal prompt from an `ask_user` question prompt. A small indicator (e.g., a highlighted label or border colour change on `#prompt`) would improve clarity during agent-initiated Q&A.
- **Parallel subagent dispatch**: the `[~]` in-progress state was introduced with parallel multi-agent future in mind. The IPC layer (`agent/ipc.py`) would need to support multiple concurrent polls; the plan panel would then show multiple subtasks as `[~]` simultaneously.
- **Pause during subagent execution**: current pause only stops the *parent* loop at its checkpoint. If a subagent is running (terminal subprocess), it continues unaffected. A future improvement could write an IPC `pause` sentinel to the subagent's channel.
- **Streaming responses**: the TUI sidebar's token counter currently only updates after each full API response. Streaming would enable per-token updates and reduce perceived latency. The `ConversationPane` could stream assistant text incrementally using `RichLog.write()` calls on each chunk.
- **Structured output / tool-call validation**: the agent currently relies on the model to produce valid JSON for tool arguments. A schema-level validator at the registry layer would catch malformed calls early.
- **Session replay / dry-run mode**: the JSONL session log has everything needed to replay a session deterministically — useful for debugging and regression testing.
- **Cross-platform subagent spawning**: replacing `CREATE_NEW_CONSOLE` with a platform-agnostic approach (e.g., tmux panes, named pipes, or asyncio subprocess) would open dagi to Linux/macOS users.
- **Emote animation**: `_status_col()` runs on every `refresh()`. Animating the face or label (e.g., cycling symbols on `_status == "running"`) requires only a branch on `self._status` inside `_status_col()` — no new state or callbacks needed. The ASCII hair glyphs (`≋`) were removed when the logo moved inline; add them back here if desired.
- **Emote tool in CLI mode**: `EmoteTool` is registered in the CLI path too (when `emote_tool: true`), but `on_emote=None` is passed since there is no sidebar. The tool still returns `"*emote*"` in text; the callback is silently a no-op. No separate CLI wiring required.
