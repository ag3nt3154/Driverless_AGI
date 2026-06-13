# Per-Project Config & System Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each project to override dagi's config, system prompt, and persona via files in `{project_root}/.dagi/`, and route session logs to the project directory.

**Architecture:** `resolve_model_config` gains a `project_path` param and shallow-merges `{project_root}/.dagi/config.yaml` over the dagi root config. `AgentLoop.__init__` loads soul and system prompt via priority-ordered file lookup (project first, dagi root second). `SessionTracker` is already log-dir-aware — just wire `project_path/.dagi/logs` to it.

**Tech Stack:** Python 3.11+, PyYAML, pathlib. No new dependencies.

---

## File Map

| Action | Path | What changes |
|--------|------|--------------|
| Move   | `soul.md` → `.dagi/prompts/soul.md` | Relocate file; update load path in `loop.py` |
| Modify | `agent/prompts.py` | Add `load_main_system_prompt(dagi_root, project_path)` |
| Modify | `agent/config_loader.py` | `resolve_model_config` gets `project_path` param + merge logic |
| Modify | `agent/loop.py` | Soul path, prompt helper call, `logs_dir` wiring; remove module-level `DEFAULT_SYSTEM_PROMPT` |
| Modify | `cli.py` | Pass `project_path` to `resolve_model_config`; add `logs/` to `/init` dirs |
| Modify | `tui/app.py` | Pass `project_path` to `resolve_model_config` (2 call sites) |
| Modify | `tui/commands.py` | Pass `project_path` to `resolve_model_config` in `_cmd_model` |
| New    | `tests/test_project_config.py` | Tests for merge logic + prompt resolution |

---

## Task 1: Move soul.md into `.dagi/prompts/`

**Files:**
- Move: `soul.md` → `.dagi/prompts/soul.md`

- [ ] **Step 1: Copy the file**

```bash
cp soul.md .dagi/prompts/soul.md
```

Verify: `cat .dagi/prompts/soul.md` should show the Dagi-chan persona text.

- [ ] **Step 2: Delete the original**

```bash
git rm soul.md
```

- [ ] **Step 3: Commit**

```bash
git add .dagi/prompts/soul.md
git commit -m "refactor: move soul.md into .dagi/prompts/soul.md"
```

---

## Task 2: Add `load_main_system_prompt` to `agent/prompts.py`

**Files:**
- Modify: `agent/prompts.py`
- Test: `tests/test_project_config.py` (new file — write tests first)

- [ ] **Step 1: Write the failing test**

Create `tests/test_project_config.py`:

```python
"""Tests for per-project config + prompt resolution."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ── Prompt resolution ────────────────────────────────────────────────────────

def test_load_main_system_prompt_falls_back_to_dagi_root(tmp_path):
    """When no project prompt exists, load from dagi root."""
    from agent.prompts import load_main_system_prompt
    dagi_root = Path(__file__).parent.parent
    # tmp_path has no .dagi/prompts/main_system.md
    result = load_main_system_prompt(dagi_root, tmp_path)
    # Should be the real dagi system prompt (non-empty, contains known marker)
    assert "<<END_OF_RESPONSE>>" in result or "<<TASK_END>>" in result


def test_load_main_system_prompt_uses_project_prompt_when_present(tmp_path):
    """When project has a main_system.md, it fully replaces the dagi root prompt."""
    from agent.prompts import load_main_system_prompt
    project_prompt_dir = tmp_path / ".dagi" / "prompts"
    project_prompt_dir.mkdir(parents=True)
    (project_prompt_dir / "main_system.md").write_text(
        "Project-specific system prompt.\n{tools_and_skills}\n", encoding="utf-8"
    )
    dagi_root = Path(__file__).parent.parent
    result = load_main_system_prompt(dagi_root, tmp_path)
    assert result == "Project-specific system prompt.\n{tools_and_skills}\n"


def test_load_soul_falls_back_to_dagi_root(tmp_path):
    """When no project soul exists, load from dagi root .dagi/prompts/soul.md."""
    from agent.prompts import load_soul
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    # Dagi root soul contains "Dagi-chan" or is None if absent
    assert result is None or "Dagi-chan" in result


def test_load_soul_uses_project_soul_when_present(tmp_path):
    """Project .dagi/prompts/soul.md overrides dagi root soul."""
    from agent.prompts import load_soul
    soul_dir = tmp_path / ".dagi" / "prompts"
    soul_dir.mkdir(parents=True)
    (soul_dir / "soul.md").write_text("Custom project persona.\n", encoding="utf-8")
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    assert result == "Custom project persona.\n"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
conda run -n dagi pytest tests/test_project_config.py::test_load_main_system_prompt_falls_back_to_dagi_root tests/test_project_config.py::test_load_main_system_prompt_uses_project_prompt_when_present tests/test_project_config.py::test_load_soul_falls_back_to_dagi_root tests/test_project_config.py::test_load_soul_uses_project_soul_when_present -v
```

