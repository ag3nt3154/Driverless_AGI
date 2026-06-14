# Harbor Harness Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two structural bugs in the Harbor benchmark harness that cause every task to score 0.0 regardless of the model used.

**Architecture:** Two orthogonal fixes applied to three files. Fix A removes the misleading `project_path` (logs dir → temp dir). Fix B threads a new `system_prompt_preamble` field through `AgentConfig` → `config_loader` → `AgentLoop` and populates it in `config_benchmark.yaml` with Harbor-specific environment instructions. Both fixes are independent and can be verified in isolation.

**Tech Stack:** Python 3.11+ / dataclasses, PyYAML, pytest

---

## Root causes

**Fix A — `project_path` set to Harbor logs dir** (`benchmarks/harbor/agent.py:67`):
The agent's `find`/`read` tools search `project_path`. When that points to Harbor's log dir, the model sees `.dagi/plans/` DAGI internal files and tries to use them as task files. The system prompt also emits `"Project root: <logs_dir>"` (loop.py:294), directing the model to explore that path rather than the Docker container.

**Fix B — No system prompt telling the agent about Harbor** (`config_benchmark.yaml` / `agent/loop.py`):
The model defaults to `enter_plan_mode` (which strips `harbor_bash`) and tries Windows file tools (which reach the host, not the container). There is no instruction saying "use `harbor_bash` to explore `/app` first."

---

## File map

| File | Change |
|------|--------|
| `agent/loop.py` | Add `system_prompt_preamble: str = ""` to `AgentConfig`; inject it first in `preamble_parts` during system prompt assembly |
| `agent/config_loader.py` | Parse `system_prompt_preamble` from yaml in `_build_config_from_entry` |
| `benchmarks/harbor/agent.py` | Change `config.project_path = Path(self.logs_dir) …` → `tempfile.mkdtemp()` |
| `config_benchmark.yaml` | Create file with model catalog, tool allowlist, and Harbor preamble |
| `tests/test_harbor_harness.py` | New test file covering both fixes |

---

## Task 1: Add `system_prompt_preamble` to `AgentConfig`

**Files:**
- Modify: `agent/loop.py` (AgentConfig dataclass, ~line 140)

- [ ] **Step 1: Write failing test**

Create `tests/test_harbor_harness.py`:

```python
"""tests/test_harbor_harness.py — Harbor harness regression tests."""
from __future__ import annotations
from pathlib import Path
from agent.loop import AgentConfig


class TestSystemPromptPreamble:
    def test_default_is_empty(self):
        cfg = AgentConfig()
        assert cfg.system_prompt_preamble == ""

    def test_preamble_field_accepts_string(self):
        cfg = AgentConfig(system_prompt_preamble="## Harbor\nuse harbor_bash")
        assert "harbor_bash" in cfg.system_prompt_preamble
```

- [ ] **Step 2: Run to verify it fails**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestSystemPromptPreamble -v
```
Expected: `AttributeError: 'AgentConfig' object has no attribute 'system_prompt_preamble'`

- [ ] **Step 3: Add the field to `AgentConfig` in `agent/loop.py`**

Find the last field in `AgentConfig` (currently `sandbox_mode: bool = False` around line 142). Add after it:

```python
    # Harbor / benchmark environment preamble injected at the TOP of the system prompt.
    # Set in config_benchmark.yaml to tell the agent about the container environment.
    system_prompt_preamble: str = ""
```

- [ ] **Step 4: Run to verify it passes**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestSystemPromptPreamble -v
```
Expected: both tests PASS

- [ ] **Step 5: Commit**

```
git add agent/loop.py tests/test_harbor_harness.py
git commit -m "feat: add system_prompt_preamble field to AgentConfig"
```

---

## Task 2: Parse `system_prompt_preamble` from config yaml

**Files:**
- Modify: `agent/config_loader.py` (`_build_config_from_entry`, ~line 109)
- Test: `tests/test_harbor_harness.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_harbor_harness.py`:

```python
import textwrap
import tempfile
from agent.config_loader import resolve_model_config


class TestPreambleFromConfig:
    def test_preamble_read_from_yaml(self, tmp_path):
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(textwrap.dedent("""
            system_prompt_preamble: "## Harbor\\nuse harbor_bash"
            default_model: m
            models:
              m:
                name: Test
                model: test-model
                api_url: http://localhost
                api_key: test-key
        """), encoding="utf-8")
        cfg = resolve_model_config(config_path=cfg_yaml)
        assert cfg.system_prompt_preamble == "## Harbor\nuse harbor_bash"

    def test_preamble_defaults_to_empty_when_absent(self, tmp_path):
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(textwrap.dedent("""
            default_model: m
            models:
              m:
                name: Test
                model: test-model
                api_url: http://localhost
                api_key: test-key
        """), encoding="utf-8")
        cfg = resolve_model_config(config_path=cfg_yaml)
        assert cfg.system_prompt_preamble == ""
```

- [ ] **Step 2: Run to verify it fails**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestPreambleFromConfig -v
```
Expected: FAIL — `system_prompt_preamble` not set in resolved config (remains `""` even when in yaml)

- [ ] **Step 3: Add parsing in `_build_config_from_entry`**

In `agent/config_loader.py`, inside `_build_config_from_entry` (around line 130, after the `sandbox_mode` line):

```python
    system_prompt_preamble: str = str(raw.get("system_prompt_preamble", "") or "")
```

Then add it to the `AgentConfig(...)` constructor call at the bottom of the function:

```python
    return AgentConfig(
        ...
        sandbox_mode=sandbox_mode,
        system_prompt_preamble=system_prompt_preamble,
    )
```

- [ ] **Step 4: Run to verify tests pass**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestPreambleFromConfig -v
```
Expected: both PASS

- [ ] **Step 5: Verify full test suite still passes**

```
conda run -n dagi python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests pass (the new field has a default so no existing call site breaks)

- [ ] **Step 6: Commit**

```
git add agent/config_loader.py tests/test_harbor_harness.py
git commit -m "feat: parse system_prompt_preamble from config yaml"
```

---

## Task 3: Inject `system_prompt_preamble` into the system prompt

**Files:**
- Modify: `agent/loop.py` (system prompt assembly block, ~lines 273–295)
- Test: `tests/test_harbor_harness.py`

The existing preamble assembly (lines 273–291) builds `preamble_parts` from soul → agents.md files. We prepend `system_prompt_preamble` so it comes first — the Harbor context-setting instruction arrives before the persona/behavioral guidelines.

Also need to apply the same injection in `_rebuild_for_normal_mode` and `_rebuild_for_plan_mode` (which rebuild the system prompt on mode transitions). These methods follow the same pattern as `__init__`.

- [ ] **Step 1: Write failing test**

Add to `tests/test_harbor_harness.py`:

```python
from unittest.mock import MagicMock, patch


class TestPreambleInjection:
    def _make_loop(self, preamble: str = "") -> "AgentLoop":
        """Build a minimal AgentLoop with a preamble and mock API client."""
        from agent.loop import AgentLoop, AgentConfig, AgentCallbacks
        cfg = AgentConfig(
            system_prompt="Base system prompt. {tools_and_skills}",
            system_prompt_preamble=preamble,
            api_key="test",
        )
        with patch("agent.loop.OpenAI"):
            loop = AgentLoop(cfg, callbacks=AgentCallbacks())
        return loop

    def test_preamble_appears_first_in_system_message(self):
        loop = self._make_loop(preamble="HARBOR_PREAMBLE_MARKER")
        system_content = loop._messages[0]["content"]
        assert "HARBOR_PREAMBLE_MARKER" in system_content
        # Preamble should appear before the base system prompt
        assert system_content.index("HARBOR_PREAMBLE_MARKER") < system_content.index("Base system prompt")

    def test_no_preamble_leaves_system_unchanged(self):
        loop_with = self._make_loop(preamble="UNIQUE_MARKER")
        loop_without = self._make_loop(preamble="")
        assert "UNIQUE_MARKER" not in loop_without._messages[0]["content"]
```

- [ ] **Step 2: Run to verify it fails**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestPreambleInjection -v
```
Expected: FAIL — preamble not present in system message

- [ ] **Step 3: Inject preamble in `AgentLoop.__init__` system prompt assembly**

