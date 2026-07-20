# Driverless AGI

A minimal, self-hosted coding agent. Give it a task — it plans, calls tools, reads results, and iterates until done. Ships with a Rich interactive CLI. Supports any OpenAI-compatible API, automatic context compaction for long sessions, extended reasoning, skills-based guidance, and full session logging with cost tracking.

---

## How It Works

```
Plan → Act → Observe → Repeat
```

1. **Plan** — The model decides the next step based on the task and prior results
2. **Act** — It calls a tool (`read`, `write`, `edit`, `bash`, `grep`, …)
3. **Observe** — It reads the tool's output
4. **Repeat** — Until the task is complete or `max_iterations` is hit

When the conversation exceeds the model's context window, **Pi-style context compaction** kicks in — the middle of the history is summarized and replaced, preserving the system prompt and recent messages. This lets the agent handle arbitrarily long tasks without crashing.

Every agent response with no tool calls must end with `<<END_OF_RESPONSE>>` — this applies to greetings, answers, and completed tasks alike. If the flag is absent, the harness treats the response as accidentally truncated and injects a recovery prompt (`.dagi/prompts/main/continue.md`) as a user message to resume the loop. A safety valve (`max_continuations`, default 10, configurable in `config.yaml`) prevents runaway recovery loops. `<<TASK_END>>` is kept as a silent legacy alias.

At session start, **wiki index injection** automatically reads the root and section `.index.md` files from the memory wiki and prepends them as a system message before the first API call — giving the agent a structural map of accumulated knowledge without any manual invocation. The agent then uses `spawn_memory_query_subagent` for targeted retrieval and `spawn_memory_add_subagent` to persist new knowledge after each task.

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

**conda:**
```bash
conda activate dagi
pip install -r requirements.txt
```

**venv:**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

### Troubleshooting

**OpenAI credentials errors** — if you see authentication failures on startup, confirm your `.env` file exists at the repo root and contains the correct key. Also ensure `langchain` is installed:

```bash
pip install langchain
```

**Authorization / proxy errors** — if API requests are blocked by a corporate proxy or firewall, add the API base URL to the `no_proxy` environment variable so requests bypass the proxy:

```bash
# Windows (PowerShell)
$env:no_proxy = "openai.com,openrouter.ai,api.openai.com"

# macOS / Linux
export no_proxy="openai.com,openrouter.ai,api.openai.com"
```

**PDF reading / "DLL load failed" errors** — docling's dependencies (torch, onnxruntime, rapidocr) are imported lazily, so a broken install only surfaces the first time you read a PDF. Verify them right after installing:

```bash
python scripts/verify_pdf_env.py
```

On Windows, a DLL load failure from torch or onnxruntime almost always means the [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe) is missing — install it and re-run the check.

**Local docling models** — if `models/docling_models/` (TableFormer + heron layout weights) is present, PDF conversion loads them from disk instead of downloading from Hugging Face on every call. Falls back to the default HF download if the directory is missing.

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
| `--model` | Model ID from `config.yaml` |
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
| `--model` / `-m` | Model ID from `config.yaml` |
| `--verbose` / `-v` | Show full tool input/output |
| `--project` / `-p` | Project directory |

**Keyboard shortcuts:**
- `Enter` — submit the input box contents as a task (single or multi-line)
- `Shift+Enter` / `Ctrl+N` / `Ctrl+Enter` — insert a newline in the input box for multi-line messages (`Ctrl+N` and `Ctrl+Enter` are reliable alternatives on Windows Terminal, which sends identical bytes for `Shift+Enter` and `Enter`)
- `Ctrl+O` — toggle compose mode: hides the conversation pane and expands the input box to fill the screen, giving a distraction-free writing area for long multi-line messages. Press `Ctrl+O` again to restore normal layout, or just press `Enter` to submit (auto-collapses on submit).
- `Esc` — pause the running agent. If a `bash` command is currently running (in the main loop or inside an active worker/review subagent), it is force-killed immediately; otherwise the agent pauses at the end of the current iteration (after all tool calls in the current LLM response complete). Status changes to `⏸ Paused`. Type any message and press Enter to inject it into the agent's context and resume. ESC has no effect when idle or during an `ask_user` prompt.
- `Ctrl-C` — quit the TUI entirely

