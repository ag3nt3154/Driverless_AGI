# dagi — Driverless AGI

A minimal, self-hosted coding agent harness. Give it a task in plain English and it reads files, writes code, edits existing files, and runs shell commands — looping autonomously until the job is done.

Powered by any OpenAI-compatible API (OpenAI, OpenRouter, Ollama, LM Studio, etc.).

## Architecture

```
main.py          CLI entry point — loads config, runs the agent loop
app.py           Streamlit chat UI — full web interface with live tool output
config.yaml      Runtime config: model, base_url, max_iterations (gitignored)
.env             API keys: OPENAI_API_KEY or OPENROUTER_API_KEY (gitignored)
soul.md          Agent personality and work style
agents.md        Project context prepended to every session
agent/
  base_tool.py   BaseTool ABC — all tools inherit from this
  registry.py    ToolRegistry singleton — tools register here on import
  tools.py       ReadTool, WriteTool, EditTool, BashTool
  loop.py        AgentConfig dataclass + AgentLoop (the agentic loop)
  session.py     SessionTracker — logs every session to JSON with token counts
logs/            Auto-generated session logs with full message history
```

## Tools

| Tool | Purpose |
|------|---------|
| **read** | Read text files (paginated with offset/limit) or images (sent as base64 attachments) |
| **write** | Create or overwrite a file; auto-creates parent directories |
| **edit** | Surgical find-and-replace — `oldText` must match exactly once in the file |
| **bash** | Run shell commands; returns stdout + stderr + exit code |

Tools follow a strict convention: `edit` requires the target text to appear exactly once. If it matches zero or multiple times, the tool errors out and the agent must adjust.

## Setup

```bash
# Install dependencies (requires Python 3.11+)
pip install -e .

# Set your API key
echo "OPENAI_API_KEY=sk-..." > .env

# Or copy the example config
cp config.example.yaml config.yaml
```

## Usage

### CLI

```bash
# Pass a task directly
dagi "list files in the current directory"

# Pipe via stdin
echo "read main.py and explain the architecture" | dagi

# Override model or backend
dagi --model gpt-4o-mini "what model are you?"
dagi --base-url http://localhost:11434/v1 --model llama3 "hello"
```

### Web UI (Streamlit)

```bash
streamlit run app.py
```

A polished chat interface with live tool execution output, token/cost tracking, session history, and diff previews for file edits.

## Configuration

Priority (highest → lowest): CLI flags → `.env` / environment variables → `config.yaml` → defaults.

**`config.yaml`**
```yaml
model: gpt-4o
base_url: https://api.openai.com/v1
max_iterations: 20
```

**`.env`**
```
OPENAI_API_KEY=sk-...
# or
OPENROUTER_API_KEY=sk-or-...
```

## Session Logging

Every agent run is logged to `logs/session_YYYY-MM-DD_HH-MM-SS.json` with:
- Full message history (system, user, assistant, tool calls)
- Token counts (input/output) per assistant turn
- Cost tracking (when supported by the API provider)
- Tool call frequency summary

## Extending

Add a new tool by creating a class that inherits from `BaseTool` in `agent/tools.py`:

```python
class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    _parameters = {
        "type": "object",
        "properties": {
            "arg": {"type": "string", "description": "An argument"},
        },
        "required": ["arg"],
    }

    def run(self, arg: str) -> str:
        return f"Did something with {arg}"

# Register at the bottom of tools.py:
registry.register(MyTool())
```

It'll automatically appear in the agent's tool list and be available for use.

## Design Decisions

- **`parallel_tool_calls=False`** — side-effectful tools (write, edit, bash) have undefined behavior when executed in parallel, so the agent processes one tool call at a time.
- **Edit uniqueness invariant** — prevents mass-replacement bugs; forces the agent to be precise about what it's changing.
- **Tool modules import only leaf dependencies** (`base_tool`, `registry`) — keeps the import graph clean and flat.

## License

MIT
