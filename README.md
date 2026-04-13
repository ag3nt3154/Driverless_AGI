# Driverless AGI

A minimal, self-hosted coding agent harness. Give it a task, it plans, executes tools, reads results, and iterates until it's done — or until it hits the iteration limit and tells you what it managed.

No black box. No magic. Every piece is yours to read, tweak, and extend.

---

## How It Works

The agent runs a tight loop:

1. **Plan** — The model decides on a step based on the task and prior results
2. **Act** — It calls a tool (`read`, `write`, `edit`, or `bash`)
3. **Observe** — It reads the tool's output
4. **Repeat** — Until the task is complete or `max_iterations` is hit

Tools are defined as classes inheriting from `BaseTool` and register themselves on import. Add a new one by dropping it in `agent/tools.py`.

---

## Setup

### 1. Clone / navigate to the project

```bash
cd Driverless_AGI
```

### 2. Create a `.env` file

```env
OPENAI_API_KEY=sk-...
```

Other providers (OpenRouter, etc.) have their own key env vars — see [Configuration](#configuration).

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure models (optional)

Edit `config.yaml` to select which model to use and configure API endpoints. A default model and several preconfigured options are included.

---

## Usage

### Run a task

**Argument:**
```bash
python main.py "Fix the off-by-one error in processor.py"
```

**Stdin:**
```bash
echo "Add type hints to all functions in agent/" | python main.py
```

**Select a model:**
```bash
python main.py --model gpt-4o-openai "your task"
```

**Set max iterations:**
```bash
python main.py --max-iter 50 "your task"
```

---

## Configuration

`config.yaml` controls runtime behavior:

```yaml
default_model: minimax-openrouter   # used if --model isn't passed
max_iterations: 20                  # hard cap on loop iterations

models:
  gpt-4o-openai:
    api_key_env: OPENAI_API_KEY      # name of env var holding the key
    api_url: https://api.openai.com/v1
    model: gpt-4o                   # actual model ID
    name: GPT-4o (OpenAI)           # display name

  claude-opus-openrouter:
    api_key_env: OPENROUTER_API_KEY
    api_url: https://openrouter.ai/api/v1
    model: anthropic/claude-opus-4-6
    name: Claude Opus 4.6 (OpenRouter)
```

### Adding a new model

Add a new entry under `models`:

```yaml
  my-model:
    api_key_env: MY_API_KEY
    api_url: https://my-provider.com/v1
    model: provider/model-id
    name: My Model (Provider)
```

Set `default_model: my-model` to use it by default.

---

## Architecture

```
Driverless_AGI/
├── main.py              # CLI entry point
├── config.yaml          # Model and runtime config
├── .env                 # API keys (gitignored)
├── soul.md             # Agent personality (me)
├── agents.md           # Agent context / system prompt base
│
└── agent/
    ├── base_tool.py    # BaseTool ABC — inherit to add tools
    ├── registry.py     # ToolRegistry singleton
    ├── tools.py         # read, write, edit, bash
    ├── loop.py          # AgentLoop + AgentConfig
    ├── config_loader.py # Resolves model config
    └── session.py       # SessionTracker — logs to logs/
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
4. Register it at the bottom of `agent/tools.py`:

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
- Message history with token counts and cost
- Tool call start/end events with inputs/outputs
- Session summary on finish

Logs are append-only. Rotate or clean as needed.

---

## Custom Agent Identity

`soul.md` defines the agent's personality and tone — that's me. Edit it to create a different agent character. `agents.md` provides project context prepended to every session.

---

## Dependencies

- `openai` — API client
- `python-dotenv` — `.env` loading
- `pyyaml` — config parsing

See `requirements.txt` for pinned versions.