**Header panels (left → center → right):**
- **Status** (left) — emote face (named emotes from `.dagi/emotes/` or custom text/kaomoji) · `● Running` / `⏸ Paused` / `○ Idle` · active model name
- **Tokens + Context** (center) — cumulative `in / think / out / cost`; condensed context breakdown (sys / msgs / reserve / total) with colour warnings at 80%/95% usage
- **Plan** (right) — subtask list polled every 2 s; shown only when a plan is active. Icons: `[ ]` pending · `[~]` in-progress (amber) · `[x]` complete (green) · `[!]` failed (red)

**Slash commands:** `/help`, `/exit`, `/clear`, `/wd`, `/compact`, `/model <id>`, `/plan`, `/tools`, `/skills`, `/workflows`, `/hist`, `/init`

Exit with `/exit`, `exit`, `quit`, or `Ctrl-C`. Conversation history carries across turns.

### Interactive CLI (`archives/cli.py`) [DEPRECATED]

The legacy CLI REPL has been **archived** in favour of the TUI (`python tui.py`).
It remains available at `archives/cli.py` for reference only — nothing in the live
codebase imports or executes it. The piped subagent binary (used by
`tools/_subagent_runner.py` for explore_files, web_research, memory-query, etc.) is
`tools/subagent_main.py`, extracted from the old CLI's pipe-mode path and run as
`python -m tools.subagent_main` (so the project root, not `tools/`, is on `sys.path[0]` —
running it by file path instead would let `tools/copy.py` shadow the stdlib `copy` module).

```bash
conda run --no-capture-output -n dagi python archives/cli.py
conda run --no-capture-output -n dagi python tui.py   # preferred
```

### Telegram Bot (`telegram_bot.py`)

