# Driverless AGI

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

To end a turn the agent calls either **`write_handoff`** (final response) or **`ask_user`** (pause for user input). `write_handoff` takes the complete user-facing response as `content` and returns a typed `ToolResult(side_effect=SideEffect.END_TURN)` that the loop detects and uses to exit cleanly — no in-band string sentinels. `ask_user` pauses the turn and waits for the user's answer; after receiving it, the agent continues working or calls `write_handoff` to finish. If the agent produces a response with no tool calls and neither turn-ending tool, the harness treats it as accidentally truncated and injects a recovery prompt (`.dagi/prompts/main/continue.md`) to resume the loop. A safety valve (`max_continuations`, default 10, configurable in `config.yaml`) prevents runaway recovery loops. Additionally, **garbled loop recovery** detects when the model produces 3 consecutive empty-content responses (a common failure mode with smaller models), revises those empty steps out of the session log, and triggers a full context compaction to give the model a fresh start.

**Garbled loop recovery:** When a model produces consecutive empty-content responses (common with smaller models), the harness automatically strips the degenerate turns, compacts the full context, and retries — rather than burning through all continuation attempts.

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
pip install -r requirements-core.txt -r requirements-gui.txt    # add PySide GUI
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

PDF/DOCX/XLSX/PPTX reading no longer requires any dagi-side extras — it's handled entirely by the standalone doc-converter service, set up separately. See [Document Conversion Service](#document-conversion-service).

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

**Running tests / pytest-qt "DLL load failed while importing QtCore"** — `pyproject.toml` disables pytest-qt globally (`-p no:pytest-qt`) because on Windows it imports QtCore before PySide6's DLL directories are registered. `pyside_gui/tests/conftest.py` re-registers the plugin after the `pyside_gui` DLL bootstrap, so `qtbot`/`qapp` work there. Run everything with `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest tests pyside_gui/tests -q` (plain `pytest` only runs `tests/`).

**GPU/CUDA** — PDF conversion always runs on CPU. `services/doc_converter/converter/pdf.py` sets `CUDA_VISIBLE_DEVICES=""` and passes `AcceleratorOptions(device=AcceleratorDevice.CPU)` to docling explicitly, so no CUDA device is ever touched by docling or tesseract/ocrmypdf, regardless of what's installed on the host.

---

## Usage

### Single-Shot CLI (`main.py`)

Runs one task and exits. Uses argparse.

```bash
python main.py "Fix the off-by-one error in processor.py"
python main.py --model gpt-4o-openai --max-iter 50 "your task"
echo "Add type hints to agent/" | python main.py
```

| Flag | Description |
|------|-------------|
| `--model` | Model ID from the model catalog |
| `--max-iter` | Override max iterations |
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

A native Qt 6 desktop app with a slate-indigo dark theme. Functionally equivalent to the TUI — full streaming conversation (rendered with Vditor in a QWebEngineView), right sidebar with token stats and plan tracker, left sidebar with session history/file tree/plan/message board, overlay dialogs, and the full slash-command set. The **message board** tab in the left sidebar displays posts from the `emote` tool — each post shows a meme asset, a text line, and a timestamp.

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
  - The empty chat shows the pet's idle emote, the model and the project path until the first message.
  - Clicked links open in the system browser.
  - Calls made before the page finishes loading are queued and replayed.
- **Composer** (`prompt_input.py`): a rounded card holding:
  - image thumbnails;
  - a text field that grows from one line to 240px (`Ctrl+O` compose mode makes it tall);
  - a `+` button that opens a file dialog for PNG/JPEG;
  - a model pill that lists the catalog and switches through `/model`;
  - a context ring (`context_meter.py`) beside it that fills with context-window use — the same total as the right sidebar's CONTEXT bar (system prompt + history + reserve), so 100% is where the loop compacts. Neutral below 70%, `warn` from 70%, `danger` from 90%; the tooltip shows exact tokens; hidden until the first model call or when the window is unknown; clicking does nothing;
  - a white round send button that turns into ■ Stop (same as `Esc`) while the agent runs with the input locked.
