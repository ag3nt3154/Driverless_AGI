# Plan: Driverless AGI — Minimal Coding Agent Harness

## Context
A minimal Python coding agent. Calls any OpenAI-compatible API, runs a tool-use loop with 4 built-in tools: read, write, edit, bash.

---

## Directory Layout

```
driverless_agi/
├── agent/
│   ├── base_tool.py     # BaseTool ABC
│   ├── registry.py      # ToolRegistry + module-level singleton
│   ├── tools.py         # ReadTool, WriteTool, EditTool, BashTool + registration
│   └── loop.py          # AgentLoop (config + history inlined)
├── main.py              # CLI entry point
├── config.yaml          # Model + runtime config (gitignored)
├── .env                 # API keys (gitignored)
└── pyproject.toml
```

## Component Dependency Diagram

```
main.py → AgentLoop → ToolRegistry → BaseTool
                    ↑
               tools.py → ReadTool, WriteTool, EditTool, BashTool
```

Import rule: `tools.py` imports only `base_tool` and `registry` (leaf imports).

---

## Implementation Steps (in order)

### 1. `pyproject.toml`
```toml
[project]
name = "driverless-agi"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["openai", "pyyaml", "python-dotenv"]

[project.scripts]
dagi = "main:main"

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:build"
```

### 2. `agent/base_tool.py`
```python
from abc import ABC, abstractmethod

class BaseTool(ABC):
    name: str
    description: str
    _parameters: dict  # JSON Schema object for inputs

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters,
            },
        }

    @abstractmethod
    def run(self, **kwargs) -> str: ...
```

### 3. `agent/registry.py`
```python
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None: ...     # raises ValueError if name exists
    def get_openai_tools_list(self) -> list[dict]: ...  # [t.schema() for t in ...]
    def dispatch(self, name: str, kwargs: dict) -> str: # catches exc → str
        ...

registry = ToolRegistry()   # module-level singleton
```

### 4. `agent/tools.py`
All 4 tools in one file. Registration loop at the bottom.

**`ReadTool`**
- Params: `path: str`, `offset: int = 0` (1-indexed), `limit: int = 2000`
- For text: returns lines `[offset : offset+limit]` joined by `\n`
- For images (jpg, png, gif, webp): returns base64-encoded content as an image attachment

**`WriteTool`**
- Params: `path: str`, `content: str`
- `Path(path).parent.mkdir(parents=True, exist_ok=True)` then `write_text(content)`

**`EditTool`**
- Params: `path: str`, `old_text: str`, `new_text: str`
- Read file, count occurrences of `old_text`
- Return error string if count == 0 or count > 1 (no changes written)
- Replace exactly once, write back

**`BashTool`**
- Params: `command: str`, `timeout: int | None = None`
- `subprocess.run(command, shell=True, capture_output=True, timeout=timeout, text=True)`
- Returns `stdout + stderr`; non-zero exit code noted in return string

**Registration:**
```python
for cls in [ReadTool, WriteTool, EditTool, BashTool]:
    registry.register(cls())
```

### 5. `agent/loop.py`

`AgentConfig` dataclass (inlined — no separate file):
- `model: str = "gpt-4o"`
- `base_url: str = "https://api.openai.com/v1"`
- `api_key: str` — `field(default_factory=lambda: os.environ["OPENAI_API_KEY"])`
- `max_iterations: int = 20`
- `system_prompt: str` — instructs agent on its tools and workflow

Config is loaded in `main.py` with this priority (highest → lowest):
1. CLI args (`--model`, `--base-url`, `--max-iter`)
2. `.env` file — loaded via `python-dotenv` before env vars are read; use for `OPENAI_API_KEY` and optionally `AGENT_MODEL`, `AGENT_BASE_URL`
3. `config.yaml` — loaded if present; supports keys `model`, `base_url`, `max_iterations`
4. `AgentConfig` dataclass defaults

Loading logic in `main.py` (no classmethods on `AgentConfig`):
```python
from dotenv import load_dotenv
import yaml

load_dotenv()  # populates os.environ from .env before anything reads it

yaml_cfg = {}
if Path("config.yaml").exists():
    yaml_cfg = yaml.safe_load(Path("config.yaml").read_text()) or {}

# build AgentConfig: yaml as base, CLI args override
config = AgentConfig(
    model=args.model or yaml_cfg.get("model", "gpt-4o"),
    base_url=args.base_url or yaml_cfg.get("base_url", "https://api.openai.com/v1"),
    max_iterations=args.max_iter or yaml_cfg.get("max_iterations", 20),
)
```

Example `config.yaml`:
```yaml
model: gpt-4o-mini
base_url: https://api.openai.com/v1
max_iterations: 30
```

Example `.env`:
```
OPENAI_API_KEY=sk-...
```

`AgentLoop`:
```python
class AgentLoop:
    def __init__(self, config: AgentConfig, registry: ToolRegistry):
        self._messages = [{"role": "system", "content": config.system_prompt}]
        self.client = openai.OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.config = config
        self.registry = registry

    def run(self, task: str) -> str:
        self._messages.append({"role": "user", "content": task})
        for _ in range(self.config.max_iterations):
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=self._messages,
                tools=self.registry.get_openai_tools_list(),
                parallel_tool_calls=False,
            )
            message = response.choices[0].message
            self._messages.append(message)
            if not message.tool_calls:
                return message.content
            results = []
            for tc in message.tool_calls:
                result = self.registry.dispatch(tc.function.name, json.loads(tc.function.arguments))
                results.append({"tool_call_id": tc.id, "role": "tool", "content": result})
            self._messages.append({"role": "tool", "content": results})  # batched
        self._messages.append({"role": "user", "content": "Max iterations reached. Summarize what you have done so far."})
        response = self.client.chat.completions.create(
            model=self.config.model, messages=self._messages
        )
        return response.choices[0].message.content
```

### 6. `main.py`
- `load_dotenv()` first, before any env reads
- Load `config.yaml` if present
- argparse: `task` (positional, `nargs="?"`), `--model`, `--base-url`, `--max-iter`
- Config priority: CLI > `.env` / env vars > `config.yaml` > defaults
- If no positional task, read from stdin
- Import `agent.tools` (triggers registration side-effect)
- Instantiate `AgentLoop(config, registry).run(task)`, print result

---

## Critical Design Constraints

| Constraint | Rationale |
|---|---|
| `parallel_tool_calls=False` hardcoded | Side-effectful tools (edit, write, bash) have undefined ordering when parallel |
| Edit uniqueness invariant | Prevents mass-replacement bugs; agent must be precise |
| Tool modules import only leaf deps (`base_tool`, `registry`) | Keeps import graph clean for future hot-reload if added later |

---

## Verification

```bash
pip install -e .

# 1. Basic bash tool
dagi "list files in current directory"

# 2. Read tool
dagi "read main.py and summarize it"

# 3. Edit workflow
dagi "add a docstring to the AgentLoop class in agent/loop.py"

# 4. config.yaml override
echo "model: gpt-4o-mini" > config.yaml
dagi "what model are you?"

# 5. Alternate backend (Ollama) via CLI override
dagi --base-url http://localhost:11434/v1 --model llama3 "hello"
```