Expected: FAIL with `ImportError: cannot import name 'load_main_system_prompt'`

- [ ] **Step 3: Implement in `agent/prompts.py`**

Replace the entire file with:

```python
from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent.parent / ".dagi" / "prompts"
_SUBAGENTS_DIR = Path(__file__).parent.parent / ".dagi" / "subagents"


def load_prompt(name: str) -> str:
    """Load a prompt template from .dagi/prompts/<name>."""
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_subagent_prompt(name: str) -> str:
    """Load a system prompt from .dagi/subagents/<name>/prompt.md."""
    return (_SUBAGENTS_DIR / name / "prompt.md").read_text(encoding="utf-8")


def load_main_system_prompt(dagi_root: Path, project_path: Path) -> str:
    """Load the main system prompt, preferring project-local over dagi root."""
    project_prompt = project_path / ".dagi" / "prompts" / "main_system.md"
    if project_prompt.exists():
        return project_prompt.read_text(encoding="utf-8")
    return load_prompt("main/main_system.md")


def load_soul(dagi_root: Path, project_path: Path) -> str | None:
    """Load the soul/persona, preferring project-local over dagi root. Returns None if absent."""
    project_soul = project_path / ".dagi" / "prompts" / "soul.md"
    if project_soul.exists():
        return project_soul.read_text(encoding="utf-8")
    dagi_soul = dagi_root / ".dagi" / "prompts" / "soul.md"
    if dagi_soul.exists():
        return dagi_soul.read_text(encoding="utf-8")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
conda run -n dagi pytest tests/test_project_config.py::test_load_main_system_prompt_falls_back_to_dagi_root tests/test_project_config.py::test_load_main_system_prompt_uses_project_prompt_when_present tests/test_project_config.py::test_load_soul_falls_back_to_dagi_root tests/test_project_config.py::test_load_soul_uses_project_soul_when_present -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add agent/prompts.py tests/test_project_config.py
git commit -m "feat: add load_main_system_prompt and load_soul helpers with project-first resolution"
```

---

## Task 3: Project config merge in `agent/config_loader.py`

**Files:**
- Modify: `agent/config_loader.py`
- Test: `tests/test_project_config.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_project_config.py`:

```python
# ── Config merge ─────────────────────────────────────────────────────────────

def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_project_config_overrides_scalar_field(tmp_path, monkeypatch):
    """Project config scalars win over dagi root scalars."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
        default_model: root-model
        max_continuations: 10
        models:
          root-model:
            name: Root Model
            model: root/model
            api_url: http://root/v1
            api_key: root-key
    """)
    _write_yaml(tmp_path / ".dagi" / "config.yaml", """
        max_continuations: 3
    """)
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_continuations == 3


def test_project_config_model_catalog_merged(tmp_path, monkeypatch):
    """Project model catalog entries are added to root catalog."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
        default_model: root-model
        models:
          root-model:
            name: Root
            model: root/m
            api_url: http://root/v1
            api_key: rk
    """)
    _write_yaml(tmp_path / ".dagi" / "config.yaml", """
        default_model: fast-local
        models:
          fast-local:
            name: Local
            model: ollama/llama
            api_url: http://localhost:11434/v1
            api_key: ollama
    """)
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.model == "ollama/llama"
    assert cfg.base_url == "http://localhost:11434/v1"


def test_project_config_absent_uses_root(tmp_path, monkeypatch):
    """When no project config exists, root config is used unchanged."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
        default_model: root-model
        max_continuations: 7
        models:
          root-model:
            name: Root
            model: root/m
            api_url: http://root/v1
            api_key: rk
    """)
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_continuations == 7


def test_project_config_invalid_yaml_raises(tmp_path, monkeypatch):
    """Invalid YAML in project config surfaces a clear ValueError."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
        default_model: root-model
        models:
          root-model:
            name: Root
            model: root/m
            api_url: http://root/v1
            api_key: rk
    """)
    bad = tmp_path / ".dagi" / "config.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(": bad: yaml: [unclosed\n", encoding="utf-8")
    from agent.config_loader import resolve_model_config
    with pytest.raises(ValueError, match=".dagi/config.yaml"):
        resolve_model_config(project_path=tmp_path, config_path=root_cfg)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
conda run -n dagi pytest tests/test_project_config.py::test_project_config_overrides_scalar_field tests/test_project_config.py::test_project_config_model_catalog_merged tests/test_project_config.py::test_project_config_absent_uses_root tests/test_project_config.py::test_project_config_invalid_yaml_raises -v
```

