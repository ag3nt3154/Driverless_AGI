---
name: run_subagent
description: >-
  Write custom subagent workflows by composing run_subagent() calls in a Python
  script. Use when no predefined subagent tool fits, or when you need to chain
  multiple subagents together (sequential, fan-out, conditional).
triggers: custom subagent, subagent workflow, orchestrate subagents, chain subagents
---

# Custom Subagent Workflows

Main-agent use only. A subagent must not invoke this skill, call run_subagent, or spawn
another agent. Return further work and wiki query/add requests in its handoff instead.
Orchestration examples below apply only to the main agent.

## When to Use

Use this skill when:
- No predefined subagent tool (`run_worker`, `explore_files`, etc.)
  fits your task
- You need to run multiple subagents in sequence, with data flow between them
- You need to fan out work across multiple subagents in a loop
- You need conditional logic based on subagent results

For single, standard operations, prefer the predefined subagent tools — they handle plan
context injection and briefing automatically.

## Function Signature

```python
from tools.subagent_api import run_subagent, SubagentResult

result: SubagentResult = run_subagent(
    task="What the subagent should do",
    preset=None,              # "worker", "explore_files", etc. — or None for custom
    prompt=None,              # System prompt (required if no preset)
    custom_instructions="",   # Situational guidance appended to the task envelope
    tools=None,               # ["read", "grep", "edit", "bash", ...] — overrides preset
    timeout=1800.0,           # Seconds before the subagent is killed
    model_tier="default",     # "default", "worker", "advanced"
    handoff_spec="",          # What to include in the handoff report
    project_path=None,        # Defaults to cwd
)
```

### Parameter Notes

- `preset` and `prompt` are mutually exclusive but one is required. If you provide both,
  `prompt` overrides the preset's system prompt while the preset's tools/tier/handoff_spec
  remain as defaults (still overridable individually).
- `tools` only takes effect when explicitly passed or when no preset is used. When a preset
  is active and `tools` is omitted, the preset's tool list is used.
- `model_tier` values: `"worker"` (fast/cheap), `"default"` (inherits preset or standard),
  `"advanced"` (best quality, slower).
- `handoff_spec` tells the subagent what to include in its handoff report. Be explicit — it
  shapes the output you read back.

## SubagentResult

```python
result.status           # "ok" | "ok_unverified" | "error" | "timeout"
result.is_ok            # True if status is "ok" or "ok_unverified"
result.handoff_text     # Auto-read content of the handoff file (empty on non-ok status)
result.handoff_path     # Path to the handoff file
result.session_log_path # Path to session log (read if debugging)
result.pid              # PID (only populated on timeout — for resume)
```

Always check `result.is_ok` before using `result.handoff_text`. On `"error"` or `"timeout"`,
`handoff_text` is empty.

## Patterns

### Sequential Chain

Run an exploration pass, then feed its output into a worker.

```python
from tools.subagent_api import run_subagent
import json

# Step 1: Explore
explore = run_subagent(
    task="Map the auth module's public API surface",
    preset="explore_files",
)

if not explore.is_ok:
    print(f"Exploration failed: {explore.status}")
    raise SystemExit(1)

# Step 2: Work based on exploration
worker = run_subagent(
    task="Refactor the auth module to use the new token format",
    preset="worker",
    custom_instructions=f"Based on exploration:\n{explore.handoff_text[:2000]}",
)

print(json.dumps({
    "explore": {"status": explore.status, "path": str(explore.handoff_path)},
    "worker": {"status": worker.status, "path": str(worker.handoff_path)},
}, default=str))
```

### Fan-Out

Run the same subagent over a list of targets, collecting results.

```python
from tools.subagent_api import run_subagent
import json

modules = ["auth", "payments", "users"]
results = []
for mod in modules:
    r = run_subagent(
        task=f"Map the {mod} module's public API",
        preset="explore_files",
    )
    results.append({"module": mod, "status": r.status, "path": str(r.handoff_path)})

print(json.dumps(results, default=str))
```

### Fully Custom Subagent

No preset — provide your own system prompt and tool list.

```python
from tools.subagent_api import run_subagent

result = run_subagent(
    task="Analyze all SQL queries for injection vulnerabilities",
    prompt="You are a security auditor specializing in SQL injection detection.",
    tools=["read", "grep", "find"],
    model_tier="advanced",
    handoff_spec="List every vulnerable query with file:line and suggested fix.",
    timeout=600,
)

if result.is_ok:
    print(result.handoff_text)
else:
    print(f"Failed: {result.status}")
```

### Conditional Branching

Take different follow-up actions based on a subagent's verdict.

```python
from tools.subagent_api import run_subagent

audit = run_subagent(
    task="Check whether the payments module has any TODO comments",
    preset="explore_files",
    handoff_spec="List every TODO with file:line. If none found, say 'NO_TODOS'.",
)

if audit.is_ok and "NO_TODOS" not in audit.handoff_text:
    fix = run_subagent(
        task="Resolve all TODO comments in the payments module",
        preset="worker",
        custom_instructions=f"TODOs found:\n{audit.handoff_text[:2000]}",
    )
    print(f"Fix status: {fix.status}")
else:
    print("Nothing to fix.")
```

### Timeout Handling

Resume a timed-out subagent by PID rather than starting over.

```python
from tools.subagent_api import run_subagent, resume_subagent_by_pid

result = run_subagent(task="Long analysis", preset="explore_files", timeout=300)
if result.status == "timeout":
    result = resume_subagent_by_pid(result.pid, extra_seconds=300)

print(result.handoff_text if result.is_ok else f"Failed: {result.status}")
```

## Python Environment

Read the `DEFAULT_PYTHON_ENV` value from the system prompt — it is injected automatically
by the harness. Do **not** hardcode `conda run -n dagi`. Run workflow scripts via:

```bash
conda run -n {DEFAULT_PYTHON_ENV} python workflow.py
```

Where `{DEFAULT_PYTHON_ENV}` is substituted with the value from the system prompt (e.g.
`dagi`). If you are unsure, check the system prompt header for the `DEFAULT_PYTHON_ENV`
line.

## Where to Save and Run

1. Write your workflow script to a `.py` file in the project root or a scratch directory
   (e.g. `scripts/workflow_<slug>.py`).
2. Run it via the bash tool:

   ```bash
   conda run -n {DEFAULT_PYTHON_ENV} python scripts/workflow_<slug>.py
   ```

3. The script prints JSON with `status` and `path` fields for each result. Read the
   handoff files from the printed paths for detailed subagent output.
4. Delete or archive the script when the workflow is complete — it is a one-off tool, not
   permanent source code.
