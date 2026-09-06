# Architecture

Current components and their relationships.

> Last updated: 2026-09-05

## Entry Points

- **TUI** (`tui/app.py`): Textual-based terminal UI; primary interactive entry point.
- **PySide GUI** (`pyside_gui/`): Qt desktop UI; collapsible left sidebar with session
  history, file tree, file viewer, and plan views. Right sidebar for media/VAD.
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
- `_compaction`: context compaction (via `compact` subagent inheriting warm KV-cache)
- `_tool_dispatch`: dispatches tool calls through `ToolRegistry`

All modules are re-exported via `agent.loop`. White-box test patches must target the
owning module (e.g. `agent._compaction.run_subagent`).

## Session and State

- `SessionTracker` + `SessionLog` (`agent/session.py`, `agent/session_log.py`):
  persist conversation, usage, and subagent branch events.
  Format version 2 (with `branch/start` events for subagent context trees).
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