Chat with DAGI from your phone via Telegram. Requires a bot token from [@BotFather](https://t.me/BotFather).

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
| `--model` / `-m` | Model ID from `config.yaml` |
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
- `.dagi/agents.md` — behavioral guidelines injected into every session
- `.dagi/skills/` — directory for project-specific skills
- `.dagi/workflow/` — directory for project-specific workflows
- `dagi-memory/raw/` — drop source material here for the wiki
- `dagi-memory/wiki/` — structured wiki pages (populated by the `memory-ingest` skill)

You only need to run `/init` once per project. It is safe to re-run — existing files are skipped.

**3. Seed the memory wiki (optional but recommended)**

Drop any relevant documents — architecture notes, API references, prior session summaries — into `dagi-memory/raw/`. Then ask dagi to ingest them:

```
Invoke the memory-ingest skill.
```

At the start of every subsequent session, BM25 retrieval automatically surfaces the most relevant wiki pages as context before the first API call.

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

**Scope the task to one concern at a time.** If you have a large feature, use plan mode (see below) to break it into subtasks first — then implement each subtask individually.

**Give context the agent can't see.** If there's a known constraint, a related PR, or a quirk of the codebase, include it:

```
"The DB client is not thread-safe; all calls must go through the connection pool
in db/pool.py. Refactor the user service to use it."
```

---

### Plan Mode

For complex multi-step tasks, invoke plan mode before implementation. The agent explores the codebase in read-only mode, writes a structured plan with subtasks, asks you to approve it, and then begins implementation.

```
/plan
```

Or ask naturally:

```
"Plan a refactor of the authentication module to use JWT instead of sessions."
```

**How it works:**

1. The agent explores relevant files (read-only — no writes except to the plan document)
2. It writes a plan with numbered subtasks, each marked `[ ]` pending
3. It calls `show_plan` and asks you for revisions
4. You respond with changes or say "looks good"
5. On approval, it calls `exit_plan_mode` and begins implementation
6. The **Plan** panel in the TUI header tracks subtask status in real time:
   `[ ]` pending · `[~]` in-progress · `[x]` complete · `[!]` failed

The plan document is saved to `.dagi/plans/` and referenced throughout the implementation.

---

### Slash Command Reference

All slash commands work identically in the TUI and CLI.

| Command | Description |
|---------|-------------|
| `/help` | Show the command list |
| `/exit` | Exit dagi |
| `/clear` | Clear conversation context and reset the session |
| `/wd [path]` | Show the current working directory, or change it to `path` |
| `/model [id]` | List available models, or switch to `id` immediately |
| `/plan` | Enter plan mode — agent explores and writes a structured plan |
| `/compact` | Force-compact the current conversation context |
| `/tools` | List all registered tools for the active session |
| `/skills` | List all loaded skills |
| `/workflows` | List all loaded workflows |
| `/hist [n]` | Show the `n` most recent session summaries (default 20) |
| `/init` | Scaffold `.dagi/` and `dagi-memory/` directories for the current project |
| `/<skill-name>` | Invoke any loaded skill directly (e.g. `/memory-query`) |
| `/<workflow-name>` | Run any loaded workflow (e.g. `/improve-yourself`) |

---

### Pausing and Resuming (TUI only)

Press `Esc` at any time while the agent is running to pause it. If a `bash` command is currently running — in the main loop, or inside an active worker/review subagent — it is force-killed immediately (surfaced as `[killed by user]` in the conversation, or as a tool error for the subagent call). Otherwise, the agent pauses at the end of the current iteration (after all tool calls in the current LLM response complete). The status indicator switches to `⏸ Paused`.

Type any message and press `Enter` to inject it into the agent's context and resume — this is equivalent to the agent asking you a question and you answering it. The agent receives your message and continues from where it stopped, with full context intact.

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
| `memory-add` | Add a structured note to the persistent wiki |
| `memory-ingest` | Bulk-ingest raw documents into the wiki |
| `memory-query` | Look up information in the wiki |
| `memory-lint` | Validate wiki structure and internal links |
| `create-skill` | Scaffold a new skill document |
| `review-session` | Analyse sessions described in free text (folder, files, time window) into one running cross-session review report |
| `grilling` | Adversarial interrogation of a plan or idea before implementation; chains to `plan` |
| `to-spec` | Synthesize the current conversation into a written spec (`spec.md`); invoked by `plan`, not user-triggered |
| `plan` | Orchestrate the planning lifecycle: spec synthesis, codebase exploration, plan-file authoring, and user approval; chains to `dagi-execute` |
| `dagi-execute` | Execute an approved plan subtask by subtask via the worker/review subagent cycle, with retry and escalation handling |
| `update-project-context` | Update `AGENTS.md` with current project state |

Add a project-specific skill by creating `.dagi/skills/<name>/SKILL.md` in your project directory.

---

### Managing Context in Long Sessions

Dagi uses **Pi-style context compaction** to handle tasks that exceed the model's context window. When the conversation approaches the token limit, the middle of the history is summarized and replaced — the system prompt and recent messages are always preserved verbatim.

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
- **Use plan mode for anything non-trivial.** It prevents the agent from making opinionated implementation choices before you've agreed on the approach.
- **Build the memory wiki over time.** The more domain knowledge in `dagi-memory/wiki/`, the less you need to re-explain project context each session.
- **Pause instead of cancelling.** `Esc` in the TUI preserves the agent's full context; you can inject corrections and resume rather than restarting from scratch.
- **Review sessions with `/hist`.** Session summaries in `.dagi/logs/` capture token counts, cost, and what the agent did. The `review-session` skill accepts a free-text description of which sessions to look at and accumulates findings from all of them into one report, so patterns that recur across sessions surface as a single insight.
- **Add a `.dagi/agents.md` to your project.** This file is injected into every session for that project. Use it to encode coding standards, architecture invariants, and anything you would otherwise repeat in every task prompt.

---

## Configuration

`config.yaml` controls runtime behavior. Copy `config.example.yaml` to get started.

```yaml
default_model: gpt-4o-openai        # used if --model isn't passed
max_iterations: 20                   # hard cap on loop iterations
max_continuations: 10                # max "continue" injections before giving up
api_error_retries: 3                 # retries for transient API errors (429/5xx/connection)
cache_prompt: true                   # send cache_prompt: true in extra_body (OpenRouter prompt caching)

models:
  gpt-4o-openai:
    name: "GPT-4o (OpenAI)"          # display name
    model: "gpt-4o"                  # model ID sent to API
    api_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"    # env var holding the key

  claude-opus-openrouter:
    name: "Claude Opus 4.6 (OpenRouter)"
    model: "anthropic/claude-opus-4-6"
    api_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
```

### Per-Model Overrides

Any model entry can override compaction thresholds (defaults shown):

```yaml
  my-model:
    model: "provider/model-id"
    api_url: "https://..."
    api_key_env: "MY_API_KEY"
    context_window: 128000       # model's hard token limit
    reserve_tokens: 16384        # headroom for next reply
    keep_recent_tokens: 20000    # recent tail kept verbatim
```

### Thinking / Reasoning

Models that support extended thinking (e.g. Qwen3, DeepSeek-R1) can be configured with the `thinking` key. Values: `none` (default), `low`, `medium`, `high`.

Set it globally:

```yaml
thinking: high
```

Or per-model (overrides the global setting):

```yaml
models:
  qwen3-30b-openrouter:
    model: "qwen/qwen3-30b-a3b"
    api_url: "https://openrouter.ai/api/v1"
    api_key_env: "OPENROUTER_API_KEY"
    thinking: high      # only this model reasons; others stay at the global value
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
models:
  some-model:
    stream: false   # this model waits for the full response, like before streaming existed
```

Token/cost usage is requested via `stream_options: {"include_usage": true}` on every streaming call; if a provider never sends the trailing usage chunk, that turn's usage is simply unavailable (the same degraded state that already exists today for providers that omit `usage.cost`) rather than an error. `main.py`, `telegram_bot.py`, and the scheduler are unaffected by this setting — streaming only changes how the TUI renders a turn in progress, not the final result.

While a response is actively streaming, the live preview automatically expands to fill the full window (down to the running-indicator/prompt), so long in-progress replies aren't capped at a few lines — it collapses back to normal once the turn finishes and the final message lands in the conversation pane.

### PDF Conversion

PDFs longer than 8 pages are converted in parallel (map-reduce: split into chunks, one docling model load per worker process, then merged and renumbered). Worker count is estimated automatically from CPU count, page count, and free RAM, and is optional to tune via a `pdf:` key in `config.yaml`:

```yaml
pdf:
  worker_ram_gb: 4.0    # RAM budget assumed per worker process (default 4.0)
  max_workers: null     # hard cap on worker processes (default null = uncapped)
```

Both keys are optional — omit the `pdf:` block entirely to use the defaults. Shorter PDFs (8 pages or fewer) always use the original single-process pipeline.

---

## Architecture

```
Driverless_AGI/
├── main.py                # Single-shot CLI (argparse)
├── archives/              # Deprecated, unused — reference only
│   └── cli.py             #   Old interactive CLI REPL (typer + rich)
├── config.yaml            # Runtime config (gitignored)
├── config.example.yaml    # Config template
├── .env                   # API keys (gitignored)
├── SOUL.md                # Agent personality
├── AGENTS.md              # Project context prepended to system prompt
│
├── agent/
│   ├── base_tool.py       # BaseTool ABC
│   ├── registry.py        # ToolRegistry singleton
│   ├── tools.py           # Builds and returns the tool registry
│   ├── loop.py            # AgentLoop, AgentConfig, AgentCallbacks
│   ├── config_loader.py   # Resolves model config from YAML
│   ├── memory_retriever.py # BM25 wiki retrieval — auto-injects context at session start
│   ├── session.py         # SessionTracker — JSONL logs
│   ├── prompts.py         # Loads system/user prompts from .dagi/prompts/ and .dagi/subagents/
│   ├── skills.py          # SkillLoader — loads .dagi/skills/
│   ├── workflows.py       # WorkflowLoader — loads .dagi/workflow/
│   ├── sub_agent.py       # SubAgentRunner — legacy in-process subagent (used by cli_subagent)
│   ├── cli_utils.py       # Shared TUI helpers (_cmd_init, _skill_invocation_message) — extracted from archives/cli.py
│   └── _git_branch.py     # Plan-mode auto-branching — creates/checks out dagi/<slug>_<plan_id> from HEAD
│
├── tools/
│   ├── read.py            # Read files (text + image)
│   ├── write.py           # Write / overwrite files
│   ├── edit.py            # Exact-text replacement
│   ├── bash.py            # Run shell commands
│   ├── git.py             # git_status, git_diff, git_log, git_branch, git_checkout, git_add, git_commit, git_reset
│   │                       #   (git_add/git_commit/git_reset are whitelist-guarded to dagi/* branches only;
│   │                       #   git_commit requires explicit git_add staging first — no implicit add -A;
│   │                       #   entering plan mode auto-creates/checks out a dagi/<slug>_<plan_id> branch)
│   ├── grep.py            # Regex search across files (ripgrep)
│   ├── find.py            # Glob-pattern file finder
│   ├── skill.py           # Load a .dagi/skills/ guidance document
│   ├── workflow.py        # Workflow content loader and lister (CLI helpers)
│   ├── web_search.py      # DuckDuckGo web search
│   ├── web_fetch.py       # Fetch and parse a URL
│   ├── web_research.py    # Multi-page web research (spawns pipe subagent)
│   ├── explore_files.py   # Large-scale codebase scanning (spawns pipe subagent)
│   ├── _subagent_runner.py # Core runner — Popen(stdout=PIPE), JSON event relay, PID polling
│   ├── subagent_main.py   # Piped subagent entry point (spawned via `python -m tools.subagent_main`)
│   ├── extend_timeout.py  # ExtendSubagentTimeoutTool — resume in-flight subagent deadline
│   ├── cli_subagent.py    # Custom subagent with caller-supplied system prompt
│   ├── compact.py         # Trigger context compaction
│   ├── plan_mode.py       # Enter / exit read-only plan mode
│   ├── switch_model.py    # Swap models mid-session
│   ├── ask_user.py        # Prompt user for clarification
│   ├── escalate_issue.py  # Worker/review subagents: sidecar-file escalation to the main agent
│   └── _path_guard.py     # Path sandboxing utilities
│
├── .dagi/
│   ├── prompts/           # Prompt markdown files, organized by role
│   │   ├── main/          #   main_system.md — primary coding assistant prompt
│   │   └── compact/       #   compact_system, compact_user (Pi-style summariser)
│   ├── subagents/         # Per-subagent: <name>/prompt.md + subagent_config.yaml
│   │   ├── document-reader/ # long-document summarizer (tools: read, grep, write)
│   │   ├── explore_files/ #   exploration agent (tools: read, grep, find)
│   │   ├── web_research/  #   web research agent (tools: web_search, web_fetch)
│   │   ├── worker/        #   full-tool worker agent
│   │   ├── review/        #   code review agent (tools: read, grep, find, bash)
│   │   └── plan/          #   plan-writing agent prompt
│   ├── handoffs/          # Generated handoff files: <type>_<uuid8>.md (content is inlined into the spawn_* tool's result automatically — see Tools table)
│   ├── skills/            # Structured guidance documents (gnhf, memory-*, create-skill, review-session, …)
│   ├── workflow/          # User-directed workflows (.dagi/workflow/<name>/workflow.md)
│   ├── memory/wiki/       # Topic-organized persistent wiki (infrastructure built)
│   ├── tools/             # Project-local tools (auto-loaded at startup)
│   ├── gnhf/              # GNHF session artifacts (notes.md — committed to dagi branch)
│   ├── plans/             # Generated plan files
│   ├── logs/              # Session JSONL files
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
| `read` | Read a text file (paginated), `.docx`/`.xlsx`/`.pptx` (markdown via `markitdown`), `.pdf` (markdown via `docling` with table detection; scanned PDFs OCR'd via `ocrmypdf`; results cached in `.dagi/hash_cache/pdf/`). PDFs longer than 8 pages are converted in parallel across multiple worker processes (map-reduce: split into page-range chunks, one docling load per worker, merge + renumber markers) for speed — worker count is capped by CPU count, page count, free RAM, and the `pdf.worker_ram_gb`/`pdf.max_workers` keys in `config.yaml`; shorter PDFs use the original single-process path unchanged. For documents exceeding the model's `reserve_tokens` budget, automatically spawns a `document-reader` subagent that produces a sectioned summary digest (per-section line ranges, token estimates, summaries, key excerpts) cached in `.dagi/hash_cache/document_summary/` — the parent receives the digest instead of truncated output and can drill into sections of interest with targeted `offset`/`limit` reads. Pass `path`, optional `offset`/`limit`, optional `pages` (PDF only, e.g. `'1-5'`) |
| `write` | Overwrite a file. Creates parent dirs. Takes `path` + `content` |
| `edit` | Replace exact `oldText` with `newText` in a file. Errors if text is absent or non-unique |
| `bash` | Run a shell command. Returns stdout + stderr + exit code. Pass `command` + optional `timeout` |
| `grep` | Regex search across files. Returns `file:line:match` format. Uses ripgrep when available |
| `find` | Find files by glob pattern (e.g. `**/*.py`). Searches all allowed roots when no path given |
| `skill` | Load a `.dagi/skills/<name>/SKILL.md` guidance document and return it for execution |
| `web_search` | DuckDuckGo web search. Returns titles, URLs, and snippets |
| `web_fetch` | Fetch and parse a URL. Returns cleaned page text |
| `web_research` | Multi-page research task: searches, fetches, and synthesizes results. Runs as a pipe subagent; output streams to the main TUI with a `[web_research]` label |
| `explore_files` | Large-scale codebase scan: explores with broad-to-narrow strategy (glob/grep first, targeted reads second) and returns a citation-first handoff (`path:line_start-line_end` entries). Runs as a pipe subagent; output streams to the main TUI with an `[explore_files]` label |
| `extend_subagent_timeout` | Extend the deadline of an in-flight subagent by PID. Called by the agent when `spawn_*` returns a timeout dict |
| `compact` | Manually trigger Pi-style context compaction |
| `switch_model` | Swap to a different model (from `config.yaml`) mid-session |
| `ask_user` | Pause and ask the user a clarifying question with optional choices |
| `show_plan` | In plan mode: render the current plan document and ask the user for revisions. Returns "Plan approved" (call `exit_plan_mode`) or "Modifications requested" (revise and call `show_plan` again). In autonomous mode, auto-approves immediately |
| `escalate_issue` | Worker/review subagent only: raise a blocking question to the main agent instead of guessing. Writes a sidecar file next to the subagent's handoff report; the main agent's subprocess poll loop detects it, terminates the subagent, and surfaces `"[worker escalated]"` / `"[review escalated]"` with the question and context — does not consume a `dagi-execute` retry attempt |

File tools (`read`, `write`, `edit`, `grep`, `find`) are sandboxed to allowed roots via `tools/_path_guard.py`. `bash` is intentionally unsandboxed.

Every `spawn_<type>_subagent` tool (worker, review, explore_files, web_research, or any custom type discovered from `.dagi/subagents/`) reads the subagent's handoff file and inlines its full content directly into the tool's own result on success (`tools/spawn_subagent.py::SpawnSubagentTool._format_ok_result()`) — the main agent never has to make a separate `read` call to see what a subagent produced. `extend_subagent_timeout`'s resume path does the same. Large handoffs are still subject to the normal output-filter truncation like any other tool result.

### Adding a Custom Tool

**Option A — core tool:** Add a file in `tools/` and register it in `agent/tools.py`:

```python
# tools/my_tool.py
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

Then import and register in `agent/tools.py`.

**Option B — project-local tool:** Drop a `.py` file into `.dagi/tools/`. It will be auto-discovered and registered at startup — no changes to core files needed.

---

## Skills

Skills are structured guidance documents stored at `.dagi/skills/<name>/SKILL.md`. When the agent calls `skill("memory-add")`, it loads and reads the full document, which contains step-by-step instructions and embedded scripts the agent then follows.

Built-in skills:

| Skill | What it does |
|-------|-------------|
| `memory-add` | Add a structured note to the wiki |
| `memory-ingest` | Bulk-ingest source material into the wiki |
| `memory-query` | Look up information in the wiki |
| `memory-lint` | Validate wiki structure and wikilinks |
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

Core (from `pyproject.toml`):

- `openai` — API client (any OpenAI-compatible endpoint)
- `pyyaml` — config parsing
- `python-dotenv` — `.env` loading
- `ddgs` — DuckDuckGo web search
- `httpx` + `beautifulsoup4` — web fetching and HTML parsing
- `crawl4ai` — web crawling for research tasks
- `markdown` — markdown rendering
- `matplotlib` — data visualization
- `nicegui` — retained for archived web UI; not needed for CLI use
- `psutil` — free-RAM probing for PDF parallel-conversion worker-count estimation (`tools/_pdf_convert.py::_estimate_worker_count`)

Additional (install separately if using the interactive CLI):

- `typer` + `rich` — interactive CLI (`archives/cli.py`)
- No extra native libraries required — subagents use stdlib `subprocess` with stdout pipe

### Windows notifications (TUI, optional)

- `win11toast` — native Windows 10/11 toast notifications, installed by default via `requirements.txt`. `tui.py` fires a toast (`tui/notifications.py::notify()`) when DAGI asks a question, presents a plan for interactive review, or reaches end-of-response. The toast is skipped when the TUI's own console window already has OS focus (`_tui_window_is_foreground()`), so you're only notified when you've alt-tabbed away; if that focus check itself fails, it fails open and still notifies. Lazily imported and exception-guarded — degrades silently to a no-op on non-Windows hosts or if the package is missing, never blocking the TUI. Not used by `cli.py`, `telegram_bot.py`, subagents, or the scheduler. Independent of the toast, every end-of-response also writes a `— turn complete —` marker directly into the conversation pane (`tui/callbacks.py::on_done`) — this stays visible even when the toast is suppressed (window focused) or the model's final response text was empty, so a normal turn ending is never mistaken for a stalled agent.
