# Architecture

Current components and their relationships.

> Last updated: 2026-09-19

## Entry Points

- **TUI** (`tui/app.py`): Textual-based terminal UI; primary interactive entry point.
- **PySide GUI** (`pyside_gui/`): Qt desktop UI; collapsible left sidebar with session
  history, file tree, file viewer, and plan views. Right sidebar for media/VAD.
  Prompt input has slash-command autocomplete (`SlashCompleterPopup` in
  `slash_completer.py`) — typing `/` shows a filtered popup of all available
  commands, skills, and workflows; Tab/Enter accepts, Up/Down navigates, Escape dismisses.
- **Telegram** (`tg/bot.py`): Async Telegram bot; requires `TELEGRAM_ALLOWED_CHAT_IDS`.
- **CLI** (`agent/cli_utils.py`): Shared helpers for TUI and future entry points.
- **Electron/dagi_gui**: Archived; not actively maintained.

## Core Agent Loop

`AgentLoop` (`agent/loop.py`) delegates to internal modules:
- `_loop_config`: configuration loading
- `_loop_helpers`: shared helpers
- `_system_prompt`: assembles stable instructions + `{tools_and_skills}` placeholder
- `_reload`: skill hot-reload logic
- `_model_switch`: model switching
- `_streaming`: provider streaming
- `_compaction`: context compaction (via `compact` subagent inheriting warm KV-cache);
  supports `summarize_all` mode for full-context compaction (no tail retention)
- `_tool_dispatch`: dispatches tool calls through `ToolRegistry`

- **Garbled loop recovery:** consecutive empty-content responses (threshold: 3) trigger
  `revise_last_step()` to strip degenerate turns, followed by full compaction
  (`compact(summarize_all=True)`). Process state transitions to `"compacting"` during
  the operation.

All modules are re-exported via `agent.loop`. White-box test patches must target the
owning module (e.g. `agent._compaction.run_subagent`).

## Session and State

- `SessionTracker` + `SessionLog` (`agent/session.py`, `agent/session_log.py`):
  persist conversation, usage, and subagent branch events.
  Format version 2 (with `branch/start` events for subagent context trees).
- `AgentLoop.log`/`SessionLog` is the session source of truth; `AgentLoop._messages` is a
  derived cache. `SessionEvent` records `seq`, `time`, `type`, `data`, `surface_op`,
  `source_seqs`, `ignorable`, and `branch`; turn/step coordinates live in applicable
  event data. The loop's append sink writes durable `.events.jsonl` records, while
  `SessionTracker` separately records activity, usage, and full tool results.
- The session surface projects user messages, assistant messages, tool results, and
  context/compaction entries into OpenAI chat dictionaries. Boundary and standalone
  tool/call bookkeeping are excluded. For main events, `surface_op` updates the surface;
  compaction shadows the replaced range with a user-role summary while retaining raw events
  and the recent tail.
- Compaction collects unique turn/step pairs from the active surface. Its tail boundary uses
  average `prompt_tokens` per step to derive a clamped keep count, rather than measured
  per-step tokens; the last middle step must have a main `STEP_END`. The parent records the
  replacement surface bounds, tail index, and generation, reconstructs the historical prefix
  cut at `STEP_END`, and sends a version-1 fork request with `context_spec`.
- The forked compaction child appends summary instructions to inherited messages, makes one
  nonstreaming retried call, and writes validated plain summary text to its handoff. It returns
  no replacement nodes or cache. The parent validates success, nonempty output, unchanged
  surface generation, and live edges before appending `CONTEXT_COMPACTION` with `source_seqs`.
  `Surface._replace` splices `_nodes` and `_cache` at inclusive edge positions; the cache
  summary is user-role and preserves the suffix.
- `_sync_messages` rebuilds `_messages` in place from the latest request/header system and
  derived surface messages. `_build_request_messages` materializes stored image references;
  each provider request sends the accumulated visible history plus separate tool schemas.
  Assistant tool calls are appended once, and `reasoning_content` is retained when present.
  Tool bookkeeping stores filtered context output in `TOOL_RESULT` and the full output in
  `SessionTracker`; the next iteration sends the accumulated history.