Expected: FAIL with `TypeError: resolve_model_config() got unexpected keyword argument 'project_path'`

- [ ] **Step 3: Add `_load_project_config` and update `resolve_model_config`**

In `agent/config_loader.py`, add after `load_raw_config`:

```python
def _load_project_config(project_path: Path) -> dict | None:
    """Load project-level config from {project_path}/.dagi/config.yaml.

    Returns None if the file is absent. Raises ValueError on invalid YAML.
    """
    path = project_path / ".dagi" / "config.yaml"
    if not path.exists():
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc


def _merge_configs(root_raw: dict, project_raw: dict) -> dict:
    """Merge project_raw over root_raw. Model catalogs are shallow-merged (project wins).
    All other top-level scalar fields: project value wins when key is present.
    """
    merged = dict(root_raw)
    root_models: dict = root_raw.get("models", {})
    project_models: dict = project_raw.get("models", {})
    merged["models"] = {**root_models, **project_models}
    for key, value in project_raw.items():
        if key != "models":
            merged[key] = value
    return merged
```

Then update the signature and first lines of `resolve_model_config`:

```python
def resolve_model_config(
    model_id: str | None = None,
    config_path: Path | None = None,
    project_path: Path | None = None,
) -> AgentConfig:
    """
    Build an AgentConfig by looking up a model in the catalog.

    Resolution order:
      1. model_id argument (CLI --model or UI selectbox)
      2. default_model from config.yaml
      3. built-in fallback (gpt-4o-openai)

    config_path overrides the default config.yaml (e.g. pass config_benchmark.yaml
    for Terminal-bench runs).

    project_path, when provided, loads {project_path}/.dagi/config.yaml and
    merges it over the root config. Project values win on all scalar fields;
    model catalog entries are shallow-merged (project entries add or fully
    replace root entries).

    Raises
    ------
    KeyError        if the resolved model_id is not in the catalog.
    EnvironmentError if the required API key env var is not set.
    ValueError       if project .dagi/config.yaml contains invalid YAML.
    """
    raw = load_raw_config(config_path=config_path)
    if project_path is not None:
        project_raw = _load_project_config(project_path)
        if project_raw:
            raw = _merge_configs(raw, project_raw)
    # ... rest of the function unchanged from here ...
```

The rest of the function body (`catalog`, `chosen_id`, `entry`, `cfg`, worker/advanced resolution) is unchanged.

After the final `return replace(cfg, ...)` line, also set `project_path` on the config if provided:

```python
    if project_path is not None:
        cfg = replace(cfg, project_path=project_path)
    return replace(cfg, worker_config=worker_cfg, advanced_config=advanced_cfg)
```

Wait — `replace()` is called twice at the end. Combine into one:

```python
    final = replace(cfg, display_name=entry.get("name", chosen_id))
    if project_path is not None:
        final = replace(final, project_path=project_path)
    # worker / advanced resolution (unchanged)
    ...
    return replace(final, worker_config=worker_cfg, advanced_config=advanced_cfg)
```

> **Note:** The full updated function is shown in Step 4 below.

- [ ] **Step 4: Full updated `resolve_model_config`**

Replace the existing `resolve_model_config` function with:

