# Message board v1.1 + multi-agent spawning — Implementation Plan

**Goal:**
- Make the board easy to run.
- Make startup resilient: if the configured board is down, fall back to a local board, and let
  the user reconnect later.
- Make attachments viewable and saveable everywhere.
- Send fetched board images to the LLM.
- Let the user spawn agents from an Agents view in the left icon rail.

**Spec:** [spec.md](spec.md).

**Branch:** `task/board-multi-agent` from `main`.

## Global Constraints

- **Interpreter:** `C:\Users\alexr\anaconda3\envs\dagi\python.exe`.
- **Tests:**
  - non-GUI: `python -u -m pytest -q -p no:pytest-qt tests`
  - GUI: `python -u -m pytest -q pyside_gui/tests`
  - TEMP/TMP outside the repo.
- **Code limits:**
  - functions ≤ 100 lines, cyclomatic complexity ≤ 8, ≤ 5 positional parameters;
  - lines ≤ 100 characters, files ≤ 500 lines;
  - `app.py` is at 496 lines, so new window logic goes in new modules.
- **Untrusted text:** all untrusted text in Qt uses `Qt.PlainText`. The web viewer uses
  `textContent` only, and its CSP is unchanged.
- **Known failures:** the 3 `tests/test_workflow_plan_template.py` failures pre-date this task.

## Subtasks

### 1. Entry script and config form (spec §5.1, §5.2)
- **Files:**
  - `message_board.py` (new);
  - `services/message_board/__main__.py`: default subcommand, config defaults, token file;
  - `pyside_gui/board_runtime.py`: parse the string or mapping config;
  - `config.example.yaml`.
- **Tests:** `tests/message_board/test_entry.py`:
  - defaults come from the config;
  - flags override them;
  - token precedence;
  - a non-loopback bind without a token refuses to start.

### 2. Startup fallback (spec §5.3)
- **Files:**
  - `pyside_gui/board_runtime.py`: `start_board` retries once and spawns on `bind:port` with
    the token;
  - `agent/board_client.py`: token-file helper.
- **Tests:** the A2 cases in `tests/test_board_runtime*.py`.

### 3. Images to the LLM (spec §5.6)
- **Files:** `tools/board/_board.py` (`FetchAttachmentTool`), which reuses `load_image` and the
  limits from `tools/read`.
- **Tests:** an image returns `ATTACH_IMAGE`; a file is unchanged; a dispatch test covers the
  non-multimodal error.

### 4. Attachments in the GUI and the web viewer (spec §5.5)
- **Files:**
  - `pyside_gui/sidebars/board_widgets.py`: Open and Save as…;
  - `services/message_board/static/index.html`: image overlay and text preview.
- **Tests:**
  - pytest-qt: Save as… copies the bytes, with the dialog monkeypatched;
  - viewer harness: overlay, preview, sink grep.

### 5. Reconnect (spec §5.4)
- **Files:**
  - `pyside_gui/board_controller.py`: `switch(url, token)` and the central ping timer;
  - `pyside_gui/sidebars/message_board.py`: header row, badge, Connect…;
  - `index.html`: dim and disable while offline; catch up and un-dim on recovery.
- **Tests:**
  - pytest-qt: switching re-points the listener and session, and clears the view;
  - the ping shows "back";
  - viewer harness: the A3 outage scenario.

### 6. Window refactor to `AgentSession`, behaviour unchanged (spec §6.1, §8)
- **Files:**
  - `pyside_gui/agent_session.py` (new): per-agent state and per-bridge signal wiring;
  - `app.py`, `_dispatch.py` and `commands.py` read state through the active session;
  - main handle persistence.
- **Tests:**
  - the existing GUI suite passes unchanged, apart from moving attributes in tests that build
    stand-in windows;
  - new: the main handle is stable across two constructions.

### 7. Agents rail view and multi-session (spec §6.2, §6.3)
- **Files:**
  - `pyside_gui/sidebars/agents_view.py` (new);
  - `left_sidebar.py`: sixth rail view `agents`;
  - `right_sidebar.py`: follows the active agent;
  - conversation `QStackedWidget`;
  - spawn, activate, close; background `ask_user` notification.
- **Tests:** the A7 cases with pytest-qt and a fake `AgentLoop`.

### 8. Docs and wrap-up
- **Files:**
  - README: entry script, config form, fallback and firewall note, reconnect, attachments,
    Agents view;
  - TODO: remove done items and add Q1;
  - AGENTS.md header date.
- **Run:**
  - the full suite;
  - memory-add with decisions and gotchas.
- **Then:** the user runs the spec §7 manual checks.

## Progress (2026-10-09)

All 8 subtasks done on `task/board-multi-agent`; spec and plan approved by the user ("yes, go
ahead").

| # | Commit | Evidence |
|---|---|---|
| 1 | `fac00e9` | `tests/message_board/test_entry.py` (settings forms, flag overrides, token precedence, generated token, loopback ignores the file, `message_board.py serve --help`) |
| 2 | `23e2250` | `tests/test_board_runtime.py`: unreachable twice → spawn on `0.0.0.0:<port>` for refused/timeout/DNS × local/remote URL; retry success; auth failure; cancel during retry; stable main handle |
| 3 | `35d0f61` | `tests/test_board_tools.py`: image → `ATTACH_IMAGE` via `ReadTool.read_image`; unreadable image falls back to text; registry wiring |
| 4 | `1f8c73a` | pytest-qt Save as… bytes, cancel, failed download; viewer harness `attach` (overlay, preview, binary, >256 KB) and `outage` (dead → live, catch-up from last id, no duplicates) |
| 5 | `c4803ba` | `pyside_gui/tests/test_board_controller.py`: switch rebinds every session + listener + view, 401 asks for a token and keeps the old board, central probe, URL normalisation, fallback badge |
| 6 | `f0791f6` | Full GUI suite unchanged in behaviour (301 passed); headless smoke run of the real window |
| 7 | (this commit) | `pyside_gui/tests/test_agents.py` (A7, incl. a real-window background turn) and meme routing per agent |
| 8 | (this commit) | README, TODO, AGENTS.md |

Deviations from the plan:
- Main-handle persistence landed in subtask 2 (it lives in `register_runtime`).
- The web viewer's offline (dead/live) state landed in subtask 4, since it is the same file.
- The viewer test's 400-line cap became the repo's 500-line file cap (page is 467 lines).
- Closing an agent mid-turn pauses it; `AgentLoop` has no cancel, so the paused worker thread
  is kept (with its session) until exit. Logged in TODO.

## Next Action

The user runs the spec §7 manual checks, then decides on merging `task/board-multi-agent`.
