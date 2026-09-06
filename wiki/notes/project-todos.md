# Project TODOs

Interim home for open and completed project tasks. Relocated from TODO.md 2026-09-05.
No roadmap redesign; preserving existing status vocabulary and organization.

> Last updated: 2026-09-05

## Open

- **Provider call has no timeout — worker can block for ~30 min** · `open` · found `2026-08-26` —
  `AgentLoop` builds `openai.OpenAI(api_key=…, base_url=…)` with no `timeout`, so a stalled
  provider response falls back to the SDK default (600s read, `max_retries=2`) before `run()`
  sees an error. Fix: config-backed `request_timeout` passed to the client.

- **`pyside_gui/app.py` file cap is stale** · `open` · found `2026-08-26` —
  `test_pyside_app_stays_under_file_cap` asserts ≤500 lines; the file has been 547+ on `main`
  since the left-sidebar work. Raise the cap or split the module.

## Completed (recent)

- **Plan mode removed — replaced with `/plan` skill + `create_plan` tool** · `done` · `2026-09-05`
- **Deliver workflow (Tasks 1–8)** · `done` · `2026-09-05`
- **String-Sentinel Protocol Refactor** · `done` · `2026-08-26`
- **TUI + GUI freeze — stale `ask_user` sink swallows the next message** · `done` · `2026-08-26`
- **VAD drift timer** · `done` · `2026-08-24`
- **PySide6 left sidebar dynamic resize + file viewer word-wrap** · `done` · `2026-08-24`
- **PySide GUI freeze after ask_user timeout** · `done` · `2026-08-23`
- **PySide6 left sidebar — collapsible rail + three modal views** · `done` · `2026-08-23`
- **Main/inherited `write_handoff` final-action restoration** · `done` · `2026-08-20`
- **Compact cache-prefix (Tasks 1–8)** · `done` · `2026-08-19`
- **Subagent-based context compaction (Tasks 1–7)** · `done` · `2026-08-18`
- **Session log tree — agent loop wiring (Tasks 1–5)** · `done` · `2026-08-17`
- **Session log tree + subagent context construction (Tasks 1–10)** · `done` · `2026-08-17`
- **Electron desktop GUI** · `done` · `2026-08-15` (archived)
- **`read_large_text` tool rebuilt** · `done` · `2026-08-15`
- **Dynamic context board + `update_task_status`** · `done` · `2026-08-10`
- **Subagent refactor (Tasks 1–10)** · `done` · `2026-08-04`
- **Session history — auto-named session files and `/hist` restore** · `done` · `2026-08-01`
- **Subagent handoff enforcement + parent-authored briefing/handoff_spec** · `done` · `2026-07-26`
- **Post-merge ponytail review cleanup** · `done` · `2026-07-26`
- **Restructured all 28 DAGI tools into subfolders; doc_converter service** · `done` · `2026-07-25`
- **Consolidated `.dagi/agents.md` behavioral guidelines into `AGENTS.md`** · `done` · `2026-07-24`
- **Double-click launcher (dagi_run.bat)** · `done` · `2026-07-24`
- **PDF + environment fixes (various)** · `done` · `2026-07-20` to `2026-07-22`
- **Added `environment.yml`** · `done` · `2026-07-21`
- **Telegram bot authorization** · `done` · `2026-07-18`
- **Hash-anchored read/edit/grep** · `reverted` · `2026-07-27`

[Notes](index.md) | [Project wiki](../index.md)
