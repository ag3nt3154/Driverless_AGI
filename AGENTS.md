# Agents

## Project
Driverless AGI — a minimal self-hosted coding agent harness.

## Architecture
```
agent/
  base_tool.py   BaseTool ABC — all tools inherit from this
  registry.py    ToolRegistry singleton — tools register here on import
  tools.py       ReadTool, WriteTool, EditTool, BashTool
  loop.py        AgentConfig dataclass + AgentLoop (the agentic loop)
main.py          CLI entry point — loads config, runs the loop
config.yaml      Runtime config: model, base_url, max_iterations (gitignored)
.env             API keys: OPENAI_API_KEY (gitignored)
soul.md          Agent identity and work style (this file's companion)
agents.md        This file — project context prepended to every session
```

## Tools Available
| Tool  | Purpose |
|-------|---------|
| read  | Read text files (paginated) or images (base64 attachment) |
| write | Write or overwrite a file; creates parent dirs automatically |
| edit  | Replace an exact unique string in a file — surgical edits only |
| bash  | Run a shell command; returns stdout + stderr + exit code |

## Conventions
- `edit` requires `oldText` to appear exactly once in the file. If it appears 0 or 2+ times, the tool errors — use `write` for full rewrites instead.
- Always `read` a file before `edit`ing it.
- New tools can be added to `agent/tools.py` following the `BaseTool` pattern and registering at the bottom of the file.
