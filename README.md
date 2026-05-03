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

Install:

```bash
pip install -e .
```

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

### Interactive CLI (`cli.py`)

Multi-turn REPL with Rich rendering, live spinners, and tool call panels. Uses typer.

```bash
python cli.py                          # start REPL
python cli.py "one-shot task"          # single task then REPL
python cli.py -m claude-opus-openrouter -v "task"
```

| Flag | Description |
|------|-------------|
| `--model` / `-m` | Model ID from `config.yaml` |
| `--verbose` / `-v` | Show full tool input/output |
| `--sync` | Disable threaded mode (no spinner) |

Exit with `q`, `exit`, or `quit`. Conversation history carries across turns.

> **Archived UIs:** `archive/app.py` (Streamlit) and `archive/nicegui_app/` (NiceGUI) are no longer maintained.

---

## Configuration

`config.yaml` controls runtime behavior. Copy `config.example.yaml` to get started.

```yaml
default_model: gpt-4o-openai        # used if --model isn't passed
max_iterations: 20                   # hard cap on loop iterations

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

---

## Architecture

```
Driverless_AGI/
├── main.py                # Single-shot CLI (argparse)
├── cli.py                 # Interactive CLI / REPL (typer + rich)
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
│   ├── session.py         # SessionTracker — JSONL logs
│   ├── prompts.py         # Loads system/user prompts from .dagi/prompts/
│   ├── skills.py          # SkillLoader — loads .dagi/skills/
│   ├── workflows.py       # WorkflowLoader — loads .dagi/workflow/
│   └── sub_agent.py       # Spawns independent sub-agent loops
│
├── tools/
│   ├── read.py            # Read files (text + image)
│   ├── write.py           # Write / overwrite files
│   ├── edit.py            # Exact-text replacement
│   ├── bash.py            # Run shell commands
│   ├── grep.py            # Regex search across files (ripgrep)
│   ├── find.py            # Glob-pattern file finder
│   ├── skill.py           # Load a .dagi/skills/ guidance document
│   ├── workflow.py        # Workflow content loader and lister (CLI helpers)
│   ├── web_search.py      # DuckDuckGo web search
│   ├── web_fetch.py       # Fetch and parse a URL
│   ├── web_research.py    # Multi-page web research
│   ├── explore_files.py   # Large-scale codebase scanning
│   ├── compact.py         # Trigger context compaction
│   ├── plan_mode.py       # Enter / exit read-only plan mode
│   ├── switch_model.py    # Swap models mid-session
│   ├── ask_user.py        # Prompt user for clarification
│   └── _path_guard.py     # Path sandboxing utilities
│
├── .dagi/
│   ├── prompts/           # Prompt markdown files, organized by role
│   │   ├── main/          #   main_system.md — primary coding assistant prompt
│   │   ├── subagents/     #   plan_subagent, explore_files, web_research
│   │   └── compact/       #   compact_system, compact_user (Pi-style summariser)
│   ├── skills/            # Structured guidance documents (memory-*, create-skill, review-session, …)
│   ├── workflow/          # User-directed workflows (.dagi/workflow/<name>/workflow.md)
│   ├── memory/wiki/       # Topic-organized persistent wiki (infrastructure built)
│   ├── tools/             # Project-local tools (auto-loaded at startup)
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
| `read` | Read a text file (paginated) or image (base64). Pass `path`, optional `offset`/`limit` |
| `write` | Overwrite a file. Creates parent dirs. Takes `path` + `content` |
| `edit` | Replace exact `oldText` with `newText` in a file. Errors if text is absent or non-unique |
| `bash` | Run a shell command. Returns stdout + stderr + exit code. Pass `command` + optional `timeout` |
| `grep` | Regex search across files. Returns `file:line:match` format. Uses ripgrep when available |
| `find` | Find files by glob pattern (e.g. `**/*.py`). Searches all allowed roots when no path given |
| `skill` | Load a `.dagi/skills/<name>/SKILL.md` guidance document and return it for execution |
| `web_search` | DuckDuckGo web search. Returns titles, URLs, and snippets |
| `web_fetch` | Fetch and parse a URL. Returns cleaned page text |
| `web_research` | Multi-page research task: searches, fetches, and synthesizes results |
| `explore_files` | Large-scale codebase scan: reads many files and returns a structured summary |
| `compact` | Manually trigger Pi-style context compaction |
| `switch_model` | Swap to a different model (from `config.yaml`) mid-session |
| `ask_user` | Pause and ask the user a clarifying question with optional choices |

File tools (`read`, `write`, `edit`, `grep`, `find`) are sandboxed to allowed roots via `tools/_path_guard.py`. `bash` is intentionally unsandboxed.

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
| `review-session` | Deep-read session logs, analyse tasks/actions/errors/corrections, and write structured review reports to `.dagi/self-review/` |

Add a custom skill by creating `.dagi/skills/<name>/SKILL.md`.

---

## Workflows

Workflows are user-directed multi-step procedures stored at `.dagi/workflow/<name>/workflow.md`
with optional YAML frontmatter (`name`, `description`). Unlike skills, they are **not injected
into the system prompt** and are not autonomously discoverable by the agent — they are invoked
only when the user types a slash command in the interactive CLI.

**Discovery and invocation (in `cli.py`):**
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

Additional (install separately if using the interactive CLI):

- `typer` + `rich` — interactive CLI (`cli.py`)