```python
def resolve_model_config(
    model_id: str | None = None,
    config_path: Path | None = None,
    project_path: Path | None = None,
) -> AgentConfig:
    """
    Build an AgentConfig by looking up a model in the catalog.

    Resolution order:
      1. model_id argument (CLI --model or UI selectbox)
      2. default_model from config.yaml
      3. built-in fallback (gpt-4o-openai)

    config_path overrides the default config.yaml (e.g. pass config_benchmark.yaml
    for Terminal-bench runs).

    project_path, when provided, loads {project_path}/.dagi/config.yaml and
    merges it over the root config. Project values win on all scalar fields;
    model catalog entries are shallow-merged (project entries add or fully
    replace root entries).

    Raises
    ------
    KeyError        if the resolved model_id is not in the catalog.
    EnvironmentError if the required API key env var is not set.
    ValueError       if project .dagi/config.yaml contains invalid YAML.
    """
    raw = load_raw_config(config_path=config_path)
    if project_path is not None:
        project_raw = _load_project_config(project_path)
        if project_raw:
            raw = _merge_configs(raw, project_raw)

    catalog: dict = raw.get("models", {})

    chosen_id = model_id or raw.get("default_model") or _FALLBACK_MODEL_ID

    if catalog and chosen_id not in catalog:
        available = ", ".join(catalog.keys())
        raise KeyError(
            f"Model '{chosen_id}' not found in config.yaml.\n"
            f"Available model IDs: {available}"
        )

    entry = catalog.get(chosen_id, _FALLBACK_ENTRY)
    if not entry.get("api_key", ""):
        api_key_env = entry.get("api_key_env", "OPENAI_API_KEY")
        if not os.environ.get(api_key_env, ""):
            print(
                f"Warning: env var '{api_key_env}' is not set "
                f"(required for model '{chosen_id}'). "
                "Set it in .env or add api_key directly in config.yaml.",
                file=sys.stderr,
            )

    from dataclasses import replace

    cfg = _build_config_from_entry(entry, raw)
    cfg = replace(cfg, display_name=entry.get("name", chosen_id))
    if project_path is not None:
        cfg = replace(cfg, project_path=project_path)

    worker_id = raw.get("worker_model")
    worker_cfg: AgentConfig | None = None
    if worker_id and worker_id in catalog:
        worker_cfg = _build_config_from_entry(catalog[worker_id], raw)
        worker_cfg = replace(worker_cfg, display_name=catalog[worker_id].get("name", worker_id))

    advanced_id = raw.get("advanced_model")
    advanced_cfg: AgentConfig | None = None
    if advanced_id and advanced_id in catalog:
        advanced_cfg = _build_config_from_entry(catalog[advanced_id], raw)
        advanced_cfg = replace(advanced_cfg, display_name=catalog[advanced_id].get("name", advanced_id))

    return replace(cfg, worker_config=worker_cfg, advanced_config=advanced_cfg)
```

- [ ] **Step 5: Run the config merge tests**

```bash
conda run -n dagi pytest tests/test_project_config.py::test_project_config_overrides_scalar_field tests/test_project_config.py::test_project_config_model_catalog_merged tests/test_project_config.py::test_project_config_absent_uses_root tests/test_project_config.py::test_project_config_invalid_yaml_raises -v
```

Expected: 4 PASSED

- [ ] **Step 6: Run existing config loader tests to catch regressions**

```bash
conda run -n dagi pytest tests/test_config_loader.py -v
```

Expected: all PASSED (they test `_build_config_from_entry` directly — unaffected)

- [ ] **Step 7: Commit**

```bash
git add agent/config_loader.py tests/test_project_config.py
git commit -m "feat: project config merge — resolve_model_config loads .dagi/config.yaml and merges over root"
```

---

## Task 4: Wire `project_path` into `resolve_model_config` at entry points

**Files:**
- Modify: `cli.py` (2 call sites)
- Modify: `tui/app.py` (2 call sites)
- Modify: `tui/commands.py` (1 call site)

The goal: pass `project_path` to `resolve_model_config` so it performs the merge, and remove the subsequent manual `config.project_path = project_path` assignments (since `resolve_model_config` now sets it).

- [ ] **Step 1: Update `cli.py` — `_run_task` function (around line 451)**

Find:
```python
    config = resolve_model_config(model_id)
    config.project_path = project_path
```

Replace with:
```python
    config = resolve_model_config(model_id, project_path=project_path)
```

- [ ] **Step 2: Update `cli.py` — subagent path (around line 1063)**

Find:
```python
    base_config = resolve_model_config(model)
    base_config.project_path = project_path
```

Replace with:
```python
    base_config = resolve_model_config(model, project_path=project_path)
```

- [ ] **Step 3: Update `tui/app.py` — `compose` method (line 51)**

Find:
```python
        cfg = resolve_model_config(self._model_id)
```

Replace with:
```python
        cfg = resolve_model_config(self._model_id, project_path=self._project_path)
```

- [ ] **Step 4: Update `tui/app.py` — `on_mount` method (line 63)**

Find:
```python
        self._config = resolve_model_config(self._model_id)
        self._config.project_path = self._project_path
```

