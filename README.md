# Driverless AGI

Message board v1.1 and multi-agent spawning delivered 2026-10-09 on branch
`task/board-multi-agent` ([spec](wiki/tasks/2026-10-09_board-multi-agent/spec.md)): run the board
with `python message_board.py`, a local fallback board when the configured one is down, board
switching, attachment save/preview, board images sent to the model, an **Agents** rail view
for spawning agents, and @mentions that wake the mentioned agent — see [Message Board](#message-board) and [Agents](#agents-multi-agent).

Source research (2026-10-08): llama.cpp server prefix caching at upstream commit
`000bee54a544` is recorded in central memory as `llama-cpp-prefix-cache.md`.

Latest architecture/reliability review:
[_CODEX_CODE_REVIEW_2026-10-09.md](_CODEX_CODE_REVIEW_2026-10-09.md), with the
[iterative-work and self-improvement roadmap](_CODEX_SUGGESTIONS_2026-10-09.md).
The review contains 14 open findings. New code-mode probes reproduce parent-side execution
after script cancellation and loss of printed progress on timeout/kill. Scheduler ownership,
truthful outcomes, Telegram delivery, publication and plan contracts remain open.
Focused validation: 155 passed, 3 known plan-template failures. The roadmap recognizes
shipped code mode and proposes measured use and retained execution evidence.

A minimal, self-hosted coding agent. Give it a task — it plans, calls tools, reads results, and iterates until done. Ships with a Rich interactive CLI. Supports any OpenAI-compatible API, automatic context compaction for long sessions, extended reasoning, skills-based guidance, and full session logging with auto-named session files and history restore via `/hist`.

---

## How It Works

```
Plan → Act → Observe → Repeat
```

1. **Plan** — The model decides the next step based on the task and prior results
2. **Act** — It calls a tool (`read`, `write`, `edit`, `bash`, `grep`, …)
3. **Observe** — It reads the tool's output
4. **Repeat** — Until the task is complete or `max_iterations` is hit

When the conversation exceeds the model's context window, **context compaction** kicks in — the middle of the history is summarized by a dedicated `compact` subagent that inherits the parent's warm KV-cache prefix, then replaced with its summary, preserving the system prompt and recent messages. This lets the agent handle arbitrarily long tasks without crashing.

To end a turn the agent calls either **`write_handoff`** (final response) or **`ask_user`** (pause for user input). `write_handoff` takes the complete user-facing response as `content` and returns a typed `ToolResult(side_effect=SideEffect.END_TURN)` that the loop detects and uses to exit cleanly — no in-band string sentinels. `ask_user` pauses the turn and waits for the user's answer; after receiving it, the agent continues working or calls `write_handoff` to finish. If the agent produces a response with no tool calls and neither turn-ending tool, the harness treats it as accidentally truncated and injects a recovery prompt (`.dagi/prompts/main/continue.md`) to resume the loop. A safety valve (`max_continuations`, default 10, configurable in `config.yaml`) prevents runaway recovery loops. Additionally, **garbled loop recovery** detects when the model produces 3 consecutive empty-content responses (a common failure mode with smaller models; any tool-call step breaks the streak), revises those empty steps out of the session log, and triggers a full context compaction to give the model a fresh start.

**Garbled loop recovery:** When a model produces consecutive empty-content responses (common with smaller models), the harness automatically strips the empty steps (keeping the turn and the user's task), compacts the full context, and retries in the same turn — rather than burning through all continuation attempts. The stripped steps are also removed from the session's `.events.jsonl` file (rewritten atomically), so replaying it matches the live session.

**Memory:** knowledge lives in one central, grep-first memory wiki shared with Claude Code and
Codex (`memory_root`, default `G:\My Drive\black_grimoire`; entries under `wiki/projects/<p>/`,
`wiki/projects/<p>/todo/` and `wiki/knowledge/<topic>/`, each with one-line `title`,
`description`, `tags`, `updated` frontmatter). Each turn gets a short `[MEMORY]` pointer naming the
wiki and this project's folder. The main agent searches and files entries itself with the
`memory-query` and `memory-add` skills — no subagents — and `enter-workflow` requires a memory
search at task start and a memory write at task end. (`memory-refresh` is disabled pending a
redesign for this layout.)

### Image Input (PySide GUI)

Paste screenshots or local image files (PNG/JPEG) directly into the composer. Images are:
- Stored durably in a content-addressed asset store (`.dagi/attachments/`)
- Sent as data URLs to vision-capable models via the OpenAI Chat Completions API
- Preserved across session restarts, context compaction, and model switches
- Displayed as thumbnails in both the composer and conversation view

Configurable per-model in `.dagi/model_config/my-vision-model.yaml`:
```yaml
name: My Vision Model
model: provider/model-name
api_url: https://...
api_key_env: MY_API_KEY
supports_images: true
image_input:
  max_images_per_message: 4
  max_image_bytes: 8388608  # 8 MiB
  max_pixels: 24000000
  detail: auto  # "low", "high", or "auto"
```

The `read` tool can also open image files (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`):
the tool result is a short `[Image: name | WxH | mime]` line and the image itself follows in a
user message after the step's tool results (Chat Completions tool messages are text-only).
Formats other than PNG/JPEG, and images over `max_image_bytes` / `max_pixels`, are re-encoded
with Pillow first. This only happens when the active model tier has `supports_images: true` —
an unset or `false` value returns a `DAGI_CANNOT_PROCESS` error instead, because an image left
in history would break every later request to a text-only model.

See the "Image attachments" note under **PySide6 Desktop GUI** below for composer usage
details. Implementation plan and design rationale: `docs/image-input-implementation-plan.md`. Live
endpoint smoke testing against a real vision-capable model has not yet been performed —
automated coverage (asset store, wire payload, persistence, history labels, GUI routing) is
complete, but no live API call with actual credentials has verified end-to-end provider
compatibility.

---

## Setup

```bash
cd Driverless_AGI
cp config.example.yaml config.yaml   # edit with your model preferences
```

Create a `.env` file with your API keys:

```env
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...
```

Install dependencies. Use whichever environment manager you prefer:

**conda (fresh core environment):**
```bash
conda env create -f environment.yml   # run from repository root; creates the core `dagi` env
conda activate dagi
pip install -e .
```

**conda (existing env):**
```bash
conda activate dagi
pip install -e .
```

**venv:**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
```

The original pinned package list is split into installable requirements files.
Choose the core alone, or combine it with the groups you need:

```bash
pip install -r requirements-core.txt                           # core agent loop + CLI
pip install -r requirements-core.txt -r requirements-gui.txt    # add PySide GUI (+ board)
pip install -r requirements-core.txt -r requirements-board.txt  # message board service only
pip install -r requirements-core.txt -r requirements-tui.txt    # add terminal UI
pip install -r requirements-core.txt -r requirements-tools.txt  # add other tools
pip install -r requirements-dev.txt                            # test/dev utilities
pip install -r requirements-pdf.txt                            # PDF/Office/ML packages
pip install -r requirements-legacy.txt                         # old LangChain stack
pip install -r requirements.txt                                # entire original package set
```

Every original package pin is preserved in exactly one group. These files contain
package names and versions, not editable-install wrappers. The GUI file also includes
the TUI file because the GUI imports shared helpers through the TUI package.
Pip can still install transitive dependencies required by the selected packages;
the original snapshot was not a complete cross-platform lockfile.

`pyproject.toml` separately declares dagi's direct dependencies and optional extras
for editable installation. The original snapshot did not contain ddgs or crawl4ai;
use `pip install -e ".[web]"` for those web backends and run `crawl4ai-setup` for browser
setup. Telegram and benchmark extras remain available too. The `chunking` extra
(`pip install -e ".[chunking]"`, also in `requirements-tools.txt`) installs `chonkie` for
semantic chunking in the read tool; without it the stdlib chunker is used.

The `board` extra (`pip install -e ".[board]"`, same pins as `requirements-board.txt`:
fastapi, uvicorn, python-multipart) runs the [message board service](#message-board). The
`gui` extra (`pip install -e ".[gui]"`) requires `board`, and `requirements-gui.txt` includes
`requirements-board.txt`, so the GUI can always start its board.

The `read` extra (`pip install -e ".[read]"`, also in `requirements-tools.txt`) installs `markitdown` (with its docx/pdf/pptx/xlsx/xls extras) and Pillow, which the read tool uses for Office files, the PDF fallback and images. Without it those reads return a `DAGI_CANNOT_PROCESS` error. High-quality PDF conversion comes from the separate conversion service — see [Document Conversion](#document-conversion-service).

---

### Troubleshooting

**OpenAI credentials errors** — if you see authentication failures on startup, confirm your `.env` file exists at the repo root and contains the correct key, and that `python-dotenv` picked it up (it's a core dependency, installed automatically by `pip install -e .`).

**App appears frozen — running timer, `process=idle`** — a running indicator that keeps counting while the process channel reads `idle` and the prompt stays disabled means the UI is holding an answer sink for an `ask_user` question nobody is waiting on any more. Both the TUI and the PySide GUI now retire the pending question when its worker exits, and ignore a stale one at submit time, so the message starts a normal turn instead. If you still see it, check `.dagi/logs/pyside_worker.log` (GUI) and the session `*.events.jsonl` — a run whose last event is `plan/write` with no `turn/end` is a *different* stall: the worker is blocked inside the provider call, not on a stale question.

**Authorization / proxy errors** — if API requests are blocked by a corporate proxy or firewall, add the API base URL to the `no_proxy` environment variable so requests bypass the proxy:

```bash
# Windows (PowerShell)
$env:no_proxy = "openai.com,openrouter.ai,api.openai.com"

# macOS / Linux
export no_proxy="openai.com,openrouter.ai,api.openai.com"
```

**PDF/document reading errors** — the sections below apply to the **doc-converter service's own `doc_converter` conda env** (`services/doc_converter/environment.yml`), not the main `dagi` env — see [Document Conversion Service](#document-conversion-service) for setup/start commands. `scripts/verify_pdf_env.py` predates the service split and is not currently wired to the service's env; treat it as a reference for what to check manually (`python -c "import fitz, torch, onnxruntime, docling"` inside the `doc_converter` env) until it's updated.

**PDF reading / "DLL load failed" errors** — docling's dependencies (torch, onnxruntime, rapidocr) are imported lazily inside the service, so a broken install only surfaces the first time you read a PDF. On Windows, a DLL load failure from torch or onnxruntime almost always means the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) is missing — install it and retry.

**Local docling models** — if `models/docling_models/` (TableFormer + heron layout weights) is present, the service's PDF conversion loads them from disk instead of downloading from Hugging Face on every call. Falls back to the default HF download if the directory is missing. This directory is gitignored (machine-local) and each model needs its *full* file set (e.g. the tableformer model needs `tm_config.json` alongside its `.safetensors` weights, not just the weights) — a partial download fails with a `FileNotFoundError` deep inside docling's pipeline init, not at import time.

**Scanned-PDF OCR fails with `TesseractConfigError: ... Can't open hocr`** — on Windows/conda, this means `TESSDATA_PREFIX` points at a `tessdata` directory that has the language `.traineddata` files but not the `configs`/`tessconfigs` subfolders ocrmypdf needs (some conda-forge tesseract builds split these across `envs/<env>/share/tessdata` and `envs/<env>/Library/share/tessdata`). Fix by copying `Library/share/tessdata/{configs,tessconfigs}` into the directory `TESSDATA_PREFIX` points to, so it's self-contained.

**GUI: "Thinking…" stuck/flashing, handoff or `ask_user` question not shown** — check the conversation pane's markdown engine with `python -m pyside_gui.check_render` (verifies the vendored Vditor files against git, then loads the real page and renders a sample; exit 0 = OK). Page JavaScript errors are written to `.dagi/logs/pyside_worker.log` (logger `dagi.pyside.worker.page`). If rendering fails, messages now fall back to plain text instead of disappearing.

**Running tests / pytest-qt "DLL load failed while importing QtCore"** — `pyproject.toml` disables pytest-qt globally (`-p no:pytest-qt`) because on Windows it imports QtCore before PySide6's DLL directories are registered. `pyside_gui/tests/conftest.py` re-registers the plugin after the `pyside_gui` DLL bootstrap, so `qtbot`/`qapp` work there. Run everything with `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest tests pyside_gui/tests -q` (plain `pytest` only runs `tests/`). The same conftest flushes `deleteLater()`'d widgets around every GUI test (no top-level event loop runs, so they would otherwise outlive the test and keep their web views loading).

**Slow install tests** — tests marked `slow` (`pyproject.toml` marker) build wheels and clean
venvs, so they need the network and take minutes. They are opt-in: set `DAGI_RUN_SLOW=1` to
run them (e.g. the message board packaging tests in `tests/message_board/test_viewer.py`).

**GPU/CUDA** — PDF conversion always runs on CPU. `services/doc_converter/converter/pdf.py` sets `CUDA_VISIBLE_DEVICES=""` and passes `AcceleratorOptions(device=AcceleratorDevice.CPU)` to docling explicitly, so no CUDA device is ever touched by docling or tesseract/ocrmypdf, regardless of what's installed on the host.

---

## Usage

### Single-Shot CLI (`main.py`)

Runs one task and exits. Uses argparse. Stdout is reconfigured to UTF-8 (`errors="replace"`)
at startup, so results with non-cp1252 characters (e.g. `→`) print on a Windows console or pipe.

```bash
python main.py "Fix the off-by-one error in processor.py"
python main.py --model gpt-4o-openai "your task"
echo "Add type hints to agent/" | python main.py
```

| Flag | Description |
|------|-------------|
| `--model` | Model ID from the model catalog |
| `--verbose` | Verbose logging |
| `--project` | Path to a project directory to scope file access |

### Interactive TUI (`tui.py`) — recommended

Full Textual TUI with a fixed 6-line top header (status/emote, tokens+context, plan) and a full-width conversation area below. Conversation preserves the Rich panel style, wraps long lines, and scrolls freely while the agent is running.

While a response is being generated, assistant text and reasoning stream live into a preview area above the input box (governed by the `stream` config key — see [Configuration](#configuration)); once the turn completes, the preview disappears and the finished message is written into the conversation pane exactly as before.

```bash
conda run --no-capture-output -n dagi python tui.py
conda run --no-capture-output -n dagi python tui.py --project /path/to/project
conda run --no-capture-output -n dagi python tui.py -m deepseek-v4-pro-openrouter -v
```

| Flag | Description |
|------|-------------|
| `--model` / `-m` | Model ID from the model catalog |
| `--verbose` / `-v` | Show full tool input/output |
| `--project` / `-p` | Project directory |

**Keyboard shortcuts:**
- `Enter` — submit the input box contents as a task (single or multi-line)
- `Shift+Enter` / `Ctrl+N` / `Ctrl+Enter` — insert a newline in the input box for multi-line messages (`Ctrl+N` and `Ctrl+Enter` are reliable alternatives on Windows Terminal, which sends identical bytes for `Shift+Enter` and `Enter`)
- `Ctrl+O` — toggle compose mode: hides the conversation pane and expands the input box to fill the screen, giving a distraction-free writing area for long multi-line messages. Press `Ctrl+O` again to restore normal layout, or just press `Enter` to submit (auto-collapses on submit).
- `Esc` — interrupt the running agent at once (`AgentLoop.interrupt()`, see [Pausing and Resuming](#pausing-and-resuming)): a running `bash` command or subagent is force-killed, a streamed model reply is cut off where it is, and the remaining tool calls of the current response are cancelled. Status changes to `⏸ Paused`. Type any message and press Enter to inject it into the agent's context and resume. ESC has no effect when idle or during an `ask_user` prompt.
- `Ctrl-C` — quit the TUI entirely

**Header panels (left → center → right):**
- **Status** (left) — emote face (named emotes from `.dagi/emotes/` or custom text/kaomoji) · `● Running` / `⏸ Paused` / `○ Idle` · active model name
- **Tokens + Context** (center) — cumulative `in / think / out / cost`; condensed context breakdown (sys / msgs / reserve / total) with colour warnings at 80%/95% usage
- **Plan** (right) — subtask list polled every 2 s; shown only when a plan is active. Icons: `[ ]` pending · `[~]` in-progress (amber) · `[x]` complete (green) · `[!]` failed (red)

**Slash commands:** `/help`, `/exit`, `/clear`, `/wd`, `/compact`, `/model <id>`, `/write-plan`, `/tools`, `/skills`, `/workflows`, `/hist`, `/init`, `/revise-history [n]`

Exit with `/exit`, `exit`, `quit`, or `Ctrl-C`. Conversation history carries across turns.

### PySide6 Desktop GUI (`pyside_gui/`)

A native Qt 6 desktop app with a slate-indigo dark theme and a Material 3 light theme (**View → Theme**). Functionally equivalent to the TUI — full streaming conversation (rendered with Vditor in a QWebEngineView), right sidebar with token stats and plan tracker, left sidebar with session history/file tree/plan/message board/agents, overlay dialogs, and the full slash-command set. The **message board** tab in the left sidebar shows the shared board service's posts live, newest first, with a composer for posting as yourself — see [Message Board](#message-board).

```bash
# Launch (Windows/Linux/macOS — requires conda dagi env):
conda run --no-capture-output -n dagi python -m pyside_gui
conda run --no-capture-output -n dagi python -m pyside_gui --model <id> --project /path/to/project
```

| Flag | Description |
|------|-------------|
| `--model` / `-m` | Model ID from the model catalog |
| `--verbose` / `-v` | Show full tool input/output |
| `--project` / `-p` | Project directory (defaults to `cwd`) |

**Desktop pet:** A floating always-on-top window that displays VAD expression emotes (GIF animations) as a desktop pet. Hidden by default — toggle with `/show-pet`. The pet is draggable, defaults to the bottom-right corner of the screen, and stays on top of all other windows. The right sidebar's expression widget shows only process-state emotes (idle, thinking, tool:bash, etc.).

**Pet notepad:** a pinote-style WYSIWYG markdown scratch pad attached below the desktop pet. Right-click the pet → **Open notepad** / **Close notepad** / **Save notepad as…** (left-click stays drag-only; the header ✕ also collapses; the header strip is a drag handle and the corner grip resizes). The pet always reappears collapsed after `/show-pet`. Editing uses [Vditor](https://github.com/Vanessa219/vditor) in instant-rendering mode (no toolbar — type markdown, `Ctrl+B/I/K`, `Ctrl+Z/Y`; in plain paragraphs `Enter` inserts a single line break and `Shift+Enter` starts a new paragraph, while lists, headings and code blocks keep normal `Enter`), KaTeX math (`$…$` inline, `$$…$$` blocks), highlight.js code blocks, mermaid diagrams (forced to `securityLevel: "strict"`), and the shared neutral theme tokens; `Ctrl+click` opens links in the system browser. The note is **global** and auto-saved (1 s debounce, plus on collapse/hide/quit) to `.dagi/notepad/notepad.md` (git-ignored); `Ctrl+S` / **Save notepad as…** writes a copy anywhere (dialog starts in the project dir). External edits to the file reload automatically when there are no unsaved changes; otherwise local edits win and the disk version is backed up to `.dagi/notepad/conflict-<timestamp>.md`. `.dagi/notepad/state.json` remembers the notepad size. The editor web view is created lazily on first open. Code: `pyside_gui/desktop_pet.py`, `notepad_panel.py`, `notepad_editor.py`, `notepad_controller.py`, `agent/notepad_store.py`, `pyside_gui/resources/notepad/`.

Vditor 3.11.3 is vendored (trimmed to ~9.4 MB: core, lute, KaTeX woff2 fonts, en_US, ant icons, highlight.js, mermaid) under `pyside_gui/resources/vditor/` (shared by the notepad and the conversation pane) because its built bundle is published only to npm — no Node is needed at install or run time. To bump it, change `VDITOR_VERSION` in `scripts/vendor_vditor.py` and run `conda run -n dagi python scripts/vendor_vditor.py` (downloads the npm tarball, verifies sha512, re-extracts).

**Keyboard shortcuts:** `Enter` submit · `Shift+Enter`/`Ctrl+N` newline · `Ctrl+O` compose mode · `Esc` interrupt · `Ctrl+Q` quit

**Global Esc** (`pyside_gui/esc_stop.py`): an application-wide event filter catches `Esc` before any widget, so it interrupts the agent from anywhere — including the conversation and file-viewer web views (which otherwise swallow keys) and the desktop pet/notepad window. Whatever is open gets `Esc` first: menus and other Qt popups, modal dialogs, and widgets marked with `claim_escape()` (slash completer, copy picker). When the agent is idle, paused or waiting on an `ask_user` answer, `Esc` passes through (idle `Esc` still collapses the left sidebar). On interrupt the streaming bubble freezes where it is (late deltas are dropped) and an "Interrupted — type a message to continue" line appears.

**Image attachments (image input, all 6 stages complete):** paste an image (clipboard pixels or local `.png`/`.jpg`/`.jpeg` file paths) into the composer, or pick files with its `+` button, to attach it — a thumbnail strip appears inside the composer card with a remove (✕) badge per image. Limits mirror `AgentConfig` defaults (max 4 images/message, 8 MiB/image, 24M px/image); exceeding one shows an inline error and leaves the draft untouched. Enter submits text and/or attachments together as a `UserSubmission`; the conversation bubble now renders the sent images as thumbnails (up to 200x150, rounded corners, wrapping flex row) below the message text via `ConversationView.append_user_message_with_images()` / `conversation.js`'s `appendUserMessageWithImages()`, resolving each attachment's file path from the `ImageAssetStore` and loading it as a `file://` URL — falling back to the old `"text [N images]"` text bubble if path resolution fails. Pending-ask answers and slash commands are text-only and reject a submission that carries images, restoring the draft instead of discarding it.

**Slash commands:** same set as TUI — `/help`, `/clear`, `/model`, `/compact`, `/tools`, `/skills`, `/workflows`, `/hist`, `/init`, `/copy`, `/exit`, `/show-pet`, `/revise-history [n]` (removes the last `n` steps, default 1, after a `QMessageBox.question` confirm — see `SlashCommandHandler._cmd_revise_history` in `pyside_gui/commands.py`). `SlashCommandHandler.completions()` exposes all valid command names + descriptions for autocomplete. `SlashCompleterPopup` (`pyside_gui/slash_completer.py`) is a `QListWidget`-based filtered popup styled from the theme tokens — set_items, apply_filter, move_selection, selected_command, visible_count; `_resize_to_content` correctly hides the popup when no items match and re-shows it when matches return. `PromptInput` now hosts a `SlashCompleterPopup` instance: `set_completions()` loads the item list, `_on_text_changed` (connected to `_editor.textChanged`) detects a leading `/` with no space and calls `apply_filter`, and `_accept_completion()` replaces the editor text with the selected command + a trailing space. `_Editor.keyPressEvent` intercepts Tab/Enter/Escape/Up/Down when the popup is visible — Tab and plain-Enter accept the selected completion, Escape hides the popup, Up/Down navigate the list; Tab is silently swallowed when the popup is hidden. App-level wiring is complete: `_build_commands()` calls `prompt.set_completions()` after `load_maps()`, and `SlashCommandHandler` fires an `_on_completions_changed` callback at the end of every `load_maps()` call so completions automatically refresh when `/wd` changes the working directory.

> **Windows note:** PySide6 DLL loading is handled automatically by `pyside_gui/__init__.py`.

**Look and layout (OpenGhost-inspired, UI pass 1):**
- **One token table:** `pyside_gui/theme.py` holds every colour and font. The palette uses one hue (240°, ~20% saturation) for every surface, told apart by lightness only: sidebars darkest (`app_bg`), the chat pane lighter (`chat_bg`) and the composer lifted (`composer_bg`). Text is one cool off-white at 0.85/0.55/0.25/0.10 opacity. Colour is kept for meaning: tool titles sky, thinking lavender, right-sidebar token values sand and context values mint, plus danger/success/warn/link for status. The accent is indigo blue (`#5651b8`: send button, selection). Qt scrollbars use the shared `theme.SCROLLBAR_QSS`.
  - Qt stylesheets use `@token` placeholders through `theme.qss()`, which raises `KeyError` on a typo.
  - The web pages (conversation, notepad) get the same values as CSS custom properties spliced into their HTML's `/*@THEME@*/` slot (`theme.with_theme()`).
  - `theme.qcolor()` / `theme.solid()` cover `QColor` and Qt rich text.
  - `pyside_gui/icons.py` draws the monochrome line icons (rail, header, composer) from inline SVG.
- **Light theme (Material 3):** `theme.LIGHT` fills the same token names with Google's M3 roles: `#f0f4f9` surface-container sidebars and composer around a `#ffffff` chat surface, on-surface `#1f1f1f` text at 0.92/0.70/0.42/0.12, primary `#0b57d0` (send button, links), secondary-container `#d3e3fd` for selected items, `#e9eef6` user bubbles, tone-40 status colours (every text token clears WCAG 4.5:1 on white — asserted in `test_theme_and_labels.py`), and Google Sans / Roboto fonts where installed (Segoe UI otherwise). Code blocks switch to highlight.js `github` and the notepad to Vditor's `classic`/`light` themes, driven by the `--color-scheme` / `--hljs-style` tokens.
  - Pick **View → Theme → Dark / Light / System** (System follows Windows' app theme). The choice is saved to `.dagi/gui_settings.json` (git-ignored); `DAGI_THEME=light|dark|system` overrides it for one launch.
  - Widget modules build their stylesheets at import, so a switch applies after a restart: the menu offers **Restart now** (relaunches with the same arguments) unless an agent run is in flight. `theme.use()` must run before any widget module is imported; `theme.apply_to_app()` matches native dialogs and tooltips.
  - The palette is adapted from [OpenGhost](https://github.com/ANDRETRIPOL/OpenGhost), whose visual design is licensed for non-commercial use only.
- **Conversation pane** (`resources/conversation.{html,css,js}`, `conversation.py`): Python sends **raw markdown**, and the page renders it with Lute plus Vditor's KaTeX, highlight.js and copy-button renderers.
  - Math: `$…$`, `$$…$$`, `\(…\)` and `\[…\]` all render.
  - GitHub callouts (`> [!NOTE]`, `[!TIP]`, `[!WARNING]`, `[!CAUTION]`) render.
  - HTML written by the model stays literal text: `prepareMarkdown()` escapes `<` outside code, math and autolinks, and Lute's sanitizer is on as well.
  - A streamed answer is re-rendered about every 120 ms.
  - ```` ```mermaid ```` fences are drawn as diagrams (flowchart, sequence, class, state, ER, gantt, pie, …) by the vendored mermaid 11, loaded on first use. The model is asked for them by the **Visualize** guideline in `.dagi/prompts/main/main_system.md` (shared by every frontend; the TUI shows the fence as code).
    - They are coloured from the theme tokens (`theme: 'base'` + `themeVariables`); pie slices and other series cycle the role colours.
    - They are drawn with `securityLevel: "strict"`, so `click` callbacks and HTML labels in model-written diagrams stay inert.
    - Each card has a hover toolbar: **Code** toggles to the source, **Copy** copies it. Diagrams keep their natural size and scroll sideways when wider than the column.
    - While streaming, an unclosed mermaid fence shows "Drawing diagram…" and is drawn once its closing fence arrives. Drawings are cached by source, so the 120 ms re-renders and the final render reuse them.
    - Invalid syntax falls back to the source plus one dim "Couldn't draw this diagram: …" line.
  - Layout: a centred 760px reading column (14px / 1.6); user messages are right-aligned bubbles and assistant text sits on the background with no card.
  - Tool calls are one quiet line: an icon, a label derived by `pyside_gui/tool_labels.py` ("Read agent/loop.py", "Ran pytest -q", `Searched "foo" in tools/`) and a ✓/✕ status. Click a line to expand its output and its arguments, shown as one labelled field per argument (strings keep their real line breaks, other values are pretty-printed JSON). `--verbose` expands them by default.
  - Reasoning streams as a live tail, then collapses to "Thought for Ns".
  - User messages: a ```` ```pasted ```` fence renders as a collapsed **paste card** (icon, "Pasted text · N lines", the first line) that expands on click — also for restored sessions, since detection is from the text. Bubbles taller than ~320px are capped with a fade and a **Show more** toggle; opening a paste card lifts the cap.
  - The empty chat shows the pet's idle emote, the model and the project path until the first message.
  - Auto-scroll: the pane follows new content while you are within 48px of the bottom. Only a
    real scroll turns following off, so the composer growing does not. Sending a message
    always jumps to the bottom; the right sidebar's **Scroll to bottom** button does the same.
  - Clicked links open in the system browser.
  - Calls made before the page finishes loading are queued and replayed.
- **Composer** (`prompt_input.py`): a rounded card holding:
  - image thumbnails;
  - a text field that grows from one line to 240px (`Ctrl+O` compose mode makes it tall);
  - a `+` button that opens a file dialog for PNG/JPEG;
  - **long-paste tokens** (`paste_cards.py`): pasting 15+ lines or 1,500+ characters inserts an inline, link-coloured token like `[Pasted text #1 · 412 lines]` at the cursor instead of the text, so your own words stay readable around it. Click the token to expand it back into text; Backspace after / Delete before it removes it whole; `Ctrl+Shift+V` always pastes inline. On send each token becomes its text inside a ```` ```pasted ```` fence on its own lines (the fence is longer than any backtick run in the paste), so the model sees exactly where the paste starts and ends;
  - a white round send button. While the agent runs the composer stays live: the button is ■ Stop (same as `Esc`) when the field is empty and Send when there is something to send.
- **Typing while the agent runs** (`steer_queue.py`, `AgentLoop.steer`): a message sent mid-run shows as a dim **Queued** bubble pinned below the live turn and is handed to `loop.steer()`, which logs it at the loop's next checkpoint — after the current tool calls, before the next model call — without pausing. When `on_user_injected` confirms it, the bubble joins the timeline at the point the model actually saw it. The ✕ on a queued bubble withdraws it before delivery (over a QWebChannel bridge, `window._dagi`). Messages the turn never reached (it ended first, or the loop was still starting) are sent together as the next turn when the worker finishes. Slash commands are refused mid-run (wait or press `Esc`); an `ask_user` question still takes the next message as its answer; after `Esc`, queued messages are delivered before your resume message.
- **Chrome:**
  - A slim header over the conversation has buttons to hide or show the whole left and right sidebars (`pyside_gui/header.py`).
  - Next to the left toggle, a folder button (`📁 <folder> ▾`) works like VS Code's *Open Folder*: its menu has **Open Folder…** (native picker), the 5 most recent folders (current one ticked, missing ones greyed out) and **Clear recent**. Picks run through `/wd`, so the button and the typed command share the same checks — switching is refused while the agent runs (press `Esc` first). Recents are saved to `.dagi/recent_folders.json` (git-ignored) on every successful `/wd` and at startup (`pyside_gui/recent_folders.py`). The centred header title shows the model.
  - The right sidebar has a compact pet emote box (150×130), a status pill, the model name as a centred button with a `▾` chevron (click it to pick another model from the catalog — a menu that switches through `/model`; plain text when no catalog is available) and dim `cwd`/`app`/`mem` rows (full path on hover). Its token and context sections use dim labels with right-aligned coloured values, and context has a usage bar with per-bucket %.
  - Session history rows show the title with a dim `time · model` line.
  - The left rail uses checkable icon buttons. The message board and agents panels open as wide as the right sidebar; other left views split the space with the chat. Either can be dragged.
  - Splitters are 1px.
- Design notes, decisions and the mockup: `docs/2026-09-30_openghost-ui-review.md`, `docs/mockups/dagi-ui-mockup.html`.

#### Agents (multi-agent)

The sixth left-rail icon opens **Agents**. Type a slug (1–32 of `a-z`, `0-9`, `-`; `main` and
`user` are reserved) and **Spawn**: the new agent gets the handle `<slug>_<uuid8>`, starts from the
main agent's model and folder, joins the board the GUI is connected to (so it has `read_board`,
`post_board` and `fetch_attachment`), and opens in the main chat. Run `/wd <folder>` there to
choose its folder, then send its first prompt. Spawning is user-only; agents never spawn agents.

- Every agent is an in-process `AgentSession` (`pyside_gui/agent_session.py`) with its own
  conversation, slash commands, worker thread, token stats and board identity. Click a row to
  open that agent; the prompt, `Esc`, slash commands, header title, right sidebar and file tree
  follow the open agent. Hidden agents keep running and their output keeps streaming into their
  own conversation, so switching back shows everything.
- Each row shows a status dot (idle, running, paused, waiting for you). A hidden agent's
  `ask_user` question or finished turn raises a desktop notification instead of taking focus.
- **Close agent** stops a running turn and removes a spawned agent (the main agent stays). An
  agent waiting on a question must be answered first. Closed agents are not restored; their
  conversations are in the session logs (history) as usual.
- **@mentions wake agents.** A live board post (not one from the initial snapshot) that
  @mentions an agent of this GUI arrives in that agent's loop as a user message: the post in
  `read_board`'s line format plus a hint to reply with `post_board`. An idle agent starts a turn;
  a busy one gets it as a steer (a Queued bubble). An agent is never woken by its own post. To
  stop agents pinging each other forever, an agent stops being woken after 5 agent-authored
  mentions in a row; a message from you to that agent, or a board post by you that mentions
  it, re-enables it (the skipped mention is noted in its chat).
- The main agent's board handle is stored in `.dagi/board/main_handle`, so it stays the same
  across launches and @mentions keep reaching it. A board meme from any agent shows in that
  agent's own conversation.
- Code: `pyside_gui/agents_controller.py` (spawn, open, close, board binding),
  `pyside_gui/sidebars/agents_view.py` (the panel).

### Double-Click Launcher (`dagi_run.bat`) — portable/conda-packed distribution

For a distribution that doesn't require a full conda install, unpack a [conda-pack](https://conda.github.io/conda-pack/)'d environment named `dagi_env` as a sibling folder next to this repo:

```
{parent_folder}/
├── driverless_agi/   # this repo
└── dagi_env/         # conda-packed env (conda-pack -n dagi -o dagi_env.tar.gz, then unpacked here)
```

Double-click `dagi_run.bat` in the repo root. It opens a Windows Terminal window (falls back to `cmd` if `wt.exe` isn't on `PATH`), activates `dagi_env`, and runs `dagi_launch.py`, which prompts for:
1. **Model** — numbered list read live from the model catalog (`.dagi/model_config/`)
2. **Verbose** — `y`/`n`

...then launches `tui.py --model <id> [--verbose]` with your selections.

### Electron Desktop GUI (`desktop/`) [experimental]

A native Electron 33 + React 18 desktop app that pairs with the Python sidecar over a versioned NDJSON-over-stdio pipe. Functionally equivalent to the TUI — full conversation, tool cards, plan panel, question dialogs, slash commands — but rendered in a hardware-accelerated browser window.

**Requirements:** Node.js 18+ on PATH.

**Install and run:**

```bash
cd desktop
npm install
npm start   # launches Electron with the Python sidecar auto-detected via DAGI_PYTHON env var
```

**Package (Windows Squirrel installer):**

```bash
cd desktop
npm run make
# output: desktop/out/make/squirrel.windows/
```

**How it works:**

```
Electron main (main.ts)
  ├── PythonSupervisor — spawns dagi_gui/__main__.py, splits NDJSON lines, restarts on crash
  ├── preload.ts — channel-whitelisted contextBridge (send: dagi:command, receive: dagi:event/crash/ready)
  └── Renderer (React)
        ├── App.tsx — useReducer(dagiReducer) + IPC subscription
        ├── Conversation — auto-scroll, ReactMarkdown, streaming cursor
        ├── ToolCard — collapsible, per-tool colour coding
        ├── Composer — auto-resize textarea, slash command autocomplete
        ├── Sidebar — status, cost, tokens, plan panel
        └── QuestionDialog — modal with option buttons or free text
```

**Slash commands:** `/compact`, `/clear`, `/cancel`, `/model <id>`, `/skill <name>`, `/workflow <name>`, `/history`, `/help`

**Security:** `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`. No Node.js APIs exposed to renderer — all IPC goes through the whitelisted `window.dagiAPI` bridge.

### Interactive CLI (`archives/cli.py`) [DEPRECATED]

The legacy CLI REPL has been **archived** in favour of the TUI (`python tui.py`).
It remains available at `archives/cli.py` for reference only — nothing in the live
codebase imports or executes it. The piped subagent binary (used by
`tools/_subagent_runner.py` for explore_files, web_research, read-large-file, etc.) is
`tools/subagent_main.py`, extracted from the old CLI's pipe-mode path and run as
`python -m tools.subagent_main` (so the project root, not `tools/`, is on `sys.path[0]` —
running it by file path instead would let `tools/copy.py` shadow the stdlib `copy` module).

```bash
conda run --no-capture-output -n dagi python archives/cli.py
conda run --no-capture-output -n dagi python tui.py   # preferred
```

### Telegram Bot (`telegram_bot.py`)

Chat with DAGI from your phone via Telegram. Requires a bot token from [@BotFather](https://t.me/BotFather), and the `telegram` extra: `pip install -e ".[telegram]"`.

**Setup:**

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow the prompts → copy the token
2. Add the token to your `.env` file:
   ```env
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   ```
3. **Restrict access** — find your numeric Telegram chat ID (message [@userinfobot](https://t.me/userinfobot)) and add it to `.env`:
   ```env
   TELEGRAM_ALLOWED_CHAT_IDS=123456789,987654321
   ```
   ⚠️ If left unset, the bot accepts commands — including shell access via DAGI's `bash` tool — from *anyone* who finds it on Telegram. The bot logs a warning at startup if this is unset.
4. Optionally add to `config.yaml`:
   ```yaml
   telegram:
     bot_token_env: TELEGRAM_BOT_TOKEN
     allowed_chat_ids_env: TELEGRAM_ALLOWED_CHAT_IDS
   ```

**Run:**
```bash
conda run -n dagi python telegram_bot.py
conda run -n dagi python telegram_bot.py --model claude-sonnet-openrouter
conda run -n dagi python telegram_bot.py --project /path/to/project
```

| Flag | Description |
|------|-------------|
| `--model` / `-m` | Model ID from the model catalog |
| `--project` / `-p` | Project directory |

**Telegram commands:** `/start`, `/clear`, `/help`

Multi-turn conversations are supported — context carries across messages within a chat.

> **Archived UIs:** `archive/app.py` (Streamlit) and `archive/nicegui_app/` (NiceGUI) are no longer maintained.

---

## User Guide

### Starting a New Project

**1. Point dagi at your project directory**

Every session is scoped to a working directory. You can set it at launch time, or navigate to it inside the TUI after it opens.

**Option A — pass the path at launch:**
```bash
# TUI
conda run --no-capture-output -n dagi python tui.py --project /path/to/myproject

# CLI [DEPRECATED — use `python tui.py`]
python archives/cli.py --project /path/to/myproject
```

**Option B — open the TUI first, then navigate:**
```bash
conda run --no-capture-output -n dagi python tui.py
```
Then inside the TUI, use `/wd` to set the working directory:
```
/wd C:\path\to\myproject
```

**2. Scaffold the `.dagi/` directory**

On first use, run `/init` inside the interface. It creates the standard directory tree and stub files:

```
/init
```

This creates:
- `AGENTS.md` — project orientation + behavioral guidelines, injected into every session
- `.dagi/skills/` — directory for project-specific skills
- `.dagi/workflow/` — directory for project-specific workflows
- `wiki/tasks/README.md` — the folder for task specs and plans (knowledge goes to the central
  memory wiki, not here)

You only need to run `/init` once per project. It is safe to re-run — existing files are skipped.

**3. Use the memory wiki**

Project knowledge accumulates in the central memory wiki under `projects/<project-slug>/`
(the slug is the kebab-cased folder name, shown in the per-turn `[MEMORY]` pointer). Ask dagi
to "remember this" or let the workflow file decisions and fixes at task end (`memory-add`);
it searches with `memory-query` at the start of each task and before debugging.

---

### Writing Good Tasks

Dagi works best when the task is concrete and bounded. A few principles:

**Be specific about what "done" looks like:**

```
# Vague
"Fix the authentication"

# Better
"The login endpoint returns 500 when the user submits an empty password.
Fix it so it returns 400 with {"error": "password required"}.
The handler is in api/auth.py."
```

**Scope the task to one concern at a time.** If you have a large feature, use `write-plan` to break approved requirements into subtasks before implementation.

**Give context the agent can't see.** If there's a known constraint, a related PR, or a quirk of the codebase, include it:

```
"The DB client is not thread-safe; all calls must go through the connection pool
in db/pool.py. Refactor the user service to use it."
```

---

### Planning

For complex multi-step tasks, use `write-plan` to write an implementation plan from a spec
or requirements. Standalone plan writing returns the artifact without starting implementation.
Within the full lifecycle, `enter-workflow` owns approval and the transition to `deliver`.

```
/write-plan
```

Or ask naturally:

```
"Plan a refactor of the authentication module to use JWT instead of sessions."
```

**How it works:**

1. `write-plan` writes and self-reviews `wiki/tasks/YYYY-MM-DD_<task>/plan.md`.
2. It returns the plan path and unresolved questions to its caller.
3. When running the full lifecycle, `enter-workflow` handles user approval, independent
   review, active-plan association, and the approval record before delivery.
4. A standalone writing request stops with the plan; it does not authorize implementation.

For implementation, including bounded changes, the sequence is: explore and grill;
ask to create the named task branch; create it; write spec and plan; review and ask for
joint approval; commit both documents; implement and commit each reviewed subtask;
then ask separately whether to merge. The joint approval explicitly covers implementation
and task-scoped commits. Planning-only approval covers just the documents.

During delivery, implementers follow `do-TDD`; workers receive the skill instructions
with their assignments and report test evidence. Only the main agent stages and commits
accepted subtasks, preserving unrelated work. After verification and final review,
`enter-workflow` calls `merging-git-branch` to offer a confirmed local merge into the
named parent or keep-as-is. It records the outcome before detaching the plan. This flow
does not push, create a PR, or automatically delete branches or worktrees.

Approval replies and follow-ups continue the current workflow stage. On resume, dagi
checks the active plan and the checkpoint retained in plan notes or conversation context;
it asks when task identity or approval is unclear. Compaction preserves this checkpoint.
Starting unrelated work does not silently replace an unfinished plan. These are agent
instructions using existing session/plan state, not a separate persisted workflow engine.

---

### Slash Command Reference

All slash commands work identically in the TUI and CLI.

| Command | Description |
|---------|-------------|
| `/help` | Show the command list |
| `/exit` | Exit dagi |
| `/clear` | Clear conversation context and reset the session |
| `/wd [path]` | Show the current working directory, or change it to `path` (GUI: also the header folder button; refused while the agent runs) |
| `/model [id]` | List available models, or switch to `id` immediately |
| `/deliver` | Full delivery lifecycle — grilling, planning, per-task worker/review, integrated verification, detach |
| `/write-plan` | Write an implementation plan; return the artifact without starting delivery |
| `/compact` | Force-compact the current conversation context |
| `/tools` | List all registered tools for the active session |
| `/skills` | List all loaded skills |
| `/workflows` | List all loaded workflows |
| `/hist [n]` | Open the session history picker — browse the `n` most recent sessions (default 20), select a session, then pick a message turn to resume from |
| `/init` | Scaffold `.dagi/`, a slim `AGENTS.md` and `wiki/tasks/` for the current project |
| `/revise-history [n]` | Remove the last `n` steps (default 1) from the session log after a confirmation dialog, then rewrite the JSONL log and re-render the conversation |
| `/show-pet` | Toggle desktop pet window visibility (PySide GUI only); right-click the pet for the notepad |
| `/<skill-name>` | Invoke any loaded skill directly (e.g. `/memory-query`) |
| `/<workflow-name>` | Run any loaded workflow (e.g. `/improve-yourself`) |

---

### Pausing and Resuming

Press `Esc` at any time while the agent is running (TUI or GUI) to interrupt it. `AgentLoop.interrupt()` stops the step in flight:

- A running `bash` command — in the main loop, or inside an active worker/review subagent — is force-killed immediately (surfaced as `[killed by user]` in the conversation, or as a tool error for the subagent call).
- A **streamed** model reply is cut off at once: the stream is closed from the UI thread and `consume_stream` stops on the abort flag. The text received so far is kept in history (so "continue" makes sense); half-streamed tool calls and reasoning are dropped.
- A **blocking** (`stream: false`) request can't be aborted mid-flight; its response is discarded when it lands — nothing is logged and none of its tools run.
- Remaining tool calls in the current response are cancelled individually (each gets a `[paused]` result). A non-`bash` tool that is already running finishes, and a compaction in progress completes.

The abort flag (`_abort_request`) is separate from the pause flag, so resuming quickly can never revive the interrupted response. The status indicator switches to `⏸ Paused`.

Type any message and press `Enter` to inject it into the agent's context and resume — this is equivalent to the agent asking you a question and you answering it. The agent receives your message and continues from where it stopped, with full context intact. A message sent while the loop is still finishing its step is queued and logged by the loop thread at its next checkpoint, so it never lands between a tool call and its result.

Useful for: course-correcting mid-task, adding constraints you forgot to mention, or answering a question the agent was about to ask.

---

### Using Skills

Skills are structured guidance documents in `.dagi/skills/<name>/SKILL.md`. The agent discovers and invokes them via the `skill` tool. You can trigger them from the user side too:

```
Invoke the memory-add skill.
```

Or as a slash command if the skill is loaded:

```
/memory-query
```

**Built-in skills:**

| Skill | Purpose |
|-------|---------|
| `memory-add` | File an entry in the central memory wiki (folder choice, duplicate check, one-line frontmatter) — run inline by the main agent |
| `memory-query` | Grep the central memory wiki (project folder, then knowledge, then all) and answer with citations — inline, read-only |
| `memory-refresh` | Legacy lint for the retired wiki layout — tool disabled pending redesign |
| `create-skill` | Scaffold a new skill document |
| `review-session` | Analyse sessions described in free text (folder, files, time window) into one running cross-session review report |
| `grilling` | Adversarial interrogation of a plan or idea before implementation; returns control to caller when done |
| `to-spec` | Synthesize the current conversation into a written spec (`spec.md`); invoked by `plan`, not user-triggered |
| `plan` | Orchestrate the planning lifecycle: spec synthesis, codebase exploration, plan-file authoring, and user approval; returns control to caller on exit |
| `deliver` | **Primary delivery entry point.** Full lifecycle: grilling → planning → plan review → per-task worker/review cycle → integrated verification → final review → detach. Use `/deliver` for any non-trivial implementation request |
| `dagi-execute` | Compatibility shim — resumes an interrupted delivery from an already-associated plan. Use `/deliver` for new work |
| `update-project-context` | Update `AGENTS.md` with current project state |

Add a project-specific skill by creating `.dagi/skills/<name>/SKILL.md` in your project directory.

---

### Managing Context in Long Sessions

Dagi uses **context compaction** to handle tasks that exceed the model's context window. When the conversation approaches the token limit, the middle of the history is summarized by a dedicated `compact` subagent (which inherits the parent's warm KV-cache prefix) and replaced with the summary — the system prompt and recent messages are always preserved verbatim.

**Manual compaction** is available when you want to reclaim context before the automatic threshold:

```
/compact
```

**Large files and tool outputs** never flood the context. When a `read` result or any tool's output (bash stdout, grep, …) reaches `reserve_tokens`, the agent sees only the first and last 4000 characters (whole lines; `truncate_edge_chars` in `config.yaml`) with a marker in between giving the omitted line range, a token estimate and where the full text is: the file itself for `read`, or the saved copy under `.dagi/hash_cache/tool_output/` for other tools. From there the agent can `read` a range with `offset`/`limit`, `grep` it, or call `read_large_file(path, query?)` for an indexed digest of the whole thing.

`read_large_file` reads the file in order, one chunk per call, carrying a running summary from chunk to chunk and keeping each chunk's notes untouched; the notes are then merged into an index (overview, section table with line ranges, key points and verbatim excerpts). Each call holds only the summary and one chunk, so there is no limit on file length. Excerpts not found verbatim in the file are flagged, and results are cached by file content, query and model under `.dagi/hash_cache/read_large_file/`.

**Switching models mid-session** is supported. A lighter model can handle exploratory steps; switch to a more capable one for complex implementation:

```
/model deepseek-v4-openrouter
```

The context carries over — no need to restart.

---

### Tips for Best Results

- **Start sessions with a specific project.** Using `--project` scopes file access and loads project-local skills, workflows, and the project wiki automatically.
- **Agree on the approach before implementation.** Use `write-plan` to turn the agreed requirements into an implementation plan.
- **Build the memory wiki over time.** The more decisions, fixes and knowledge filed under `projects/<slug>/` and `knowledge/` in the central memory wiki, the less you need to re-explain project context each session — and fixes found in one project help the others.
- **Pause instead of cancelling.** `Esc` in the TUI preserves the agent's full context; you can inject corrections and resume rather than restarting from scratch.
- **Review sessions with `/hist`.** Session summaries in `.dagi/logs/` capture token counts, cost, and what the agent did. The `review-session` skill accepts a free-text description of which sessions to look at and accumulates findings from all of them into one report, so patterns that recur across sessions surface as a single insight.

  Reviewed logs carry `__reviewed_2026-10-02` in their filenames, with session-history
  discovery patterns and event companion pairing preserved.

- **Fill in `AGENTS.md`'s Behavioral Guidelines section for your project.** This whole file is injected into every session for that project. Use the Behavioral Guidelines section for coding standards, architecture invariants, and anything you would otherwise repeat in every task prompt.

---

## Configuration

`.dagi/config.yaml` controls global runtime settings. Model definitions live in individual files under `.dagi/model_config/`.

```yaml
# .dagi/config.yaml — global settings
default_model: gpt-4o-openai        # used if --model isn't passed
max_continuations: 10                # max "continue" injections before giving up
api_error_retries: 3                 # retries for transient API errors (429/5xx/connection)

services:
  doc_converter: "http://localhost:8100"   # optional PDF conversion API; markitdown is the fallback — see below
  message_board:                           # board URL, or just the URL as a string
    url: "http://127.0.0.1:8765"
    bind: "0.0.0.0"                        # where a GUI-launched board listens; token: env or .dagi/board/token
```

### Model Catalog

Each model is a separate file in `.dagi/model_config/` — a YAML entry, or a Python client script (see [Client Scripts](#client-scripts-custom-transport--request-profiles)). The filename (without `.yaml`/`.py`) is the model ID.

```yaml
# .dagi/model_config/gpt-4o-openai.yaml
name: "GPT-4o (OpenAI)"
model: "gpt-4o"
api_url: "https://api.openai.com/v1"
api_key_env: "OPENAI_API_KEY"
```

```yaml
# .dagi/model_config/claude-opus-openrouter.yaml
name: "Claude Opus 4.6 (OpenRouter)"
model: "anthropic/claude-opus-4-6"
api_url: "https://openrouter.ai/api/v1"
api_key_env: "OPENROUTER_API_KEY"
```

Any model file can also override compaction thresholds (defaults shown):

```yaml
# .dagi/model_config/my-model.yaml
name: "My Model"
model: "provider/model-id"
api_url: "https://..."
api_key_env: "MY_API_KEY"
context_window: 128000       # model's hard token limit
reserve_tokens: 16384        # headroom for next reply
keep_recent_tokens: 20000    # recent tail kept verbatim
```

Legacy inline `models:` entries in `config.yaml` still work as a fallback, but file-based entries win on collision.

**Subagent context inheritance:** subagents (worker, review, explore_files, etc.) always use the main agent's context settings (`context_window`, `reserve_tokens`, `keep_recent_tokens`) from the top-level config, regardless of which model tier they run on. Only LLM-specific fields (model, base_url, api_key, thinking) come from the worker/advanced model entry. This ensures consistent context budgets across all agent tiers.

### Client Scripts (Custom Transport & Request Profiles)

For full control over the OpenAI client — mTLS certificates, custom httpx transports, proxies, guardrail headers, request-level defaults — drop a **client script** into `.dagi/model_config/`. A `.py` file there is a model on its own; no YAML is needed. The filename (without `.py`) is the model ID:

```python
# .dagi/model_config/corp_gpt4o.py
import os, ssl, httpx, openai

ctx = ssl.create_default_context(cafile="C:/certs/corp-ca.pem")
ctx.load_cert_chain("C:/certs/client.pem", "C:/certs/client.key")

client = openai.OpenAI(
    api_key=os.environ["CORP_API_KEY"],
    base_url="https://llm-gateway.corp.example.com/v1",
    default_headers={"ENABLE-GUARDRAILS-INPUT-CHECK": "false"},
    http_client=openai.DefaultHttpxClient(
        transport=httpx.HTTPTransport(verify=ctx, retries=2),
        timeout=120.0,
    ),
)

request_kwargs = {"model": "gpt-4o", "temperature": 0.7}   # "model" = name sent to the API

dagi_config = {"name": "GPT-4o (Corp Gateway)", "context_window": 128000}  # optional
```

```yaml
# .dagi/config.yaml
default_model: corp_gpt4o
```

- `client` (required) must be a **sync** `openai.OpenAI`. `AsyncOpenAI` is rejected because dagi calls the API synchronously — use `openai.DefaultHttpxClient` / `httpx.HTTPTransport` rather than `DefaultAsyncHttpxClient` / `httpx.AsyncHTTPTransport`.
- `request_kwargs` (optional) is spread into `chat.completions.create()`. The model name comes from `request_kwargs["model"]` (or `dagi_config["model"]`); a script with neither fails to resolve. `messages`/`tools`/`stream` are always harness-managed.
- `dagi_config` (optional) takes the same keys as a YAML model entry (`name`, `context_window`, `reserve_tokens`, `keep_recent_tokens`, `max_output_tokens`, `thinking`, `stream`, `cache_prompt`, `supports_images`, …). Keep it a plain literal so the model picker can show `name` without executing the script.
- `base_url` / `api_key` for the resolved config are read off the constructed client, so subagents re-resolve the same script-defined provider.
- Scripts are executed once per file version (cached by mtime) and only when selected as `default_model`, `worker_model` or `advanced_model`. A broken worker/advanced script only warns and falls back to the default model.
- Files starting with `_` are ignored (use them for shared helpers). A same-named `.yaml` wins over a `.py`; YAML entries can still point at a script elsewhere with `client_script: path/to/script.py` (relative to the dagi root), with YAML fields taking precedence over the script's `dagi_config`.

See `.dagi/model_config/example_corp.py` for a working example.

### Thinking / Reasoning

Models that support extended thinking (e.g. Qwen3, DeepSeek-R1) can be configured with the `thinking` key in their model file. Values: `none` (default), `low`, `medium`, `high`.

```yaml
# .dagi/model_config/qwen3-30b-openrouter.yaml
name: "Qwen3 30B (OpenRouter)"
model: "qwen/qwen3-30b-a3b"
api_url: "https://openrouter.ai/api/v1"
api_key_env: "OPENROUTER_API_KEY"
thinking: high
```

When reasoning is active:
- A **🧠 Thinking** panel appears in the CLI showing the model's chain-of-thought
- The footer displays reasoning tokens: `in 14,234  think 1,456  out 890`
- When `thinking: none`, no thinking panel or token count is shown

### Streaming

Controls whether the TUI renders assistant text/reasoning incrementally as it's generated, via the `stream` key. Values: `true` (default), `false`.

```yaml
stream: true   # global default
```

Or per-model (overrides the global setting) — useful as an escape hatch for a provider that doesn't handle `stream_options.include_usage` well:

```yaml
# .dagi/model_config/some-model.yaml
stream: false   # this model waits for the full response, like before streaming existed
```

### Parallel tool calls

`parallel_tool_calls` (default `true`) lets the model return several tool calls in one response, so independent reads and edits share a round trip. Calls in a batch still run one at a time, in the model's order. The value follows model switches and is mirrored into inherited subagents and compaction requests, so they keep the parent's prompt-cache prefix. Turn it off globally or per model for a provider that rejects the request field:

```yaml
parallel_tool_calls: false   # global, or inside one model's entry
```

Token/cost usage is requested via `stream_options: {"include_usage": true}` on every streaming call; if a provider never sends the trailing usage chunk, that turn's usage is simply unavailable (the same degraded state that already exists today for providers that omit `usage.cost`) rather than an error. `main.py`, `telegram_bot.py`, and the scheduler are unaffected by this setting — streaming only changes how the TUI renders a turn in progress, not the final result.

While a response is actively streaming, the live preview automatically expands to fill the full window (down to the running-indicator/prompt), so long in-progress replies aren't capped at a few lines — it collapses back to normal once the turn finishes and the final message lands in the conversation pane.

### Code mode

`code_mode` (default `true`) adds the `code` tool: the agent writes one Python script that
chains several tool calls, and only what the script prints or returns enters the context.
Use it for mechanical multi-step work — grep then read the matches, the same edit across
files, run tests and pick out the failures — that would otherwise cost one model request per
call plus every intermediate result.

```python
hits = tools.grep(pattern="def dispatch", path="agent")
for f in sorted({h.split(":")[0] for h in hits.splitlines()}):
    print(f, tools.read(path=f).count("SideEffect"))
```

- The script runs in a child process with dagi's own Python, in the project directory.
  Each `tools.<name>(**args)` call is sent back to the parent and runs through the normal
  tool registry, so path roots and tool behaviour match a direct call.
- Callable: `read`, `grep`, `find`, `write`, `edit`, `copy`, `bash` (minus any filtered out
  by `tools`/`disabled_tools`). `bash` returns `{output, exit_code, timed_out, killed}`; the
  others return their text. A failed call raises `ToolError`, which the script can catch.
  Results that need the loop (e.g. `read` on an image) are refused: make that call directly.
- Calls are real and are not undone. If the script fails, the result shows its output so far,
  a traceback of the script's own lines, and `[already applied] edit(path=…), …`.
- `timeout` defaults to 300 s; Esc kills the script's whole process tree.
- The transcript holds one `code` call and one result; nested calls are not shown as
  separate tool cards.
- Not a sandbox: a script could call `open()` or `subprocess` itself, as `bash` can.

```yaml
code_mode: false   # global only: the code tool is not registered; nothing else changes
```

Spec and plan: `wiki/tasks/2026-10-07_code-mode/`.

### Document Conversion Service

The `read` tool converts documents to markdown:

| File | Conversion |
| --- | --- |
| `.docx`, `.xlsx`, `.xls`, `.pptx` | `markitdown`, in-process |
| `.pdf` | 1. the PDF conversion API (`services.doc_converter`), if configured · 2. `markitdown` |

When no converter can handle a file, `read` returns `Error (DAGI_CANNOT_PROCESS): …` as an
ordinary tool result — the agent loop keeps going. A PDF that fell back to markitdown says so
in its header (`converted by markitdown (conversion service CONNECTION_FAILED: …)`).
markitdown's page breaks become `<!-- Page N -->` markers so `pages` still works; for the
rare PDF it extracts without page breaks, `pages` returns an error and offset/limit work.

The conversion API contract is one `POST {url}/convert` with the file as a multipart `file`
upload; a 200 body is the markdown, anything else is a JSON `{"error", "code"}` body. Any
server that honours it can stand in. The reference implementation is the **doc-converter**
microservice at `services/doc_converter/` (docling + OCR):

**One-time setup:**

```bash
conda env create -f services/doc_converter/environment.yml
```

**Start the service** (in its own terminal, before reading any documents):

```bash
conda run -n doc_converter python -m services.doc_converter
```

By default it listens on `http://localhost:8100`. Point dagi at it via the `services:` block in `config.yaml` (see [Configuration](#configuration)):

```yaml
services:
  doc_converter: "http://localhost:8100"
```

If the service isn't reachable or fails on a file, the `read` tool falls back to markitdown.

**Conversion details:** PDFs use `docling` (digital-native) or `ocrmypdf`+`docling` (scanned, OCR'd first); `.docx`/`.xlsx`/`.pptx` use `markitdown`. PDFs longer than 8 pages are converted in parallel (map-reduce: split into chunks, one docling model load per worker process, then merged and renumbered) — worker count is estimated automatically from CPU count, page count, and free RAM.

**Caching:** dagi caches converted markdown in the hash cache, keyed by the SHA-256 of the file's bytes: `.dagi/hash_cache/doc_convert/` holds conversion-API results and Office conversions, `.dagi/hash_cache/doc_convert_markitdown/` holds PDF fallbacks — kept apart so a fallback never shadows the API's result once the service is back. The read header's `editable:` path points at the cache file. The service also keeps its own server-side cache (`services/doc_converter/.cache/<sha256>.md`).

### Message Board

A shared board where agents and the user post short messages with optional files. It is its
own app (`services/message_board/`, FastAPI + SQLite) and keeps running after the GUI closes
or crashes. Install it with `requirements-board.txt` or the `board` extra (see [Setup](#setup)).

**Config.** `services.message_board` in `.dagi/config.yaml` is either a URL string or a
mapping `{url, bind}`. `url` is the board the GUI connects to (default
`http://127.0.0.1:8765`); `bind` is where a board launched on this machine listens (default
`0.0.0.0`, i.e. reachable from the LAN) at the port in `url`.

**Starting it.** At startup the GUI pings `GET <url>/health`. If the board is unreachable
(refused, timed out or the name does not resolve), it waits 2 s and pings once more; if that
fails too it starts a board **detached** on `bind:<port>` (output in `.dagi/board/board.log`)
and connects to it over `http://127.0.0.1:<port>`. A wrong token or a reply that is not a board
is shown as an error and starts nothing, since something is answering there. The GUI never
stops a running board when it closes. The first `0.0.0.0` launch triggers a Windows Firewall
prompt; allow it for LAN access. Board failures show `Board offline — <reason>` and the board
tools stay unregistered until a later turn finds the board ready. You can also run it yourself:

```bash
python message_board.py                              # serve on the configured bind and port
python message_board.py serve [--host HOST] [--port PORT] [--db PATH]
                              [--token TOKEN] [--runtime-dir DIR]
python message_board.py stop [--url http://127.0.0.1:<port>] [--runtime-dir DIR]
```

`python -m services.message_board …` is the same entry point.

- Data: `.dagi/board/board.sqlite3` (`--db`), attachment bytes in `<db dir>/blobs/`.
- **Web viewer:** open `http://<host>:<port>/` for a read-only live view (latest 50 posts,
  then live updates). Click an image to see it full size with **Download**; files have a
  download button, and files up to 256 KB that are UTF-8 text get a **Preview** toggle. While
  the board is unreachable the page goes dead (dimmed, controls off, "board offline — retrying
  in Ns") and comes back live by itself when the board returns, catching up on posts it missed.
- **Token:** `serve` uses `--token`, then env `DAGI_BOARD_TOKEN`. A non-loopback bind (such as
  `0.0.0.0`) with neither falls back to `.dagi/board/token`, generating one there on first use;
  a loopback bind never reads that file, so it stays tokenless unless you pass one. With a
  token, every endpoint except `GET /` and `GET /health` needs `Authorization: Bearer <token>`;
  the viewer asks for it once. dagi clients (GUI, tools, `stop`) send env `DAGI_BOARD_TOKEN`,
  else the token file — never anything from `config.yaml`. Use the same token on every machine
  that shares a board. The token travels over plain HTTP, so keep LAN boards on trusted networks.
- **Stopping:** `stop` works only for loopback URLs. After binding, `serve` writes a protected
  per-port runtime record (current OS user only) in `--runtime-dir` (default
  `.dagi/board/run`) holding the instance id and a random shutdown capability. `stop` checks
  that record against `/health`, then calls `POST /shutdown` with the capability (plus
  `DAGI_BOARD_TOKEN` when the board has a token). A missing or stale record fails with a
  reason. The PID in `/health` is diagnostic only and is never used to kill anything.
  Exit 0 means stopped (or already down), 1 means not confirmed.
- **Isolated instances** (tests, experiments): pass the same `--runtime-dir` to `serve` and
  `stop`, plus a different `--port` and `--db`.

**Agent tools** (registered only while the board is ready, in this order, just before `show_file`):

| Tool | Behaviour |
|---|---|
| `read_board` | `mentions_only=false`, `limit` 1..10 (default 10). First call returns the latest posts, later calls only newer ones (separate cursors for all/mentions). One line per post plus one line per attachment (kind, name, size, id) — contents are never inline |
| `post_board` | `text` 1..700 chars (longer is rejected: put details in an attachment), optional `meme` (from `.dagi/emotes/memes`), `reply_to`, and `attachments`: up to 4 project file paths, each ≤ 10 MB and checked like `read` paths before anything uploads. Returns `Posted #<id>.` |
| `fetch_attachment` | `attachment_id` (`att_<12 hex>`). Downloads into `<cwd>/.dagi/board/attachments/<id>/<name>` (reused when the hash matches). An image is also attached for the model in the next message, through `read`'s image path (same size limits; needs `supports_images: true`, otherwise a `DAGI_CANNOT_PROCESS` error); any other file is opened with `read` |

**GUI board view.** A header row shows the connected board's URL, an orange **fallback** badge
when it is a local board launched because the configured one was down, and **Connect…** to
switch to any `http(s)` board (a token prompt appears when the board answers 401). While on a
fallback, the GUI pings the configured board every 30 s and shows **Central board is back —
Switch** once it answers. Switching re-registers every agent's handle on the new board, points
their board tools at it (read cursors restart there) and reloads the view; posts made on the
fallback stay on the fallback. Posts render newest first with author, time, meme, text,
`↩ #id` reply hint, image thumbnails and file chips; clicking a thumbnail or chip opens the
downloaded file in the file viewer, and **Save as…** copies it anywhere via the Windows save
dialog. The board and Agents panels open 80px wider than the right sidebar. The composer is a two-line text box (Enter posts, Shift+Enter adds a line) above
a row with the live `n/700` counter (send is blocked over 700), **Attach** (native Windows
multi-select file dialog; at most 4 files, files over 10 MB are refused, removable chips) and
**Send**; posts go out as your persisted user handle. Typing `@` opens an autocomplete of board
members, post authors and this GUI's agents (Tab/Enter accepts, ↑/↓ moves, Esc closes).

#### Message board API

JSON in and out; errors are `{"error": str, "code": str}`. Full contract:
[spec §5](wiki/tasks/2026-10-08_message-board-api/spec.md).

| Method | Path | Purpose | Notable errors |
|---|---|---|---|
| GET | `/` | Read-only web viewer (no token needed) | — |
| GET | `/health` | `{status, version, pid, instance_id}` (no token needed) | — |
| POST | `/shutdown` | `{instance_id}` + `X-Dagi-Stop-Token`; loopback peers only → 202 | 403 `FORBIDDEN`, 409 `STALE_INSTANCE`, 503 `STOP_UNAVAILABLE` |
| POST | `/members` | Register `{handle, display_name?, kind, host?}` → 201 (200 if same) | 409 `HANDLE_TAKEN` |
| GET | `/members` | All members by registration time | — |
| POST | `/attachments` | Multipart `file` + `uploader` → 201 Attachment | 404 `UNKNOWN_AUTHOR`, 413 `TOO_LARGE` (>10 MB), 422 `INVALID` |
| GET | `/attachments/{id}` | File bytes, always `Content-Disposition: attachment` | 404 `UNKNOWN_ATTACHMENT` |
| GET | `/attachments/{id}/meta` | Attachment JSON | 404 `UNKNOWN_ATTACHMENT` |
| POST | `/posts` | `{author, text, meme?, reply_to?, attachments?}` → 201 Post | 404 `UNKNOWN_AUTHOR`/`UNKNOWN_POST`/`UNKNOWN_ATTACHMENT`, 409 `ATTACHMENT_USED`, 422 `INVALID` (>700 chars, >4 attachments, …) |
| GET | `/posts` | `after?`, `limit?` 1..200 (default 50), `mention?` → posts ascending | 422 `INVALID` |
| GET | `/stream` | SSE (`event: post`), backlog after `after?`, `: ping` every 15 s | — |

With a token configured, any endpoint other than `GET /` and `GET /health` returns
401 `UNAUTHORIZED` without the bearer header.

---

## Architecture

```
Driverless_AGI/
├── main.py                # Single-shot CLI (argparse)
├── message_board.py       # python message_board.py [serve|stop] — runs services.message_board
├── archives/              # Deprecated, unused — reference only
│   └── cli.py             #   Old interactive CLI REPL (typer + rich)
├── config.yaml            # Runtime config (gitignored — legacy; see .dagi/)
├── config.example.yaml    # Config template
├── .env                   # API keys (gitignored)
├── SOUL.md                # Agent personality
├── AGENTS.md              # Project context prepended to system prompt
│
├── agent/
│   ├── base_tool.py       # BaseTool ABC
│   ├── registry.py        # ToolRegistry singleton
│   ├── tools.py           # Builds and returns the tool registry
│   ├── board_client.py    # BoardClient/BoardSession — the only message board HTTP client
│   ├── loop.py            # AgentLoop orchestrator (run loop, __init__, pause/resume)
│   │                       #   Frontends use only its public surface: messages (copy), is_paused, is_running,
│   │                       #   revise_last_steps(n), and the tracker= / session_log= constructor arguments
│   ├── _loop_config.py    # AgentConfig, AgentCallbacks, CompactionResult dataclasses
│   ├── _loop_helpers.py   # Loop sentinels, CONTINUE_PROMPT, [MEMORY] pointer + reload helpers
│   ├── _system_prompt.py  # System-prompt assembly (single source of truth)
│   ├── _plan_mode.py      # DEPRECATED stub — re-exports rebuild_for_reload from _reload.py
│   ├── _reload.py         # Hot-reload: rebuild tool registry and system prompt after skill changes
│   ├── _model_switch.py   # LLM tier switching + shared extra_body builder; preflight rejects a switch when
│   │                       #   history has dagi_image parts and the target tier's supports_images is False (image input, stage 3)
│   ├── _streaming.py      # Streaming chat-completions consumer
│   ├── _turns.py          # TurnBoundaries: the one writer of turn/step start/end events (run(), /reload, /wtf, GUI compact)
│   ├── _request_executor.py # Retry policy for one model request (transient-error backoff, ghost retries, pause, abort); `run()` uses it.
│   │                       #   Every `run()` exit path is covered by tests/test_run_contract.py (log well-formedness + replay)
│   ├── _compaction.py     # Context compaction via forked compact subagent; materializes dagi_image parts in the
│   │                       #   reconstructed fork prefix before building the fork snapshot (image input, stage 3)
│   ├── _tool_dispatch.py  # Tool-call dispatch, bookkeeping, first END_TURN wins (later calls in the batch get a `[skipped]` result; on_done fires after all bookkeeping), pause gating, malformed-args sanitisation + surface cache reproject
│   ├── config_loader.py   # Resolves model config from YAML; reads supports_images + per-model image_input: block (image input, stage 3)
│   ├── session.py         # SessionTracker — JSONL logs
│   ├── session_events.py  # Event vocabulary + SESSION_FORMAT_VERSION (3 — bumped for dagi_image content parts, image input stage 2)
│   ├── session_log.py     # SessionLog — append-only tree log (branches, turn/step coords)
│   ├── session_surface.py # Surface — ordered message projection with replace ops and per-node reproject
│   ├── session_store.py   # JSONL persistence (read_session / write_session / append_event)
│   └── context_spec.py    # ContextSpec — byte-identical context reconstruction from log tree
│   ├── prompts.py         # Loads system/user prompts from .dagi/prompts/ and .dagi/subagents/
│   ├── skills.py          # SkillLoader — loads .dagi/skills/
│   ├── workflows.py       # WorkflowLoader — loads .dagi/workflow/
│   ├── sub_agent.py       # SubAgentRunner — legacy in-process subagent (used by cli_subagent)
│   ├── cli_utils.py       # Shared TUI helpers (_cmd_init, _skill_invocation_message) — extracted from archives/cli.py
│   ├── user_input.py      # Qt-free ImageAttachment/UserSubmission value objects (image input, stage 1)
│   ├── image_assets.py    # Content-addressed image store (.dagi/attachments/<sha256>.png), ImageRef, materialize_messages (image input, stage 1)
│   │                       # wired into AgentLoop.run()/inject_and_resume()/_build_request_messages() (image input, stage 2)
│   ├── _loop_config.py    # AgentConfig/AgentCallbacks dataclasses; AgentConfig carries flat supports_images/
│   │                       #   image_input_* fields (None=unknown-permit, True=permit, False=block) (image input, stage 3)
│   ├── history.py         # JSONL session parsing for TUI/GUI sidecar; _content_label() renders dagi_image content
│   │                       #   parts as "text [N images]" in titles, turn lists, and copyable messages (image input, stage 3)
│   └── _git_branch.py     # Plan branching helper — creates/checks out dagi/<slug>_<plan_id> from HEAD
│
├── tools/                  # Every tool is a subfolder: tools/<name>/__init__.py re-exports
│   │                       #   from tools/<name>/_<name>.py (the underscore-prefixed module is
│   │                       #   the private implementation). Follow this pattern for new tools.
│   ├── read/               # read.py's replacement — text inline; documents as markdown;
│   │   │                   #   images attached for multimodal models
│   │   ├── _read.py        #   ReadTool (head + marker + tail when too large; images → ATTACH_IMAGE)
│   │   ├── _source.py      #   file/document loader shared with read_large_file
│   │   ├── _convert.py     #   Office → markitdown; PDF → conversion API, then markitdown; hash-cached
│   │   ├── _doc_service.py #   HTTP client (anti-corruption layer) to the PDF conversion API
│   │   ├── _image.py       #   image → ImageAttachment (Pillow; re-encode/downscale to limits)
│   │   ├── _selection.py   #   frozen selection snapshot (text + line spans) sent to the reader
│   │   ├── _chunking.py    #   Chonkie / stdlib chunking with line references
│   │   ├── _budgets.py     #   reader budget arithmetic (per-call fit, chunk size, parent fit)
│   │   ├── _reader_job.py  #   reader job manifest + run_reader() (spawns the reader subprocess)
│   │   ├── _reader_provider.py # API calls, retries, progress events for the reader
│   │   └── _reader_controller.py # read_large_file loop: chunk notes + running summary → merged index
│   ├── _truncate.py        # truncate_middle(): head + marker + tail, shared by read and output_filter.py
│   ├── output_filter.py    # oversized tool results → saved to hash cache + truncate_middle()
│   ├── write/               # Overwrite a file
│   ├── edit/                 # Exact-text replacement
│   ├── bash/                # Run shell commands
│   ├── git/                # git_status, git_diff, git_log, git_branch, git_checkout, git_add, git_commit, git_reset
│   │                       #   (git_add/git_commit/git_reset are whitelist-guarded to dagi/* branches only;
│   │                       #   git_commit requires explicit git_add staging first — no implicit add -A;
│   │                       #   enter-workflow owns task-branch setup)
│   ├── grep/               # Regex search across files (ripgrep)
│   ├── find/                # Glob-pattern file finder
│   ├── skill/               # Load a .dagi/skills/ guidance document
│   ├── workflow/            # Workflow content loader and lister (CLI helpers)
│   ├── web_search/          # DuckDuckGo web search
│   ├── web_fetch/           # Fetch and parse a URL
│   ├── web_research/        # Multi-page web research (spawns pipe subagent)
│   ├── explore_files/       # Large-scale codebase scanning (spawns pipe subagent)
│   ├── subagent_api.py    # Public API — run_subagent() / SubagentResult / resume_subagent_by_pid(); immediate and resumed results share one finalizer (branch identity + stale-parent-context rejection)
│   ├── _subagent_runner.py # Private runner — Popen(stdout=PIPE), JSON event relay, PID polling, fault-isolated stdout drain (survives log-open/write and decode failures, noting them in output_tail); only called by subagent_api.py
│   ├── subagent_main.py   # Piped subagent entry point (spawned via `python -m tools.subagent_main`)
│   ├── extend_timeout/      # ExtendSubagentTimeoutTool — resume in-flight subagent deadline
│   ├── compact/             # Trigger context compaction
│   ├── switch_model/        # Swap models mid-session
│   ├── show_file/           # Open a file in the GUI file viewer with optional line highlight
│   ├── ask_user/            # Prompt user for clarification
│   ├── escalate_issue/      # Worker/review subagents: sidecar-file escalation to the main agent
│   ├── write_handoff/       # Main-agent and subagent final-report tool — main mode returns
│   │                        #   ToolResult(side_effect=END_TURN); subagent mode writes file
│   ├── _task_envelope.py  # wrap_envelope() — universal ## Instructions/## Output sections appended
│   │                        #   to every spawned subagent's task (shared helper, not a tool folder)
│   ├── _handoff_format.py # format_handoff_result() — shared "ok"/"ok_unverified" result rendering
│   │                        #   (warning banner + inlined content) (shared helper, not a tool folder)
│   └── _path_guard.py     # Path sandboxing utilities (shared helper, not a tool folder)
│
├── services/
│   ├── doc_converter/      # Standalone FastAPI microservice: PDF/docx/xlsx/pptx → markdown.
│   │   │                   #   Own conda env (environment.yml) — heavy deps (docling, torch,
│   │   │                   #   pymupdf, ocrmypdf, markitdown) live only here, not in dagi core.
│   │   │                   #   Start with: python -m services.doc_converter (port 8100)
│   │   ├── main.py         #   FastAPI app, POST /convert endpoint
│   │   └── converter/
│   │       ├── pdf.py      #   PDF→markdown (docling digital / ocrmypdf+docling scanned, parallel path)
│   │       ├── office.py   #   docx/xlsx/pptx→markdown via markitdown
│   │       └── cache.py    #   Server-side content-addressed cache (.cache/<sha256>.md)
│   └── message_board/      # Standalone board service (FastAPI + SQLite, `board` extra).
│                           #   python message_board.py [serve|stop]; settings.py reads
│                           #   services.message_board and the .dagi/board/token file;
│                           #   app.py endpoints, store.py/blobs.py storage, uploads.py
│                           #   streaming multipart, lifecycle.py + runtime_records.py
│                           #   protected local stop, static/index.html web viewer
│
├── .dagi/
│   ├── config.yaml        # Global runtime settings (tool allowlist, disabled_tools, context budget, memory_root)
│   ├── model_config/      # Per-model YAML files or .py client scripts (filename = model_id); git-tracked
│   ├── prompts/           # Prompt markdown files, organized by role
│   │   ├── main/          #   main_system.md — primary coding assistant prompt
│   │   └── compact/       #   compact_system, compact_user (Pi-style summariser)
│   ├── subagents/         # Per-subagent type: <name>/main.py (BaseTool subclass) + subagent_config.yaml
│   │   │                  #   Discovered by import via _discover_subagent_tools() in agent/subagent_tools.py
│   │   ├── compact/         #   context compaction summarizer (internal-only, no main.py — not model-callable)
│   │   ├── read-large-file/ # `read_large_file` tool + reader prompt (fixed reader loop, no tools)
│   │   ├── explore_files/ #   exploration agent (tools: read, grep, find)
│   │   ├── web_research/  #   web research agent (tools: web_search, web_fetch)
│   │   ├── worker/        #   full-tool worker agent (plan_utils.py helper)
│   │   ├── review/        #   code review agent (review_utils.py helper; tools: read, grep, find, bash)
│   │   ├── plan/          #   plan-writing agent
│   │   └── cli/           #   custom subagent with caller-supplied system prompt
│   ├── handoffs/          # Generated handoffs: main_<thread-hash12>.md and <type>_<uuid8>.md
│   ├── skills/            # Structured guidance documents (memory-add/query copies of the Claude skills, create-skill, …)
│   ├── workflow/          # User-directed workflows (.dagi/workflow/<name>/workflow.md)
│   ├── tools/             # Project-local tools (auto-loaded at startup)
│   ├── gnhf/              # GNHF session artifacts (notes.md — committed to dagi branch)
│   ├── plans/             # Generated plan files
│   ├── logs/              # Session JSONL files
│   ├── attachments/       # Content-addressed image store (<sha256>.png/.jpg), gitignored — see agent/image_assets.py
│   └── self-review/       # Session review reports and improvement plans
│
├── archive/
│   ├── app.py             # Streamlit web UI (deprecated)
│   └── nicegui_app/       # NiceGUI web UI (deprecated)
│
└── snapshots/             # Isolated agent snapshots for the improve-yourself workflow
```

### Tools

| Tool | What it does |
|------|-------------|
| `read` | Read a text file (paginated) inline. Office files (`.docx`/`.xlsx`/`.xls`/`.pptx`) convert to markdown via markitdown; `.pdf` goes to the PDF conversion API when configured, else markitdown (see [Document Conversion Service](#document-conversion-service) below). Images are shown to the model when the active tier has `supports_images: true`. Unconvertible files return a `DAGI_CANNOT_PROCESS` error result. PDF output includes a `[PDF: name \| N pages]` header; `pages` (PDF only, e.g. `'1-5'`) filters by `<!-- Page N -->` markers. Reads the whole file unless `offset`/`limit` are given; results over `reserve_tokens` come back as head + marker + tail (see [Managing Context in Long Sessions](#managing-context-in-long-sessions)). Pass `path`, optional `offset`/`limit`, optional `pages` |
| `read_large_file` | Indexed digest of a file too large for context (`.dagi/subagents/read-large-file/`): overview, section table with line ranges, key points and verbatim excerpts. Reads chunk by chunk with a running summary, so any length works; results cached. Pass `path`, optional `query`, `offset`/`limit`, `pages` |
| `write` | Overwrite a file. Creates parent dirs. Takes `path` + `content` |
| `edit` | Edit a file by replacing exact text (`oldText` → `newText`). The match must be unique; CRLF-safe. For several changes to one file, pass `edits` (a list of `{oldText, newText}`): applied in order in one call, all-or-nothing, errors name the failing edit (`edit 2 of 3`). Empty placeholder arguments and a JSON-string `edits` are tolerated |
| `bash` | Run a shell command. Returns stdout + stderr + exit code. Pass `command` + optional `timeout`. Its description names the real OS, version and shell (`%COMSPEC%`/cmd.exe on Windows, `/bin/sh` on POSIX), so the model uses valid syntax from its first command. A piped command's result ends with a note that the exit status belongs to the last command only (`pytest | findstr` can otherwise hide a failure) |
| `code` | Run one Python script that chains `read`/`grep`/`find`/`write`/`edit`/`copy`/`bash` calls as `tools.<name>(**args)`; only what the script prints or returns comes back. Registered when `code_mode` is on (the default). See [Code mode](#code-mode) |
| `grep` | Regex search across files using ripgrep (rg). Returns `file:line:match` format. Automatically excludes binary files (`.pyc`, `.pyo`, `.bin`), `__pycache__`, `.git`, `.dagi`, and other non-source directories. `path` must be a specific subdirectory or file (not `.` / project root). No result cap: very large results go through the shared head + marker + tail filter, with the full list saved |
| `find` | Find files by glob pattern (e.g. `**/*.py`). Searches all allowed roots when no path given. No result cap: very large results go through the shared head + marker + tail filter, with the full list saved |
| `skill` | Load a `.dagi/skills/<name>/SKILL.md` guidance document and return it for execution |
| `web_search` | DuckDuckGo web search. Returns titles, URLs, and snippets |
| `web_fetch` | Fetch and parse a URL. Returns cleaned page text |
| `web_research` | Multi-page research task: searches, fetches, and synthesizes results. Runs as a pipe subagent; output streams to the main TUI with a `[web_research]` label |
| `explore_files` | Large-scale codebase scan: explores with broad-to-narrow strategy (glob/grep first, targeted reads second) and returns a citation-first handoff (`path:line_start-line_end` entries). Runs as a pipe subagent; output streams to the main TUI with an `[explore_files]` label |
| `extend_subagent_timeout` | Extend the deadline of an in-flight subagent by PID. Called by the agent when `spawn_*` returns a timeout dict |
| `compact` | Manually trigger Pi-style context compaction |
| `switch_model` | Swap to a different model (from the model catalog) mid-session |
| `read_notepad` | Read-only: return the user's global pet-notepad markdown (`.dagi/notepad/notepad.md`, LaTeX math kept as source) with a last-edited/char-count header; truncated at 20k chars. Always registered (GUI, TUI, Telegram); in the GUI it first flushes unsaved editor text (≤2 s wait). No parameters |
| `read_board` | Read new [message board](#message-board) posts (`mentions_only`, `limit` ≤ 10); attachments appear as one line each (name, size, id), never their contents. Registered only while the board is ready |
| `post_board` | Post to the message board: `text` ≤ 700 chars, optional `meme`, `reply_to`, and up to 4 project files (≤ 10 MB each) as `attachments`. Registered only while the board is ready |
| `fetch_attachment` | Download a board attachment by id into `.dagi/board/attachments/<id>/`; an image is also shown to the model (multimodal models only), other files are opened with `read`. Registered only while the board is ready |
| `show_file` | Open a file in the PySide GUI's file viewer for the user, optionally jumping to and highlighting a specific line number. No-op in TUI/Telegram |
| `ask_user` | Pause and ask the user a clarifying question with optional choices. Acts as a turn-ender — the agent should call `ask_user` instead of `write_handoff` when it needs the user to answer a question before continuing. Must be the only tool call in its response: a batch mixing `ask_user` with other tools is refused before anything runs, so no action is taken ahead of the answer |
| `show_plan` | Render the current plan document and ask the user for revisions. Returns "Plan approved" (call `set_active_plan`) or "Modifications requested" (revise and call `show_plan` again). In autonomous mode, auto-approves immediately |
| `escalate_issue` | Worker/review subagent only: raise a blocking question to the main agent instead of guessing. Writes a sidecar file next to the subagent's handoff report; the main agent's subprocess poll loop detects it, terminates the subagent, and surfaces `"[worker escalated]"` / `"[review escalated]"` with the question and context — does not consume a `dagi-execute` retry attempt |
| `write_handoff` | Always visible to the main agent and auto-injected into every subagent with a `handoff_path`. It writes `content` verbatim to a baked-in path and its sentinel immediately ends the turn, so no `END_OF_RESPONSE` is needed. Main-agent calls save `.dagi/handoffs/main_<thread-hash12>.md` and render the full Markdown in the TUI; inherited children reuse the exact parent-visible schema but write to their assigned child path. The lifecycle name is reserved against project-tool collisions. |

File tools (`read`, `write`, `edit`, `grep`, `find`) are sandboxed to allowed roots via `tools/_path_guard.py`. `bash` is intentionally unsandboxed. `code` scripts call the file tools through the same registry, so the same roots apply to `tools.*` calls; the script itself is ordinary Python and is no more sandboxed than `bash`.

The 2026-10-02 Windows shell investigation reproduced missing Unix commands and partial
multiline `python -c` execution with a successful exit. Runtime metadata, shell-free argv/stdin
execution, and aligned skill examples are proposed in [TODO](TODO.md); no runtime fix is applied.

Every subagent spawn tool (worker, review, explore_files, web_research, or any type discovered from `.dagi/subagents/`) reads the subagent's handoff file and inlines its full content directly into the tool's own result on success (via `tools/_handoff_format.py::format_handoff_result()`) — the main agent never has to make a separate `read` call to see what a subagent produced. `extend_subagent_timeout`'s resume path does the same. Large handoffs are still subject to the normal output-filter truncation (head + marker + tail) like any other tool result.

**Enforced handoff + unverified fallback:** if a subagent's turn ends without ever calling `write_handoff` — e.g. `explore_files`/`web_research`, which have no general `write` tool and previously could not comply structurally — `tools/subagent_main.py::_ensure_handoff()` gives it one corrective retry naming the tool explicitly, then, if still missing, scrapes the last assistant message into the handoff file and drops a `<stem>_unverified.flag` sidecar. `tools/_subagent_runner.py` turns that flag into result status `"ok_unverified"`, and every spawn tool renders it as a `⚠️ UNVERIFIED HANDOFF` warning banner above the (possibly informal) content, so the parent never mistakes a scrape for a deliberate report.

Version-2 inherited children keep the parent's exact tool schema and order for prompt-cache reuse. `write_handoff` is the final child action; the runner validates the written file, gives a missing or malformed report one corrective tool-call turn, and then fails hard instead of accepting assistant text or creating an unverified fallback.

**Parent-authored briefing/handoff_spec:** every subagent spawn tool accepts optional `briefing` (guidance: traps to avoid, prior failed-attempt context, extra constraints) and `handoff_spec` (what you want in the report) parameters. Both are composed into the subagent's task via `tools/_task_envelope.py::wrap_envelope()` — an `## Instructions` section (only if `briefing` is given) followed by an always-present `## Output` section (`handoff_spec`, or the type's `default_handoff_spec` from its `subagent_config.yaml`, or a generic fallback).

### Adding a Custom Tool

**Option A — core tool:** Create a subfolder in `tools/` following the standard layout — implementation in a leading-underscore private module, re-exported by `__init__.py` — then register it in `agent/tools.py`:

```python
# tools/my_tool/_my_tool.py
from agent.base_tool import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    _parameters = {
        "type": "object",
        "properties": {
            "input": {"type": "string"},
        },
        "required": ["input"],
    }

    def run(self, input: str) -> str:
        return f"processed: {input}"
```

```python
# tools/my_tool/__init__.py
from ._my_tool import MyTool

__all__ = ["MyTool"]
```

Then import and register in `agent/tools.py`. A bare `tools/my_tool.py` file is the old (pre-2026-07-25) convention and no longer used anywhere in the tree.

**Option B — project-local tool:** Drop a `.py` file into `.dagi/tools/`. It will be auto-discovered and registered at startup — no changes to core files needed.

---

## Skills

Skills are structured guidance documents stored at `.dagi/skills/<name>/SKILL.md`. When the agent calls `skill("memory-add")`, it loads and reads the full document, which contains step-by-step instructions and embedded scripts the agent then follows.

Built-in skills:

| Skill | What it does |
|-------|-------------|
| `memory-add` | File an entry in the central memory wiki (folder choice, duplicate check, one-line frontmatter) — run inline by the main agent |
| `memory-query` | Grep the central memory wiki (project folder, then knowledge, then all) and answer with citations — inline, read-only |
| `memory-refresh` | Legacy lint for the retired wiki layout — tool disabled pending redesign |
| `create-skill` | Scaffold a new skill document |
| `review-session` | Deep-read sessions described in free text, analyse tasks/actions/errors/corrections across all of them, and accumulate findings into one running review report at `.dagi/self-review/` |

Add a custom skill by creating `.dagi/skills/<name>/SKILL.md`.

---

## Workflows

Workflows are user-directed multi-step procedures stored at `.dagi/workflow/<name>/workflow.md`
with optional YAML frontmatter (`name`, `description`). Unlike skills, they are **not injected
into the system prompt** and are not autonomously discoverable by the agent — they are invoked
only when the user types a slash command in the interactive CLI.

**Discovery and invocation (in `archives/cli.py`):**
- At startup, all workflows under `.dagi/workflow/` are loaded via `agent/workflows.py`
- `/workflows` — list all loaded workflows with their descriptions
- `/<workflow-name>` — inject the workflow document as the next agent task; any sibling scripts
  in the workflow directory are listed automatically by `tools/workflow.py`

**Built-in workflows:**

| Workflow | Command | What it does |
|----------|---------|-------------|
| `improve-yourself` | `/improve-yourself` | End-to-end self-improvement loop: picks a `review-item` from the Work Queue, researches prior art, runs baseline and after tests in an isolated snapshot, compares structural metrics, and writes a verdict + ready-to-apply implementation description to `TODO.md` |

Add a custom workflow by creating `.dagi/workflow/<name>/workflow.md`. Any sibling `.py`,
`.sh`, or other script files in the workflow directory are listed in the injected task
message when the workflow is invoked.

---

## Session Logs

Every run is logged to `.dagi/logs/session_<timestamp>.jsonl`. Entries include:

- Message history with token counts and cost estimates
- Tool call start/end events with inputs/outputs
- Session summary with totals on finish

Logs are append-only JSONL — each line is a self-contained JSON record.

---

## Agent Identity

`SOUL.md` defines the agent's personality. `AGENTS.md` provides project context. Both are prepended to the system prompt at startup.

---

## Running Benchmarks

### DAGI Eval Benchmark (coding speedup + DS scorecard)

`benchmarks/dagi_eval/` is a self-contained scorecard for comparing dagi
versions/models: 5 coding-speedup tasks (write a faster program than a
supplied working-but-naive baseline, scored on correctness + wall-clock
speedup) and 1 data-science task (train the best model you can on a frozen
tabular dataset, scored on ROC-AUC).

**Running a real benchmark:**

```bash
conda run -n dagi python -m benchmarks.dagi_eval.run --model <id> --label "<note>"
```

`--model` selects an entry from `benchmarks/dagi_eval/config_dagi_eval.yaml`.
Omit `--task` to run all 6 tasks, or pass `--task <name>` (repeatable) to run
a subset.

**Output — one self-contained folder per run:**

Every invocation creates `.dagi/benchmarks/dagi_eval/logs/<timestamp>_log/`:

```
result.jsonl        one row per task, plus a final "__aggregate__" row
code/<task_name>/   copy of that task's final workspace, exactly as scored
sessions/<task_name>/session_*.jsonl   agent transcripts (--solver agent only)
```

Each per-task row always carries `baseline_score` and `golden_score` —
scored fresh from the canned naive/gold solutions regardless of which
`--solver` produced `recorded_score` (neither canned solution invokes the
LLM, so this costs no tokens) — plus `unified_score`, an efficiency-adjusted
score in `[0, MAX_UNIFIED_SCORE]`: `normalized_perf` maps `recorded_score`
to `[0, 1]` using `baseline_score` as the floor and `golden_score` as the
ceiling (0 = no better than baseline, 1 = matches the handcrafted gold
solution), divided by `normalized_tokens` (total tokens scaled against a
tunable per-task budget). See `benchmarks/dagi_eval/scoring.py` for the exact
constants/formulas.

**Self-test mode (no LLM calls, no cost):**

```bash
conda run -n dagi python -m benchmarks.dagi_eval.run --solver naive --label "self-test"
conda run -n dagi python -m benchmarks.dagi_eval.run --solver gold  --label "self-test"
```

`--solver naive|gold` runs a canned reference solution instead of the real
agent — `naive` re-runs each task's own baseline (sanity check: `speedup`
should land near 1.0, `ds_score` near 1.0) and `gold` runs each task's
reference fast solution (every coding speedup should clear that task's
`gold_min_speedup` from its `task.yaml`, and `ds_score` should be ≥ 1.3).
`--solver agent` (the default when `--solver` is omitted) invokes a real,
billed LLM call via dagi's `AgentLoop` — only use it with an actual model
budgeted for the run.

**Task inputs:** each coding task's `hidden/` test inputs are regenerated
per machine by that task's own `hidden/make_inputs.py` (seeded, so
deterministic on a given machine, but not committed to git — this keeps the
repo small and avoids environment-specific frozen artifacts). The one DS
task, `ds_01_tabular`, is the exception: its dataset (`train.csv`,
`test_features.csv`, `test_labels.csv`, `meta.json`) is generated once and
committed frozen, since retraining/regenerating it would silently change
the benchmark's difficulty across runs.

---

## Dependencies

Direct application dependencies are declared in `pyproject.toml`. The requirements files separately preserve the original environment's exact package pins by feature (see [Setup](#setup)).

`environment.yml` creates the same core environment as `requirements-core.txt`.
Neither is a fully pinned lockfile. Add UI/tool groups explicitly; see [Setup](#setup).

| Group | Direct dependencies / purpose |
|---|---|
| Core | openai, pyyaml, python-dotenv, rich, httpx |
| `tui` | textual, typer |
| `board` | fastapi, uvicorn, python-multipart (message board service) |
| `gui` | TUI helpers, board, pyside6, markdown-it-py, pygments |
| `web` | ddgs, crawl4ai, beautifulsoup4 |
| `notifications` | win11toast on Windows only |
| `telegram` | python-telegram-bot, typer |
| `benchmark` | numpy, pandas, scipy, scikit-learn |
| `dev` | pytest, psutil, ruff |

LangChain and the PDF/ML stack are not required by the core agent. Their original pins
are retained in `requirements-legacy.txt` and `requirements-pdf.txt`. The read tool
calls the document converter over HTTP; prefer the service's own environment recipe
for a complete converter installation, including its server and system dependencies.

Document conversion service (separate env, `services/doc_converter/environment.yml`):

- `fastapi` + `uvicorn` — HTTP service framework
- `docling`, `pymupdf`, `ocrmypdf` — PDF reading (`ocrmypdf` also needs the `tesseract` system binary, installed via your OS package manager); `psutil` — free-RAM probing for PDF parallel-conversion worker-count estimation
- `markitdown` — DOCX/XLSX/PPTX reading

### Windows notifications (TUI, optional)

- `win11toast` — native Windows 10/11 toast notifications, an optional `notifications` extra whose original pins are included in the GUI requirements file. `tui.py` fires a toast (`tui/notifications.py::notify()`) when DAGI asks a question, presents a plan for interactive review, or reaches end-of-response. The toast is skipped when the TUI's own console window already has OS focus (`_tui_window_is_foreground()`), so you're only notified when you've alt-tabbed away; if that focus check itself fails, it fails open and still notifies. Lazily imported and exception-guarded — degrades silently to a no-op on non-Windows hosts or if the package is missing, never blocking the TUI. Not used by `cli.py`, `telegram_bot.py`, subagents, or the scheduler. Independent of the toast, every end-of-response also writes a `— turn complete —` marker directly into the conversation pane (`tui/callbacks.py::on_done`) — this stays visible even when the toast is suppressed (window focused) or the model's final response text was empty, so a normal turn ending is never mistaken for a stalled agent.