In `agent/loop.py`, find the preamble assembly block (around line 273):

```python
        # Load preamble: soul (project first, dagi root fallback), then agents.md files
        preamble_parts: list[str] = []
        soul_text = load_soul(dagi_root, config.project_path)
```

Change to:

```python
        # Load preamble: config preamble first, then soul, then agents.md files
        preamble_parts: list[str] = []
        if config.system_prompt_preamble:
            preamble_parts.append(config.system_prompt_preamble.strip())
        soul_text = load_soul(dagi_root, config.project_path)
```

- [ ] **Step 4: Run to verify it passes**

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestPreambleInjection -v
```
Expected: both PASS

- [ ] **Step 5: Apply same injection in `_rebuild_for_normal_mode` and `_rebuild_for_plan_mode`**

Both methods rebuild the full system prompt on mode transitions. Search for `preamble_parts: list[str] = []` — it appears in both methods. Apply the same `if config.system_prompt_preamble:` guard before `soul_text = load_soul(...)` in both.

In `_rebuild_for_normal_mode` (around line 772):
```python
        preamble_parts: list[str] = []
        if self.config.system_prompt_preamble:
            preamble_parts.append(self.config.system_prompt_preamble.strip())
        soul_text = load_soul(dagi_root, self.config.project_path)
```

In `_rebuild_for_plan_mode` (around line 830):
```python
        preamble_parts: list[str] = []
        if self.config.system_prompt_preamble:
            preamble_parts.append(self.config.system_prompt_preamble.strip())
        soul_text = load_soul(dagi_root, self.config.project_path)
```

- [ ] **Step 6: Run full test suite**

```
conda run -n dagi python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all tests pass

- [ ] **Step 7: Commit**

```
git add agent/loop.py tests/test_harbor_harness.py
git commit -m "feat: inject system_prompt_preamble into system prompt (all build sites)"
```

---

## Task 4: Fix A — Neutral temp workspace in Harbor agent

**Files:**
- Modify: `benchmarks/harbor/agent.py` (line 67)
- Test: `tests/test_harbor_harness.py`

Currently `config.project_path = Path(self.logs_dir) if self.logs_dir else Path(".")` sets DAGI's internal workspace to Harbor's log directory. When the model calls `find("**/*")`, it discovers `.dagi/plans/` DAGI files and mistakes them for task files. The system prompt's `"Project root: <logs_dir>"` line reinforces this confusion.

Fix: use a fresh `tempfile.mkdtemp()` so DAGI's workspace is clean and the system prompt emits `"Project root: /tmp/xxxx"` — a path the model has no reason to explore.

- [ ] **Step 1: Write failing test**

Add to `tests/test_harbor_harness.py`:

```python
import asyncio


class TestHarborProjectPath:
    def test_project_path_is_not_logs_dir(self, tmp_path):
        """DagiAgent must NOT set project_path to the Harbor logs directory."""
        logs_dir = str(tmp_path / "logs")

        captured: dict = {}

        class _PatchedDagiAgent:
            """Minimal stand-in that exposes the project_path selection logic."""
            logs_dir = logs_dir

            def _get_project_path(self) -> Path:
                import tempfile
                return Path(tempfile.mkdtemp())

        agent = _PatchedDagiAgent()
        path = agent._get_project_path()
        assert str(path) != logs_dir
        assert path.exists()  # tempfile.mkdtemp() creates the dir

    def test_project_path_is_a_clean_directory(self, tmp_path):
        """The chosen project_path must start empty (no pre-existing .dagi/ files)."""
        import tempfile
        path = Path(tempfile.mkdtemp())
        assert list(path.iterdir()) == []
```

- [ ] **Step 2: Run to verify tests pass** (these are greenfield tests, not testing a bug yet)

```
conda run -n dagi python -m pytest tests/test_harbor_harness.py::TestHarborProjectPath -v
```
Expected: PASS — the tests document intended behavior

- [ ] **Step 3: Apply the fix in `benchmarks/harbor/agent.py`**

At the top of the file, add `import tempfile` after `import os`:

```python
import asyncio
import os
import tempfile
from pathlib import Path
```