Replace with:
```python
        self._config = resolve_model_config(self._model_id, project_path=self._project_path)
```

- [ ] **Step 5: Update `tui/commands.py` — `_cmd_model` method (line 114)**

Find:
```python
        self._config = resolve_model_config(arg)
        self._config.project_path = self._project_path
```

Replace with:
```python
        self._config = resolve_model_config(arg, project_path=self._project_path)
```

- [ ] **Step 6: Run the full test suite to catch regressions**

```bash
conda run -n dagi pytest tests/ -v
```

Expected: all existing tests PASSED, plus new tests from Task 2/3.

- [ ] **Step 7: Commit**

```bash
git add cli.py tui/app.py tui/commands.py
git commit -m "feat: thread project_path into resolve_model_config at all entry points"
```

---

## Task 5: Update `agent/loop.py` — soul, system prompt, logs

**Files:**
- Modify: `agent/loop.py`

This task has three sub-changes:
1. Remove module-level `DEFAULT_SYSTEM_PROMPT` constant (load at `__init__` time instead)
2. Update soul loading to use `load_soul()` helper (project first, dagi root second)
3. Wire `logs_dir=config.project_path / ".dagi" / "logs"` into `SessionTracker`

- [ ] **Step 1: Update imports at top of `agent/loop.py`**

Find the existing import:
```python
from agent.prompts import load_prompt
```

Replace with:
```python
from agent.prompts import load_prompt, load_main_system_prompt, load_soul
```

- [ ] **Step 2: Remove `DEFAULT_SYSTEM_PROMPT` module-level constant and update `AgentConfig.system_prompt` default**

Find:
```python
DEFAULT_SYSTEM_PROMPT = load_prompt("main/main_system.md")
CONTINUE_PROMPT = load_prompt("main/continue.md")
```

Replace with:
```python
CONTINUE_PROMPT = load_prompt("main/continue.md")
```

Then find in `AgentConfig`:
```python
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
```

Replace with:
```python
    system_prompt: str = ""  # loaded from files at AgentLoop init time if empty
```

- [ ] **Step 3: Update soul loading in `AgentLoop.__init__`**

Find the soul-loading block (around line 265):
```python
        # Load preamble: dagi root soul + .dagi/agents.md, then project .dagi/agents.md
        preamble_parts: list[str] = []
        dagi_soul = dagi_root / "soul.md"
        if dagi_soul.exists():
            preamble_parts.append(dagi_soul.read_text(encoding="utf-8").strip())
```

Replace the `dagi_soul` lines with:
```python
        # Load preamble: soul (project first, dagi root fallback), then agents.md files
        preamble_parts: list[str] = []
        soul_text = load_soul(dagi_root, config.project_path)
        if soul_text:
            preamble_parts.append(soul_text.strip())
```

Also find the `system_parts` block that references `dagi_soul` (around line 289):
```python
        if dagi_soul.exists():
            self.system_parts.append({"label": "SOUL.md", "content": dagi_soul.read_text(encoding="utf-8").strip()})
```

Replace with:
```python
        if soul_text:
            self.system_parts.append({"label": "SOUL.md", "content": soul_text.strip()})
```

- [ ] **Step 4: Update system prompt loading in `AgentLoop.__init__`**

Find the line that builds `prompt` from `config.system_prompt`:
```python
        prompt = config.system_prompt.format_map(_SafeDict(
```

Replace the lines before it that load `DEFAULT_SYSTEM_PROMPT` (there is no explicit load — `config.system_prompt` carried the value). Now add the conditional load:

```python
        system_prompt_text = (
            config.system_prompt
            if config.system_prompt
            else load_main_system_prompt(dagi_root, config.project_path)
        )
        prompt = system_prompt_text.format_map(_SafeDict(
```

- [ ] **Step 5: Wire `logs_dir` into `SessionTracker`**

Find the `SessionTracker` construction (around line 220):
```python
            self.tracker = SessionTracker(model=config.model, thread_id=config.thread_id)
```

Replace with:
```python
            self.tracker = SessionTracker(
                model=config.model,
                thread_id=config.thread_id,
                logs_dir=config.project_path / ".dagi" / "logs",
            )
```

- [ ] **Step 6: Run the full test suite**

```bash
conda run -n dagi pytest tests/ -v
```

Expected: all PASSED. The continuation tests use `system_prompt="You are a test agent."` explicitly — they bypass the file load path (non-empty `system_prompt` is used as-is). ✓