- PySide continuation reuses the prior log and tracker. When a supplied log exists, the
  constructor skips initial-message reseeding, preventing duplicate history; message-only
  resume seeds conversation events and emits a fresh header. Normal appends are durable, but `revise_last_step()` can
  remove in-memory events and malformed-tool-argument repair can mutate event payloads, so
  the event stream is not universally immutable.
- Active plan: `.dagi/session-state/<thread_id>/active-plan.json` sidecar.
  Set/checked via `set_active_plan`/`check_active_plan` tools.
- Session files: `*_logs.jsonl` in `.dagi/logs/`; old `session_*.jsonl` also supported.

## Tool Registry and Protocol

- `ToolRegistry` (`agent/registry.py`): dispatches tool calls; respects `config.yaml` tool allowlist.
- `ToolResult(output, side_effect, side_effect_data)` dataclass (`agent/protocol.py`) —
  replaces old string-sentinel control flow; `SideEffect` enum covers `END_TURN`,
  `ALL_TASKS_RESOLVED`, `SET_ACTIVE_PLAN`, `RELOAD_SKILLS`, `SWITCH_MODEL`.
- Tool filtering: `config.yaml`'s `tools:` list restricts main agent; mandatory
  `write_handoff` is always injected.
- Output filter (`tools/output_filter.py`): large tool results are cached to
  `.dagi/hash_cache/tool_output/` and replaced with a truncated preview; the
  "refine your search" instruction appears first so the agent sees it before the preview.
- Grep exclusions (`tools/grep/_grep.py`): `.dagi/`, `__pycache__/`, `.git/`, and other
  non-source directories plus binary extensions (`.pyc`, `.pyo`, etc.) are excluded from
  both ripgrep and Python-fallback search paths.

## Subagent System

- **Public API**: `tools/subagent_api.py` (`run_subagent`, `SubagentResult`). Never import
  private `_subagent_runner.py`.
- `SubagentResult` fields: `status`, `is_ok`, `handoff_text`, `handoff_path`,
  `session_log_path`, `pid`, `message`, `exit_code`, `output_tail`, `output_log_path`.
- Subagent types in `.dagi/subagents/*/main.py` discovered by `_discover_subagent_tools()`.
- Subagent output is tee'd to `<handoff_stem>.output.log` by the runner.
- Inherited children reuse the captured parent request prefix; finish via `write_handoff`.
- No subagent may spawn another agent (no nesting).

## Affect System

- `RandomEmoteLibrary` + `ExpressionController` (`agent/expression.py`): GIF emote rotation.
- GIF emotes play one full loop before rotating; new expressions deferred while playing.
- VAD drift: periodic `threading.Timer` (configurable `affect.drift_interval`).
- VAD vectors no longer part of the display path.

## Wiki and Memory

- Project wiki: `<project_root>/wiki/` — Git-tracked Markdown, queried/updated via
  `wiki_query`/`wiki_add` tools (delegated to subagents).
- Personal memory: `G:/My Drive/black_grimoire/dagi-memory` (explicit requests only).
- `/init` creates only missing placeholder files; never overwrites existing content.

## Key Directories

| Path | Purpose |
|------|---------|
| `agent/` | Core loop, tools, config, session |
| `tools/` | Tool implementations (subfolders per tool) |
| `.dagi/subagents/*/` | Subagent presets (main.py + prompt.md + config) |
| `.dagi/skills/*/` | Skills loaded by `skill` tool |
| `.dagi/prompts/main/` | Main agent system prompt |
| `.dagi/plans/` | Execution plan files |
| `.dagi/session-state/` | Active-plan sidecars |
| `.dagi/logs/` | Session JSONL logs |
| `wiki/` | Project knowledge wiki |
| `tui/` | Textual TUI |
| `pyside_gui/` | PySide6 desktop UI |

[Project wiki](index.md)