On line 67, replace:
```python
        config.project_path = Path(self.logs_dir) if self.logs_dir else Path(".")
```
with:
```python
        config.project_path = Path(tempfile.mkdtemp())
```

- [ ] **Step 4: Verify the agent still imports cleanly**

```
conda run -n dagi python -c "from benchmarks.harbor.agent import DagiAgent; print('ok')"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```
git add benchmarks/harbor/agent.py tests/test_harbor_harness.py
git commit -m "fix: use tempfile.mkdtemp() for Harbor agent project_path"
```

---

## Task 5: Create `config_benchmark.yaml` with Harbor preamble

**Files:**
- Create: `config_benchmark.yaml`

This file is referenced by `benchmarks/harbor/agent.py` and `benchmarks/terminal_bench/agent.py` as the benchmark-specific model config. It does not exist on disk (was previously created by the user and not committed). We create it with:
- A model catalog matching what the user runs (placeholder entries — user fills in API keys)
- A `tools:` allowlist scoped to Harbor (`harbor_bash` only for container access + `read`/`find`/`grep`/`write`/`edit` for local plan files)
- `system_prompt_preamble:` with Harbor-specific environment instructions
- `max_continuations: 30` (longer budget for benchmark tasks)

> **Note**: `config_benchmark.yaml` contains API keys via `api_key_env` pointers — it is NOT gitignored. Inline `api_key:` values must never be committed.

- [ ] **Step 1: Create `config_benchmark.yaml`**

```yaml
# config_benchmark.yaml — Harbor / Terminal-bench benchmark configuration
# Copy your model definitions from config.yaml and tune settings for benchmarks.
# This file is loaded by benchmarks/harbor/agent.py and benchmarks/terminal_bench/agent.py.
#
# Select model at run time:
#   set DAGI_BENCH_MODEL=claude-sonnet-openrouter
#   benchmarks\run_harbor.bat

# ── Loop behaviour ────────────────────────────────────────────────────────────
max_continuations: 30       # Benchmark tasks need more iterations than interactive sessions
null_response_retries: 5
api_error_retries: 5

# ── Harbor environment preamble ───────────────────────────────────────────────
# Injected at the TOP of the system prompt for every Harbor benchmark run.
# Tells the agent which tool to use for container file access.
system_prompt_preamble: |
  ## Harbor Benchmark Environment

  You are running inside a **Harbor benchmark**. The task's files live in a
  **Docker container** — they are NOT on the local filesystem.

  CRITICAL rules:
  - Your **FIRST action** must be `harbor_bash("ls /app")` to explore the container.
  - ALL file access (read, write, compile, run, test) MUST go through `harbor_bash`.
  - The local `find` / `read` / `grep` / `write` / `edit` tools see only the
    Windows host — they cannot reach container paths like `/app`. Do not use them
    for task-related files.
  - Do NOT call `enter_plan_mode`. Plan mentally, then act immediately via
    `harbor_bash`. Time-boxed benchmarks have no human to approve a plan.
  - The task workspace is typically `/app` in the container. Start there.

# ── Tools ─────────────────────────────────────────────────────────────────────
# harbor_bash is the ONLY tool that reaches the Docker container.
# Local file tools are included so the agent can write plans/notes to its
# ephemeral workspace (project_path = tempdir), but they cannot touch /app.
tools:
  - harbor_bash        # Container shell — primary execution tool
  - read               # Local file read (agent's temp workspace only)
  - find               # Local file find (agent's temp workspace only)
  - grep               # Local file grep (agent's temp workspace only)
  - write              # Local file write (agent's temp workspace only)
  - edit               # Local file edit (agent's temp workspace only)
  - ask_user           # Blocked by timeout in benchmarks — kept for compat

# bash_backend: kept for backwards compatibility — no longer drives tool registration
bash_backend: subprocess

# ── Model catalog ─────────────────────────────────────────────────────────────
# Add the models you want to benchmark. Set DAGI_BENCH_MODEL to the key.
# If DAGI_BENCH_MODEL is unset, default_model is used.

default_model: claude-sonnet-openrouter

