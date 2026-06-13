# Per-Project Config & System Prompt Design

> Created: 2026-06-13  
> Status: Approved  
> Scope: `soul.md` relocation, per-project config.yaml, per-project system prompt, project-local session logs

---

## Problem Statement

Dagi currently has no way to customise config, system prompt, or persona for individual projects. All settings are global (dagi root). This makes it impossible to, e.g., restrict tools for a sensitive repo, run a lighter model for a quick scripting project, or give an agent a project-specific persona.

---

## Goals

1. Move `soul.md` into `.dagi/prompts/` (housekeeping + enables per-project override)
2. Projects can provide `.dagi/config.yaml` that overrides fields from dagi root's `config.yaml`
3. Projects can provide `.dagi/prompts/main_system.md` as a full replacement system prompt
4. Projects can provide `.dagi/prompts/soul.md` as a persona override
5. Session logs save to `{project_root}/.dagi/logs/` instead of dagi root's `.dagi/logs/`
6. `/init` command creates the `logs/` subdirectory in `.dagi/`

---

## Non-Goals

- Adding a `--project` CLI flag (CWD remains the project discovery mechanism)
- Deep per-field model entry merging (whole entry wins, not individual fields)
- Changing subagent config resolution

---

## File Layout

```
{dagi_root}/
├── .dagi/
│   ├── prompts/
│   │   ├── soul.md              ← MOVED from root soul.md
│   │   ├── main/
│   │   │   ├── main_system.md
│   │   │   └── continue.md
│   │   ├── compact/
│   │   └── (subagent prompts loaded separately)
│   └── logs/                   ← dagi's own dev sessions (when CWD = dagi root)
├── config.yaml                  ← unchanged
└── soul.md                      ← DELETED after move

{project_root}/
└── .dagi/
    ├── config.yaml              ← NEW optional: project overrides
    ├── prompts/
    │   ├── soul.md              ← NEW optional: project persona (overrides dagi root soul)
    │   └── main_system.md       ← NEW optional: full replacement system prompt
    ├── logs/                    ← NEW: all session logs written here
    ├── skills/
    └── agents.md
```

---

## Architecture

### New file: `agent/project.py`

Thin dataclass owning "where do I find things?" knowledge.

```python
@dataclass
class ProjectContext:
    dagi_root: Path      # always the dagi installation directory
    project_path: Path   # CWD at launch time
```

No logic beyond holding the two paths. Used internally to pass both roots cleanly without changing every function signature.

---

### Config Merge (`agent/config_loader.py`)

`resolve_model_config(model_id, config_path, project_path)` gains a new optional `project_path: Path | None` parameter.

**Merge algorithm:**

1. Load dagi root `config.yaml` → `root_raw: dict`
2. If `{project_path}/.dagi/config.yaml` exists, load it → `project_raw: dict`
3. Merge:
   - `models:` block → `{**root_raw["models"], **project_raw.get("models", {})}` — project entries win; project can add new model IDs or fully replace existing ones
   - All other scalar keys → project value wins if key present in `project_raw`, else root value used
   - `default_model` → project value takes precedence if set
4. Build `AgentConfig` from merged dict as normal

**Example project `.dagi/config.yaml`:**
```yaml
default_model: fast-local
max_continuations: 5
tools:
  - read
  - write
  - bash
models:
  fast-local:
    name: "Local Ollama"
    model: "llama3.2"
    api_url: "http://localhost:11434/v1"
    api_key: "ollama"
```

---

### Soul Resolution (`agent/loop.py`)

Priority order (first match wins):

```
1. {project_root}/.dagi/prompts/soul.md    ← project persona
2. {dagi_root}/.dagi/prompts/soul.md       ← dagi global persona (moved from root soul.md)
3. (absent)                                 ← skip gracefully
```

---

### System Prompt Resolution (`agent/prompts.py` + `agent/loop.py`)

New helper in `agent/prompts.py`:

```python
def load_main_system_prompt(dagi_root: Path, project_path: Path) -> str:
    project_prompt = project_path / ".dagi" / "prompts" / "main_system.md"
    if project_prompt.exists():
        return project_prompt.read_text(encoding="utf-8")
    return load_prompt("main/main_system.md")  # dagi root fallback
```

`DEFAULT_SYSTEM_PROMPT` module-level constant in `loop.py` is removed. The prompt is loaded inside `AgentLoop.__init__` via the helper above, using `config.project_path` and the resolved `dagi_root`.

The `AgentConfig.system_prompt` field default is kept as `""` (empty string) — `AgentLoop.__init__` always overwrites it from the resolved file.

---

### Session Logs (`agent/loop.py`)

`AgentLoop.__init__` passes `logs_dir` to `SessionTracker`:

```python
self.tracker = SessionTracker(
    model=config.model,
    thread_id=config.thread_id,
    logs_dir=config.project_path / ".dagi" / "logs",
)
```

`SessionTracker` already accepts `logs_dir` and creates the directory if absent — no changes needed there.

---

### `/init` Command (`cli.py:_cmd_init`)

Add `dagi_dir / "logs"` to the list of directories created:

```python
for d in [
    dagi_dir / "skills",
    dagi_dir / "workflow",
    dagi_dir / "self-review",
    dagi_dir / "logs",          # ← NEW
    memory / "raw",
    ...
]:
    d.mkdir(parents=True, exist_ok=True)
```

---

### Entry Point Wiring

`tui/app.py` and `cli.py` already have `project_path` (as `self._project_path` / local var). Both pass it to `resolve_model_config`:

```python
config = resolve_model_config(model_id, project_path=project_path)
```

---

## Files Changed

| File | Change |
|------|--------|
| `soul.md` | Deleted (content moved to `.dagi/prompts/soul.md`) |
| `.dagi/prompts/soul.md` | NEW — moved content from `soul.md` |
| `agent/project.py` | NEW — `ProjectContext` dataclass |
| `agent/prompts.py` | Add `load_main_system_prompt(dagi_root, project_path)` |
| `agent/config_loader.py` | `resolve_model_config` gets `project_path` param; add project config load + merge |
| `agent/loop.py` | Soul path updated; prompt loaded via new helper; `logs_dir` wired to `SessionTracker`; remove `DEFAULT_SYSTEM_PROMPT` module-level constant |
| `cli.py` | Pass `project_path` to `resolve_model_config`; add `logs/` to `/init` dirs |
| `tui/app.py` | Pass `project_path` to `resolve_model_config` |

---

## Error Handling

- Missing project `.dagi/config.yaml` → silently skipped, dagi root config used
- Missing project soul / system prompt → silently fall through to dagi root equivalents
- Invalid YAML in project config → surface as `ValueError` with clear message including path
- `logs/` dir creation: already handled by `SessionTracker.mkdir(parents=True, exist_ok=True)`

---

## Backwards Compatibility

- Existing projects without `.dagi/config.yaml` or `.dagi/prompts/` are unaffected
- `soul.md` at dagi root is deleted — no backwards compat needed (it's an internal file, not a user file)
- `DEFAULT_SYSTEM_PROMPT` constant in `loop.py` is only used internally — removal is safe
- `resolve_model_config` signature change is additive (new optional param with default `None`)