- **Chrome:**
  - A slim header over the conversation has buttons to hide or show the whole left and right sidebars (`pyside_gui/header.py`).
  - Next to the left toggle, a folder button (`📁 <folder> ▾`) works like VS Code's *Open Folder*: its menu has **Open Folder…** (native picker), the 5 most recent folders (current one ticked, missing ones greyed out) and **Clear recent**. Picks run through `/wd`, so the button and the typed command share the same checks — switching is refused while the agent runs (press `Esc` first). Recents are saved to `.dagi/recent_folders.json` (git-ignored) on every successful `/wd` and at startup (`pyside_gui/recent_folders.py`). The centred header title shows the model.
  - The right sidebar has a compact pet emote box (150×130), a status pill, the model name and dim `cwd`/`app`/`mem` rows (full path on hover). Its token and context sections use dim labels with right-aligned coloured values, and context has a usage bar with per-bucket %.
  - Session history rows show the title with a dim `time · model` line.
  - The left rail uses checkable icon buttons. The message board opens as wide as the right sidebar; other left views split the space with the chat. Either can be dragged.
  - Splitters are 1px.
- Design notes, decisions and the mockup: `docs/2026-09-30_openghost-ui-review.md`, `docs/mockups/dagi-ui-mockup.html`.

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
`tools/_subagent_runner.py` for explore_files, web_research, read-large-text, etc.) is
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
  doc_converter: "http://localhost:8100"   # required for reading .pdf/.docx/.xlsx/.pptx — see below
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

Token/cost usage is requested via `stream_options: {"include_usage": true}` on every streaming call; if a provider never sends the trailing usage chunk, that turn's usage is simply unavailable (the same degraded state that already exists today for providers that omit `usage.cost`) rather than an error. `main.py`, `telegram_bot.py`, and the scheduler are unaffected by this setting — streaming only changes how the TUI renders a turn in progress, not the final result.

While a response is actively streaming, the live preview automatically expands to fill the full window (down to the running-indicator/prompt), so long in-progress replies aren't capped at a few lines — it collapses back to normal once the turn finishes and the final message lands in the conversation pane.

### Document Conversion Service

Reading `.pdf`, `.docx`, `.xlsx`, or `.pptx` files requires the standalone **doc-converter** microservice at `services/doc_converter/`. Plain text files need no extra setup — only document conversion depends on this service.

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

If the service isn't reachable, the `read` tool returns a clear error asking you to start it — there is no inline/fallback conversion path.

