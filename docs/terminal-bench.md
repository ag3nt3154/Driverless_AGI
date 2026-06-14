# Running DAGI on Terminal-bench 2

Terminal-bench 2 evaluates AI agents on 89 real-world terminal tasks (software
engineering, sysadmin, ML, security, and more) inside isolated Docker containers.
DAGI participates via a thin adapter that routes its `bash` tool through the
benchmark's tmux session instead of a local subprocess.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker Desktop | Must be **running** before `tb run` |
| conda env `dagi` | Already set up for normal DAGI usage |
| Terminal-bench | Installed once via pip (see below) |
| API key | Same `.env` file used by normal DAGI |

## One-time setup

Install Terminal-bench into the `dagi` conda environment:

```
conda run -n dagi pip install terminal-bench
```

Verify the install:

```
conda run -n dagi tb --help
```

## How it works

`config_benchmark.yaml` is a copy of `config.yaml` with one key difference:

When the benchmark harness calls `DagiAgent.perform_task`, it constructs a
`TmuxBashTool` wrapping the `TmuxSession` provided by Terminal-bench and
passes it to `AgentLoop(..., _bash_tool=bash_tool)`. The agent loop then
registers **both** `BashTool` (local subprocess, name `bash`) and the injected
`TmuxBashTool` (name `tmux_bash`) in its tool registry. Inside the container
the agent uses `tmux_bash` to run commands; `bash` remains available for any
local operations. Normal DAGI usage (`config.yaml`) is completely unaffected —
only `BashTool` is registered when no `_bash_tool` is injected.

## Choosing a model

Set `DAGI_BENCH_MODEL` to any model key defined in `benchmarks/config_benchmark.yaml`.
If unset, defaults to `claude-sonnet-openrouter`.

```bat
set DAGI_BENCH_MODEL=claude-opus-openrouter
```

Edit `benchmarks/config_benchmark.yaml` to tune other settings (thinking level, subagent
models, max continuations, etc.) before running.

## Running the benchmark

### List available task IDs

```
conda run -n dagi tb list --dataset terminal-bench-core==head
```

### Single task (smoke test — cheapest)

```
benchmarks\run_terminal_bench.bat --task-id <task-id>
```

### Full benchmark suite

```
benchmarks\run_terminal_bench.bat
```

### Parallel execution

```
benchmarks\run_terminal_bench.bat --n-concurrent 4
```

Each `--n-concurrent N` slot runs a separate Docker container simultaneously.
Higher values finish faster but multiply API cost proportionally.

### Override model for one run

```bat
set DAGI_BENCH_MODEL=claude-opus-openrouter
benchmarks\run_terminal_bench.bat --n-concurrent 2
```

## Interpreting results

Terminal-bench prints a summary after each run:

```
Tasks attempted : 89
Tasks passed    : 47  (52.8 %)
Input tokens    : 412,000,000
Output tokens   :  38,000,000
```

Compare against the [official leaderboard](https://www.tbench.ai/) — top agents
currently score 60–65%. Each task is verified by a pytest suite running inside
the container, so pass/fail is objective.

DAGI session logs (`.dagi/logs/session_*.jsonl`) are written to the
`logging_dir` provided by the harness and can be analysed post-hoc with the
existing `parse_jsonl_logs.py` tool.

## Architecture

```
benchmarks\run_terminal_bench.bat
  └─ tb run --agent-import-path benchmarks.terminal_bench.agent:DagiAgent
       └─ DagiAgent.perform_task(instruction, tmux_session, logging_dir)
            ├─ resolve_model_config()   ← reads benchmarks/config_benchmark.yaml
            └─ AgentLoop(config, _bash_tool=bash_tool)
                 ├─ BashTool            ← name "bash",      local subprocess (always registered)
                 └─ TmuxBashTool        ← name "tmux_bash", injected alongside BashTool
                      └─ session.send_keys(command, block=True)
                           └─ command runs inside Docker container
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `conda: command not found` | Open Anaconda Prompt or add conda to PATH |
| `Docker not running` | Start Docker Desktop before running |
| `Model not found in config` | Check `DAGI_BENCH_MODEL` matches a key in `benchmarks/config_benchmark.yaml` |
| Command timeouts in container | Increase `timeout` via DAGI's bash tool call, or raise `max_continuations` |
