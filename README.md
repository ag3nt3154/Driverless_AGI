# Driverless AGI

A minimal, self-hosted coding agent. Give it a task — it plans, calls tools, reads results, and iterates until done. Ships with a Rich interactive CLI, a Streamlit web UI, and a NiceGUI web UI. Supports any OpenAI-compatible API, automatic context compaction for long sessions, and full session logging with cost tracking.

---

## How It Works

```
Plan → Act → Observe → Repeat
```

1. **Plan** — The model decides the next step based on the task and prior results
2. **Act** — It calls a tool (`read`, `write`, `edit`, or `bash`)
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

### Web UI — Streamlit (`app.py`)

```bash
streamlit run app.py
```

Full-featured chat interface with model selector, live tool cards, session history, cost tracking, and an API debug panel.

### Web UI — NiceGUI (`nicegui_app/`)

```bash
python -m nicegui_app.main
```

Alternative web interface with the same feature set: model/iteration controls, collapsible tool cards, session history with continuation, iteration progress bar, and export.

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

---

## Architecture

```
Driverless_AGI/
├── main.py                # Single-shot CLI (argparse)
├── cli.py                 # Interactive CLI / REPL (typer + rich)
├── app.py                 # Streamlit web UI
├── config.yaml            # Runtime config (gitignored)
├── config.example.yaml    # Config template
├── .env                   # API keys (gitignored)
├── SOUL.md                # Agent personality
├── AGENTS.md              # Project context prepended to system prompt
│
├── agent/
│   ├── base_tool.py       # BaseTool ABC
│   ├── registry.py        # ToolRegistry singleton
│   ├── tools.py           # read, write, edit, bash
│   ├── loop.py            # AgentLoop, AgentConfig, AgentCallbacks
│   ├── config_loader.py   # Resolves model config from YAML
│   └── session.py         # SessionTracker — JSONL logs
│
├── nicegui_app/           # NiceGUI web UI
│   ├── main.py            # App entry point
│   ├── callbacks.py       # Agent → UI bridge (thread-safe)
│   ├── state.py           # App state
│   ├── history.py         # Session history loader
│   ├── components/        # Sidebar, chat message, tool card
│   └── styles/theme.css   # Soft-structuralism CSS
│
└── logs/                  # Session JSONL files
```

### Tools

| Tool | What it does |
|------|-------------|
| `read` | Read a text file (paginated) or image (base64). Pass `path`, optional `offset`/`limit` |
| `write` | Overwrite a file. Creates parent dirs. Takes `path` + `content` |
| `edit` | Replace exact `oldText` with `newText` in a file. Errors if text is absent or non-unique |
| `bash` | Run a shell command. Returns stdout + stderr + exit code. Pass `command` + optional `timeout` |

### Adding a Custom Tool

1. Create a class inheriting from `BaseTool`
2. Define `name`, `description`, and `_parameters` (JSON Schema)
3. Implement `run(self, ...)` — receives parsed args as kwargs
4. Register at the bottom of `agent/tools.py`:

```python
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

registry.register(MyTool())
```

---

## Session Logs

Every run is logged to `logs/session_<timestamp>.jsonl`. Entries include:

- Message history with token counts and cost estimates
- Tool call start/end events with inputs/outputs
- Session summary with totals on finish

The web UIs can load past sessions and continue them. Logs are append-only.

---

## Agent Identity

`SOUL.md` defines the agent's personality. `AGENTS.md` provides project context. Both are prepended to the system prompt.

---

## Dependencies

Core (from `pyproject.toml`):

- `openai` — API client (any OpenAI-compatible endpoint)
- `pyyaml` — config parsing
- `python-dotenv` — `.env` loading
- `nicegui` — NiceGUI web UI
- `markdown` — markdown rendering

Additional (used by CLI and Streamlit UI, install separately if needed):

- `typer` + `rich` — interactive CLI
- `streamlit` + `streamlit-autorefresh` — Streamlit web UI