**Conversion details:** PDFs use `docling` (digital-native) or `ocrmypdf`+`docling` (scanned, OCR'd first); `.docx`/`.xlsx`/`.pptx` use `markitdown`. PDFs longer than 8 pages are converted in parallel (map-reduce: split into chunks, one docling model load per worker process, then merged and renumbered) — worker count is estimated automatically from CPU count, page count, and free RAM.

**Two-layer caching:** the service maintains a server-side content-addressed cache (`services/doc_converter/.cache/<sha256>.md`, keyed by SHA-256 of the uploaded file's bytes) so repeated conversions of the same file across any client are free. dagi additionally keeps a client-side cache under `.dagi/hash_cache/doc_convert/`, keyed by the same hash, so unchanged files aren't even re-uploaded.

---

## Architecture

```
Driverless_AGI/
├── main.py                # Single-shot CLI (argparse)
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
│   ├── loop.py            # AgentLoop orchestrator (run loop, __init__, pause/resume)
│   ├── _loop_config.py    # AgentConfig, AgentCallbacks, CompactionResult dataclasses
│   ├── _loop_helpers.py   # Loop sentinels, CONTINUE_PROMPT, [MEMORY] pointer + reload helpers
│   ├── _system_prompt.py  # System-prompt assembly (single source of truth)
│   ├── _plan_mode.py      # DEPRECATED stub — re-exports rebuild_for_reload from _reload.py
│   ├── _reload.py         # Hot-reload: rebuild tool registry and system prompt after skill changes
│   ├── _model_switch.py   # LLM tier switching + shared extra_body builder; preflight rejects a switch when
│   │                       #   history has dagi_image parts and the target tier's supports_images is False (image input, stage 3)
│   ├── _streaming.py      # Streaming chat-completions consumer
│   ├── _compaction.py     # Context compaction via forked compact subagent; materializes dagi_image parts in the
│   │                       #   reconstructed fork prefix before building the fork snapshot (image input, stage 3)
│   ├── _tool_dispatch.py  # Tool-call dispatch, bookkeeping, write_handoff deferral (runs last in batch), pause gating, malformed-args sanitisation + surface cache reproject
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
│   ├── read/               # read.py's replacement — text inline; .pdf/.docx/.xlsx/.pptx via
│   │   │                   #   the doc-converter service (see services/doc_converter/ below)
│   │   ├── _read.py        #   ReadTool
│   │   ├── _doc_service.py #   HTTP client (anti-corruption layer) to the doc-converter service
│   │   └── _document_reader.py # long-document summarizer orchestration
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
│   ├── subagent_api.py    # Public API — run_subagent() / SubagentResult / resume_subagent_by_pid()
│   ├── _subagent_runner.py # Private runner — Popen(stdout=PIPE), JSON event relay, PID polling, fault-isolated stdout drain; only called by subagent_api.py
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
│   └── doc_converter/      # Standalone FastAPI microservice: PDF/docx/xlsx/pptx → markdown.
│       │                   #   Own conda env (environment.yml) — heavy deps (docling, torch,
│       │                   #   pymupdf, ocrmypdf, markitdown) live only here, not in dagi core.
│       │                   #   Start with: python -m services.doc_converter (port 8100)
│       ├── main.py         #   FastAPI app, POST /convert endpoint
│       └── converter/
│           ├── pdf.py      #   PDF→markdown (docling digital / ocrmypdf+docling scanned, parallel path)
│           ├── office.py   #   docx/xlsx/pptx→markdown via markitdown
│           └── cache.py    #   Server-side content-addressed cache (.cache/<sha256>.md)
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
│   ├── read-large-text/ # large-text-file summarizer, directly LLM-callable as `read_large_text` (tools: read, grep, write)
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
| `read` | Read a text file (paginated) inline. `.pdf`/`.docx`/`.xlsx`/`.pptx` are delegated to the standalone **doc-converter service** over HTTP (see [Document Conversion Service](#document-conversion-service) below) — the service must be running or `read` returns a clear error telling you to start it, no inline fallback. PDF output includes a `[PDF: name \| N pages]` header; `pages` (PDF only, e.g. `'1-5'`) filters by `<!-- Page N -->` markers. Pass `path`, optional `offset`/`limit`, optional `pages` |
| `read_large_text` | Directly LLM-callable tool (`.dagi/subagents/read-large-text/`) that reads and digests a large text file, returning a sectioned summary with key excerpts, line ranges, and token estimates. Use when a file is too long to fit in context or requires structured summarization. Pass `task` (file path + what to extract), optional `custom_instructions` |
| `write` | Overwrite a file. Creates parent dirs. Takes `path` + `content` |
| `edit` | Edit a file by replacing exact text (`oldText` → `newText`). The match must be unique; CRLF-safe |
| `bash` | Run a shell command. Returns stdout + stderr + exit code. Pass `command` + optional `timeout` |
| `grep` | Regex search across files using ripgrep (rg). Returns `file:line:match` format. Automatically excludes binary files (`.pyc`, `.pyo`, `.bin`), `__pycache__`, `.git`, `.dagi`, and other non-source directories. `path` must be a specific subdirectory or file (not `.` / project root) |
| `find` | Find files by glob pattern (e.g. `**/*.py`). Searches all allowed roots when no path given |
| `skill` | Load a `.dagi/skills/<name>/SKILL.md` guidance document and return it for execution |
| `web_search` | DuckDuckGo web search. Returns titles, URLs, and snippets |
| `web_fetch` | Fetch and parse a URL. Returns cleaned page text |
| `web_research` | Multi-page research task: searches, fetches, and synthesizes results. Runs as a pipe subagent; output streams to the main TUI with a `[web_research]` label |
| `explore_files` | Large-scale codebase scan: explores with broad-to-narrow strategy (glob/grep first, targeted reads second) and returns a citation-first handoff (`path:line_start-line_end` entries). Runs as a pipe subagent; output streams to the main TUI with an `[explore_files]` label |
| `extend_subagent_timeout` | Extend the deadline of an in-flight subagent by PID. Called by the agent when `spawn_*` returns a timeout dict |
| `compact` | Manually trigger Pi-style context compaction |
| `switch_model` | Swap to a different model (from the model catalog) mid-session |
| `read_notepad` | Read-only: return the user's global pet-notepad markdown (`.dagi/notepad/notepad.md`, LaTeX math kept as source) with a last-edited/char-count header; truncated at 20k chars. Always registered (GUI, TUI, Telegram); in the GUI it first flushes unsaved editor text (≤2 s wait). No parameters |
| `show_file` | Open a file in the PySide GUI's file viewer for the user, optionally jumping to and highlighting a specific line number. No-op in TUI/Telegram |
| `ask_user` | Pause and ask the user a clarifying question with optional choices. Acts as a turn-ender — the agent should call `ask_user` instead of `write_handoff` when it needs the user to answer a question before continuing |
| `show_plan` | Render the current plan document and ask the user for revisions. Returns "Plan approved" (call `set_active_plan`) or "Modifications requested" (revise and call `show_plan` again). In autonomous mode, auto-approves immediately |
| `escalate_issue` | Worker/review subagent only: raise a blocking question to the main agent instead of guessing. Writes a sidecar file next to the subagent's handoff report; the main agent's subprocess poll loop detects it, terminates the subagent, and surfaces `"[worker escalated]"` / `"[review escalated]"` with the question and context — does not consume a `dagi-execute` retry attempt |
| `write_handoff` | Always visible to the main agent and auto-injected into every subagent with a `handoff_path`. It writes `content` verbatim to a baked-in path and its sentinel immediately ends the turn, so no `END_OF_RESPONSE` is needed. Main-agent calls save `.dagi/handoffs/main_<thread-hash12>.md` and render the full Markdown in the TUI; inherited children reuse the exact parent-visible schema but write to their assigned child path. The lifecycle name is reserved against project-tool collisions. |

File tools (`read`, `write`, `edit`, `grep`, `find`) are sandboxed to allowed roots via `tools/_path_guard.py`. `bash` is intentionally unsandboxed.

Every subagent spawn tool (worker, review, explore_files, web_research, or any type discovered from `.dagi/subagents/`) reads the subagent's handoff file and inlines its full content directly into the tool's own result on success (via `tools/_handoff_format.py::format_handoff_result()`) — the main agent never has to make a separate `read` call to see what a subagent produced. `extend_subagent_timeout`'s resume path does the same. Large handoffs are still subject to the normal output-filter truncation like any other tool result.

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

See `docs/superpowers/specs/2026-07-06-dagi-eval-benchmark-design.md` for
the full design rationale and `docs/superpowers/plans/2026-07-06-dagi-eval-benchmark.md`
for the implementation plan.

---

## Dependencies

Direct application dependencies are declared in `pyproject.toml`. The requirements files separately preserve the original environment's exact package pins by feature (see [Setup](#setup)).

`environment.yml` creates the same core environment as `requirements-core.txt`.
Neither is a fully pinned lockfile. Add UI/tool groups explicitly; see [Setup](#setup).

| Group | Direct dependencies / purpose |
|---|---|
| Core | openai, pyyaml, python-dotenv, rich, httpx |
| `tui` | textual, typer |
| `gui` | TUI helpers, pyside6, markdown-it-py, pygments |
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