models:
  claude-sonnet-openrouter:
    name: Claude Sonnet 4.6 (OpenRouter)
    model: anthropic/claude-sonnet-4-6
    api_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    context_window: 200000
    reserve_tokens: 16384
    keep_recent_tokens: 30000

  claude-opus-openrouter:
    name: Claude Opus 4.6 (OpenRouter)
    model: anthropic/claude-opus-4-6
    api_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    context_window: 200000
    reserve_tokens: 16384
    keep_recent_tokens: 30000
```

- [ ] **Step 2: Verify the file parses and the preamble round-trips correctly**

```
conda run -n dagi python -c "
from pathlib import Path
from agent.config_loader import resolve_model_config
cfg = resolve_model_config(config_path=Path('config_benchmark.yaml'))
print('preamble length:', len(cfg.system_prompt_preamble))
print('first line:', cfg.system_prompt_preamble.strip().splitlines()[0])
"
```
Expected output:
```
preamble length: <N>
first line: ## Harbor Benchmark Environment
```

- [ ] **Step 3: Verify `harbor_bash` survives `filter_to`**

The tools list in `config_benchmark.yaml` includes `harbor_bash`. `create_tool_registry` calls `reg.filter_to(config.tools)` after building the registry. Verify the tool survives:

```
conda run -n dagi python -c "
from pathlib import Path
from agent.config_loader import resolve_model_config
from agent.tools import create_tool_registry
from benchmarks.harbor.bash_tool import HarborBashTool

cfg = resolve_model_config(config_path=Path('config_benchmark.yaml'))
tool = HarborBashTool(exec_fn=lambda c, t: '')
reg = create_tool_registry(cwd=Path('.'), bash_tool=tool, config=cfg)
names = [n for n, _ in reg.list_tools()]
print('tools:', names)
assert 'harbor_bash' in names, 'harbor_bash filtered out!'
print('harbor_bash present: OK')
"
```
Expected: `harbor_bash` in the printed names

- [ ] **Step 4: Commit**

```
git add config_benchmark.yaml
git commit -m "feat: create config_benchmark.yaml with Harbor preamble and tool allowlist"
```

---

## Task 6: Update README, TODO, and PROJECT_CONTEXT

- [ ] **Step 1: Update README.md** — add a "Harbor benchmark" section under the benchmarks documentation noting: (a) set `DAGI_BENCH_MODEL`, (b) run `run_harbor.bat`, (c) that `harbor_bash` is the only container-access tool, (d) fix A/B are now in place.

- [ ] **Step 2: Update TODO.md** — mark any open Harbor harness items done; add "No full 89-task benchmark run yet" if not already present.

- [ ] **Step 3: Update PROJECT_CONTEXT.md** — add to Encountered Errors section:

  - **2026-06-13 Bug (Fix A)**: `config.project_path` pointed at Harbor's log dir → agent tried Windows file tools on container paths. Fix: `tempfile.mkdtemp()`.
  - **2026-06-13 Bug (Fix B)**: No Harbor environment context in system prompt → agent entered plan mode (stripping `harbor_bash`) and used wrong file tools. Fix: `system_prompt_preamble` field in `AgentConfig`, parsed from `config_benchmark.yaml`, injected first in preamble assembly.

- [ ] **Step 4: Commit docs**

```
git add README.md TODO.md PROJECT_CONTEXT.md
git commit -m "docs: document Harbor harness fixes A and B"
```

---

## Self-Review

**Spec coverage:**
- Fix A (project_path → tempdir): covered in Task 4 ✓
- Fix B (system_prompt_preamble): covered in Tasks 1–3 + 5 ✓
- `config_benchmark.yaml` creation: Task 5 ✓
- Plan mode strips `harbor_bash`: addressed by preamble instruction "Do NOT call `enter_plan_mode`" + the preamble appears before the rest of the system prompt ✓
- `enter_plan_mode` still strips bash tools in plan mode: not changed — the instruction is behavioral, not structural. A future structural fix would inject `harbor_bash` into the plan-mode tool registry, but that's scope creep for this plan.

**Placeholder scan:** No TBDs. All test code is complete. Config yaml is complete.

**Type consistency:** `system_prompt_preamble: str = ""` throughout — `AgentConfig`, `_build_config_from_entry`, `config.system_prompt_preamble` references in `loop.py`. All consistent.