- [ ] **Step 7: Commit**

```bash
git add agent/loop.py
git commit -m "feat: project-aware soul, system prompt, and session log routing in AgentLoop"
```

---

## Task 6: Add `logs/` to `/init` command

**Files:**
- Modify: `cli.py` (`_cmd_init` function, around line 589)

- [ ] **Step 1: Add `logs/` to the directory list in `_cmd_init`**

Find:
```python
    for d in [
        dagi_dir / "skills",
        dagi_dir / "workflow",
        dagi_dir / "self-review",
        memory / "raw",
```

Replace with:
```python
    for d in [
        dagi_dir / "skills",
        dagi_dir / "workflow",
        dagi_dir / "self-review",
        dagi_dir / "logs",
        memory / "raw",
```

- [ ] **Step 2: Verify manually**

```bash
conda run -n dagi python -c "
from pathlib import Path
import tempfile, sys
sys.argv = ['cli']
with tempfile.TemporaryDirectory() as d:
    from cli import _cmd_init
    _cmd_init(Path(d))
    logs = Path(d) / '.dagi' / 'logs'
    print('logs created:', logs.exists())
"
```

Expected output: `logs created: True`

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat: /init creates .dagi/logs/ directory"
```

---

## Task 7: Verify end-to-end + add project config docs to `config.example.yaml`

**Files:**
- Modify: `config.example.yaml` (add per-project config notes)

- [ ] **Step 1: Run the full test suite one final time**

```bash
conda run -n dagi pytest tests/ -v
```

Expected: all PASSED

- [ ] **Step 2: Add per-project config documentation to `config.example.yaml`**

At the top of `config.example.yaml`, add a comment block:

```yaml
# Per-project config: place a .dagi/config.yaml in any project directory.
# Fields present in the project config override the corresponding fields here.
# The models: block is shallow-merged — project entries add to or fully replace
# root entries. All other fields (max_continuations, tools, etc.) are scalars
# that the project value wins when present.
#
# Example project .dagi/config.yaml:
#   default_model: fast-local
#   max_continuations: 5
#   tools:
#     - read
#     - write
#     - bash
#   models:
#     fast-local:
#       name: "Local Ollama"
#       model: "llama3.2"
#       api_url: "http://localhost:11434/v1"
#       api_key: "ollama"
```

- [ ] **Step 3: Update `.gitignore` to ignore project `.dagi/config.yaml` if it contains API keys**

Add to `.gitignore`:
```
# Project-level dagi config (may contain API keys)
.dagi/config.yaml
```

But check if `.dagi/` is already ignored:

```bash
grep -n "\.dagi" .gitignore
```

If `.dagi/` is broadly ignored, no change needed. If not, add just `.dagi/config.yaml`.

- [ ] **Step 4: Commit**

```bash
git add config.example.yaml .gitignore
git commit -m "docs: document per-project config in config.example.yaml; update .gitignore"
```

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|-------------|------|
| Move soul.md → .dagi/prompts/soul.md | Task 1 ✓ |
| Projects can override soul (project first, dagi root fallback) | Task 2 (`load_soul`) ✓ |
| Projects can have .dagi/prompts/main_system.md (full replace) | Task 2 (`load_main_system_prompt`) ✓ |
| Projects can have .dagi/config.yaml (field-level merge) | Task 3 ✓ |
| Model catalog shallow-merge | Task 3 ✓ |
| Session logs → {project_root}/.dagi/logs | Task 5 ✓ |
| /init creates logs/ subfolder | Task 6 ✓ |
| Backwards compat (no project config = unchanged behavior) | Task 3, test `test_project_config_absent_uses_root` ✓ |

**Placeholder scan:** No TBDs found. All code blocks are complete.

**Type consistency check:**
- `load_soul(dagi_root, project_path) -> str | None` — used as `soul_text = load_soul(...)` and `if soul_text:` in Task 5 ✓
- `load_main_system_prompt(dagi_root, project_path) -> str` — used as `load_main_system_prompt(dagi_root, config.project_path)` in Task 5 ✓
- `_load_project_config(project_path) -> dict | None` — checked with `if project_raw:` in Task 3 ✓
- `_merge_configs(root_raw, project_raw) -> dict` — used as `raw = _merge_configs(raw, project_raw)` in Task 3 ✓
- `resolve_model_config(model_id, config_path, project_path) -> AgentConfig` — all call sites updated in Task 4 ✓
