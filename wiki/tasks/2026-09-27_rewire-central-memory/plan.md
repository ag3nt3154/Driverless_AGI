# Rewire DAGI & Codex to the Central Memory Wiki — Implementation Plan

**Goal:** Make DAGI and Codex use `G:\My Drive\black_grimoire\wiki` exactly as Claude Code
does, and remove the memory subagents, the per-project knowledge wiki and the repo's Codex
package.

**Architecture:**
- A single `resolve_memory_root()` default feeds every memory path.
- A per-turn `[MEMORY]` pointer names the store and the project folder.
- The main agent runs the `memory-add`/`memory-query` skills inline, using its own
  grep/read/write tools.
- `/init` creates only an AGENTS.md and `wiki/tasks/`.

**Tech Stack:** Python 3 (conda env `dagi`), pytest; markdown skills.

**Spec:** `wiki/tasks/2026-09-27_rewire-central-memory/spec.md`

## Global Constraints
- Test command:
  `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt -p no:cacheprovider`.
  Baseline: 1382 passed, 1 skipped.
- Functions ≤100 lines; cyclomatic complexity ≤8; ≤5 positional parameters; lines ≤100
  characters.
- `DEFAULT_MEMORY_ROOT = Path(r"G:\My Drive\black_grimoire")`. The wiki is `<root>\wiki`.
- Never edit the historical paths: `.superpowers/`, `docs/superpowers/`, `snapshots/`,
  `_todo/`, `.dagi/plans/`, `.dagi/self-review/`, `.dagi/handoffs/`,
  `.dagi/scripts/migrate_wiki.py`, `new_skills_planning.md`, `SUBAGENT_REPORT_*.md`.
- Never touch `memory-refresh` (skill, subagent, scripts), except removing `memory_refresh`
  from the enabled tool lists.
- Task artifacts stay at `wiki/tasks/YYYY-MM-DD_<task>/`.
- Before editing anything outside the repo (`~/.codex`), back it up to
  `wiki/tasks/2026-09-27_rewire-central-memory/backup/codex/`.

## Review Focus
1. **Project folder names with spaces, dots or leading/trailing punctuation**
   (`My Proj.v2_`). Expected: a clean kebab slug (`my-proj-v2`), never empty (use
   `project` for an all-punctuation name). Tested in Subtask 1.
2. **Config `memory_root` given as a relative or `~` path.** Expected: resolved to an
   absolute path, same as today (`config_loader` already calls `expanduser`). Tested in
   Subtask 1.
3. **A user's existing `wiki/` from an old `/init`.** Expected: a new `/init` never deletes
   or overwrites it; it only adds a missing `wiki/tasks/README.md`. Tested in Subtask 3.
4. **The subagent `root: memory_root` fallback when `memory_root` is `None`.** Expected: it
   resolves to the default, not `<project>/dagi-memory`. Tested in Subtask 1.
5. **Skill loader behaviour after `.dagi/skills/wiki-*` is deleted** (a `reload_skills`
   notification lists them as removed without an error). Covered by the existing reload tests
   plus the full suite in Subtask 7.

---

### Subtask 1: Memory root default and `[MEMORY]` pointer
**Goal:** One resolved default for the memory root, and a pointer naming the store and the
project folder.

**Requirements:** spec R1, R2.

**Acceptance Criteria:**
- The new tests pass.
- There is no `dagi-memory` fallback left in `agent/` or `tools/skill/_skill.py`.
- `_build_wiki_index_context` no longer exists anywhere in `agent/` or `tests/`.

**Files:**
- Modify:
  - `agent/_loop_config.py` (the `memory_root` comment block, lines 42–44; add the constant
    and function);
  - `agent/_loop_helpers.py` (replace `_build_wiki_index_context`);
  - `agent/loop.py` (import at 43; fallback at 101–104; call at 568);
  - `agent/tools.py:217,246`;
  - `agent/subagent_tools.py:196-199`;
  - `tools/skill/_skill.py:80`;
  - `config.example.yaml:92`;
  - `.dagi/config.yaml:21-23`.
- Test: `tests/test_loop_helpers.py`, `tests/test_memory_root.py` (new),
  `tests/test_subagent_main.py:1035` (patch target rename).

**Interfaces — Produces:**
- `agent._loop_config.DEFAULT_MEMORY_ROOT: Path`
- `agent._loop_config.resolve_memory_root(configured: Path | None) -> Path`
- `agent._loop_helpers.project_slug(project_path: Path) -> str`
- `agent._loop_helpers._build_memory_context(memory_root: Path, project_path: Path) -> str | None`

- [x] **Step 1: Write the failing tests**
```python
# tests/test_memory_root.py
from pathlib import Path

import agent._loop_config as lc
from agent._loop_config import resolve_memory_root
from agent._loop_helpers import _build_memory_context, project_slug


def test_resolve_memory_root_defaults_and_overrides(tmp_path):
    # lc.DEFAULT_MEMORY_ROOT is patched by the autouse conftest fixture; read it via the module.
    assert resolve_memory_root(None) == lc.DEFAULT_MEMORY_ROOT.resolve()
    assert resolve_memory_root(tmp_path) == tmp_path.resolve()


def test_resolve_memory_root_makes_relative_absolute():
    assert resolve_memory_root(Path("rel")).is_absolute()


def test_project_slug():
    assert project_slug(Path("C:/x/Driverless_AGI")) == "driverless-agi"
    assert project_slug(Path("/x/My Proj.v2_")) == "my-proj-v2"
    assert project_slug(Path("/x/hedgefundie")) == "hedgefundie"
    assert project_slug(Path("/x/___")) == "project"


def test_memory_context_missing_wiki_returns_none(tmp_path):
    assert _build_memory_context(tmp_path, tmp_path / "Proj") is None


def test_memory_context_names_store_and_project(tmp_path):
    (tmp_path / "wiki").mkdir()
    text = _build_memory_context(tmp_path, Path("/x/Driverless_AGI"))
    assert text.startswith("[MEMORY]\n") and text.endswith("[END MEMORY]")
    assert str(tmp_path / "wiki") in text
    assert "projects/driverless-agi/" in text
    assert "memory-query" in text and "memory-add" in text
```
In `tests/test_loop_helpers.py`:
- change the import from `_build_wiki_index_context` to `_build_memory_context`;
- replace `test_build_wiki_index_context_missing` with:
```python
def test_build_memory_context_missing(tmp_path):
    assert _build_memory_context(tmp_path, tmp_path) is None
```
In `tests/test_subagent_main.py:1035`, change the patch target to
`"agent.loop._build_memory_context"`.

**Test isolation (review #1, blocking finding 2).** `G:\My Drive\black_grimoire\wiki`
exists on this machine, so the new default would inject `[MEMORY]` into every test that
builds `AgentConfig` without `memory_root`. This breaks 7 existing tests, including
`test_agent_loop.py::TestParentForkCapture::*`, `test_loop_image_integration.py::…
test_text_only_message_shape_is_unchanged_string` and `test_session_log_shadow.py::*`.

Add an **autouse** fixture to `tests/conftest.py` that isolates every test from the real
store:
```python
@pytest.fixture(autouse=True)
def _isolate_memory_root(monkeypatch, tmp_path_factory):
    """Tests never see the real central memory store (it exists on the dev machine)."""
    import agent._loop_config as lc
    monkeypatch.setattr(lc, "DEFAULT_MEMORY_ROOT", tmp_path_factory.mktemp("memroot"))
```
`resolve_memory_root` must read the module global at call time (as written above), so the
patch takes effect. Add one test that pins the real default constant:
```python
def test_default_memory_root_constant_is_the_vault():
    import inspect  # the value is patched in tests, so pin the source constant instead
    assert r'Path(r"G:\My Drive\black_grimoire")' in inspect.getsource(lc)
```
and adjust `test_resolve_memory_root_defaults_and_overrides` to compare against
`agent._loop_config.DEFAULT_MEMORY_ROOT` (the patched one) via module attribute access.

Add to `tests/test_memory_root.py` an **AgentLoop default test** (AC1):
- build an `AgentLoop` exactly as `tests/test_subagent_main.py:1015-1030` does
  (`AgentConfig(api_key="test", project_path=tmp_path, system_prompt="x")`, with `memory_root`
  omitted; pass a `_registry` and patch `openai.OpenAI`);
- assert `loop._effective_memory_root == agent._loop_config.DEFAULT_MEMORY_ROOT.resolve()`.

Add a **subagent fallback test** (Review Focus 4). The real signature is
`build_subagent_registry(subagent_type, config, project_path, callbacks=None,
tracker=None, memory_root=None, handoff_path=None, tool_names_override=None)`
(`agent/subagent_tools.py:158`):
```python
def test_subagent_memory_root_fallback_uses_default(monkeypatch, tmp_path):
    from unittest.mock import MagicMock
    import agent._loop_config as lc
    import agent.subagent_tools as st
    monkeypatch.setattr(st, "_load_subagent_config",
                        lambda *a, **k: {"root": "memory_root", "tools": ["read"]})
    config = MagicMock(sandbox_mode=False)  # only attribute read (subagent_tools.py:185)
    reg = st.build_subagent_registry("memory-refresh", config, tmp_path, memory_root=None)
    expected = lc.DEFAULT_MEMORY_ROOT.resolve()
    read_tool = reg.get("read")
    assert read_tool.cwd == expected                # today: <project>/<legacy dir> → fails first
    assert read_tool.allowed_roots == [expected]
```
(Review #2 verified that `reg.get("read").cwd` and `.allowed_roots` show the scoped root.)

- [x] **Step 2: Run to confirm failure.**
  `...python.exe -u -m pytest -q -p no:pytest-qt tests/test_memory_root.py tests/test_loop_helpers.py`
  → ImportError.

- [x] **Step 3: Implement.**
`agent/_loop_config.py` (module level, near the imports):
```python
DEFAULT_MEMORY_ROOT = Path(r"G:\My Drive\black_grimoire")


def resolve_memory_root(configured: Path | None) -> Path:
    """Central memory store root: configured value, else the machine default."""
    return (configured if configured is not None else DEFAULT_MEMORY_ROOT).resolve()
```
Replace the field comment with:
`# Memory root — central memory store (contains wiki/). None → DEFAULT_MEMORY_ROOT.`

`agent/_loop_helpers.py`: replace `_build_wiki_index_context` with
```python
def project_slug(project_path: Path) -> str:
    """Kebab-case project folder name, matching wiki/projects/<slug>/."""
    slug = re.sub(r"[^a-z0-9]+", "-", project_path.name.lower()).strip("-")
    return slug or "project"


def _build_memory_context(memory_root: Path, project_path: Path) -> str | None:
    """Short, static per-project pointer to the central memory wiki."""
    wiki_root = memory_root / "wiki"
    if not wiki_root.exists():
        return None
    return (
        "[MEMORY]\n"
        f"Memory wiki: {wiki_root}\n"
        f"This project: projects/{project_slug(project_path)}/  — search with memory-query "
        "at task start and before debugging; file with memory-add.\n"
        "[END MEMORY]"
    )
```
(add `import re`).

`agent/loop.py`:
- import `_build_memory_context` in place of `_build_wiki_index_context`;
- lines 101–104 become
  `self._effective_memory_root = resolve_memory_root(config.memory_root)` (import from
  `agent._loop_config`);
- line 568 becomes
  `wiki_ctx = _build_memory_context(self._effective_memory_root, self.config.project_path)`.
  Keep the log source label `"wiki"` unchanged, so the session-log format is stable.

`agent/tools.py:217,246`: `_effective_memory_root = resolve_memory_root(memory_root)`.

`agent/subagent_tools.py:196-199`: `wiki_root = resolve_memory_root(memory_root)`, imported
at module level so the test can monkeypatch it.

`tools/skill/_skill.py:80`:
`memory_root_str = str(resolve_memory_root(self._memory_root))`.

`config.example.yaml:92`:
```yaml
# Central memory store (contains wiki/). Optional — defaults to G:\My Drive\black_grimoire.
# memory_root: /absolute/path/to/black_grimoire
```
`.dagi/config.yaml:21-23`:
```yaml
# Central memory store (contains wiki/). Omit to use the built-in default.
memory_root: "G:\\My Drive\\black_grimoire"
```
Also:
- wrap the new `loop.py:568` call to stay ≤100 characters;
- update the `_loop_helpers.py` module docstring, since `agent/_init_templates.py` now imports
  `project_slug` too.

- [x] **Step 4:** Run the tests from Step 2 plus `tests/test_subagent_main.py`,
  `tests/test_system_prompt.py`, `tests/test_agent_loop.py`,
  `tests/test_loop_image_integration.py` and `tests/test_session_log_shadow.py` → PASS.
- [x] **Step 5:** Return for review.

---

### Subtask 2: Remove the memory and wiki subagents
**Goal:** Delete the four subagent tools and the wiki tool module; disable `memory_refresh`.

**Requirements:** spec R3.

**Acceptance Criteria:**
- The directories and files below are gone.
- The registry tests pass with the updated expected sets.
- `grep -rnE "memory_add|memory_query|wiki_query|wiki_add|memory_refresh" .dagi/config.yaml benchmarks/dagi_eval/config_dagi_eval.yaml`
  → no hits.

**Files:**
- Delete (`git rm -r`): `.dagi/subagents/memory-add/`, `.dagi/subagents/memory-query/`,
  `.dagi/subagents/wiki-add/`, `.dagi/subagents/wiki-query/`, `tools/_wiki_tools.py`,
  `tests/test_wiki_tools.py`.
- Modify:
  - `.dagi/config.yaml` (remove the lines for `memory_add`, `memory_query`,
    `memory_refresh`, `wiki_query` and `wiki_add` from `tools:`);
  - `benchmarks/dagi_eval/config_dagi_eval.yaml` (remove the `memory_add` and
    `memory_query` lines);
  - `tests/test_subagent_configs.py` (remove `"wiki-query"`, `"wiki-add"`, `"memory-add"`
    and `"memory-query"` from `TYPED_SUBAGENT_NAMES`; keep `"memory-refresh"`);
  - `tests/test_subagent_tools_new.py` (remove the same four keys from
    `_EXPECTED_TOOL_NAMES` and the `memory-add` branch in `_run_with_minimal_arguments`);
  - `tests/test_subagent_configs.py:93-101`: delete
    `test_wiki_presets_have_only_file_tools_and_no_parent_instructions`, which reads the
    removed wiki-* configs;
  - `.dagi/config.yaml`: also add `memory_refresh` to `disabled_tools:` (create the key if
    absent). This keeps it off even for project configs that omit `tools:`. First check that
    `disabled_tools` is honoured from the base config (`agent/tools.py`, `config_loader.py`);
    if it isn't, report that and rely on the `tools:` removal.
- After `git rm`, also `rm -rf` the left-over git-ignored `__pycache__/` in the four deleted
  subagent dirs.

- [x] **Step 1:** Update both test files first, then run them → FAIL, because the
  directories still exist and the discovery set mismatches.
- [x] **Step 2:** Delete the files and edit the configs.
- [x] **Step 3:** Run `tests/test_subagent_configs.py tests/test_subagent_tools_new.py`,
  then the full suite → PASS. If any other module imports `tools._wiki_tools` or the
  subagent folders, fix the import and report it.
- [x] **Step 4:** Return for review.

---

### Subtask 3: Slim `/init`
**Goal:** `/init` creates only a slim AGENTS.md and `wiki/tasks/README.md`.

**Requirements:** spec R6.

**Acceptance Criteria:** the rewritten `tests/test_project_init.py` passes.

**Files:**
- Modify: `agent/_init_templates.py` (full rewrite), `agent/cli_utils.py` (the "Next:" hint,
  about lines 50–55), `tests/test_project_init.py` (rewrite).

**Interfaces:** `build_init_files(project_name: str, today: str) -> dict[str, str]`, same
signature; it returns exactly the keys `{"AGENTS.md", "wiki/tasks/README.md"}`.

- [x] **Step 1: Rewrite the tests**
```python
"""Initialization creates a slim briefing and the task-artifact folder, never overwriting."""
import pytest

from agent._loop_helpers import project_slug
from agent.cli_utils import _cmd_init

EXPECTED = {"AGENTS.md", "wiki/tasks/README.md"}


def _files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and ".dagi" not in p.relative_to(root).parts}


def test_init_creates_exactly_briefing_and_tasks_readme(tmp_path):
    _cmd_init(tmp_path)
    assert _files(tmp_path) == EXPECTED
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    for heading in ("## Overview", "## Rules", "## Commands & Environment", "## Memory"):
        assert heading in agents
    assert "memory-query" in agents and "memory-add" in agents
    assert f"projects\\{project_slug(tmp_path)}\\" in agents
    for name in ("skills", "workflow", "self-review", "logs"):
        assert (tmp_path / ".dagi" / name).is_dir()


def test_init_repeat_preserves_all_file_bytes(tmp_path):
    _cmd_init(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    _cmd_init(tmp_path)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize("content", [b"", b"User-maintained knowledge\n"])
def test_init_preserves_legacy_wiki_and_agents(tmp_path, content):
    legacy = [tmp_path / "AGENTS.md", tmp_path / "wiki" / "index.md",
              tmp_path / "wiki" / "notes" / "x.md", tmp_path / "legacy-store" / "r.txt"]
    for p in legacy:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    _cmd_init(tmp_path)
    assert all(p.read_bytes() == content for p in legacy)
    assert (tmp_path / "wiki" / "tasks" / "README.md").is_file()
```
Keep the existing `test_init_keeps_selected_root_cwd_and_git_state` test, but change its
assertion `(project / "wiki" / "index.md").is_file()` to
`(project / "wiki" / "tasks" / "README.md").is_file()`.

Note: the template renders a Windows path with backslashes (`projects\<slug>\`), so the
test asserts that exact form, using `project_slug`.

- [x] **Step 2:** Run → FAIL.
- [x] **Step 3: Implement.** Rewrite `_init_templates.py`:
```python
"""Project briefing and task-artifact folder; initialization never overwrites files."""
from pathlib import Path

from agent._loop_helpers import project_slug


def _agents_template(project_name: str, today: str) -> str:
    slug = project_slug(Path(project_name))
    return f"""# AGENTS.md

> Last updated: {today}

## Overview
_1–2 sentences: what {project_name} is and why it exists._

## Rules
- _Standing, project-specific instructions only._

## Commands & Environment
- _Verified run / test / build commands and the Python environment._

## Memory
- Project wiki: `G:\\My Drive\\black_grimoire\\wiki\\projects\\{slug}\\`
- Search with memory-query at task start and before debugging; file with memory-add.
- Task specs and plans: `wiki/tasks/YYYY-MM-DD_<task>/` (this repo).
"""


_TASKS_README = """# wiki/tasks

Task specs and plans only (`YYYY-MM-DD_<task>/spec.md`, `plan.md`), written by the workflow.
Project knowledge (decisions, errors, notes, todos) lives in the central memory wiki at
`G:\\My Drive\\black_grimoire\\wiki` — use memory-query / memory-add, not files here.
"""


def build_init_files(project_name: str, today: str) -> dict[str, str]:
    """Return the project-relative files /init creates when missing."""
    return {
        "AGENTS.md": _agents_template(project_name, today),
        "wiki/tasks/README.md": _TASKS_README,
    }
```
Replace the `cli_utils.py` hint text with:
```python
        "[dim]Next: use [bold]memory-query[/bold] / [bold]memory-add[/bold] for the central "
        "memory wiki. Task specs and plans go in [bold]wiki/tasks/[/bold]. "
        "Add workflows to [bold].dagi/workflow/<name>/workflow.md[/bold].[/dim]"
```
- [x] **Step 4:** Run `tests/test_project_init.py` → PASS.
- [x] **Step 5:** Return for review.

---

### Subtask 4: DAGI skills and prompts
**Goal:** Full skill copies, parity test, and workflow rules rewritten to spec R4 and R5.

**Acceptance Criteria:**
- The parity test passes.
- `.dagi/skills/wiki-*` are gone.
- `grep -rnE "wiki_query|wiki_add|wiki-query|wiki-add|wiki-refresh|Personal memory|personal memory" .dagi/skills .dagi/prompts .dagi/workflow`
  → no hits, except inside `.dagi/skills/memory-refresh/`.
- The existing `tests/test_workflow_plan_template.py` passes.

**Files:**
- Replace: `.dagi/skills/memory-add/SKILL.md` and `.dagi/skills/memory-query/SKILL.md`
  (copy bytes from `C:\Users\alexr\.claude\skills\memory-{add,query}\SKILL.md`).
- Delete (`git rm -r`): `.dagi/skills/wiki-add/`, `wiki-query/`, `wiki-refresh/`.
- Create: `tests/test_memory_skill_parity.py`.
- Modify:
  - `.dagi/skills/enter-workflow/SKILL.md` (lines ~51, 81–101, 124, 151, 160, 196,
    216–232, 294);
  - `.dagi/skills/deliver/SKILL.md:71`;
  - `.dagi/skills/update-project-context/SKILL.md` (lines 3–42);
  - `.dagi/prompts/main/main_system.md` (lines 7–8, 10, 18, 65–67);
  - `.dagi/workflow/improve-yourself/workflow.md` (lines 69–77, 147–149, 330, 391).

- [x] **Step 1: Parity test (fails first, because the DAGI copies are still old)**
```python
"""The DAGI memory skills are full copies of the Claude Code ones (decision: full copies)."""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAUDE = Path.home() / ".claude" / "skills"


@pytest.mark.parametrize("name", ["memory-add", "memory-query"])
def test_memory_skill_matches_claude_copy(name):
    claude = CLAUDE / name / "SKILL.md"
    if not claude.exists():
        pytest.skip("Claude Code skills not installed on this machine")
    ours = REPO / ".dagi" / "skills" / name / "SKILL.md"
    assert ours.read_bytes() == claude.read_bytes(), f"{name} drifted — re-copy it"
```
- [x] **Step 2:** Copy the two SKILL.md files and `git rm` the `wiki-*` skills. Parity →
  PASS.
- [x] **Step 3: Rewrite the rules.** Apply these exact semantics (keep each file's existing
  voice and structure; replace only the memory/wiki content):
  - **enter-workflow:**
    - Replace the missing-wiki bootstrap and `wiki_query` paragraph (about lines 81–101)
      with a **"Memory checkpoint (task start)"**: "Before any substantive task, load the
      `memory-query` skill and search `projects/<slug>/` (the `[MEMORY]` pointer names it)
      for the task's keywords, then list its `todo/` folder. State what you found, or
      'no wiki entries'. Missing or empty results never block work." Also:
      "Ensure `wiki/tasks/` exists (create it if missing) before writing task artifacts."
    - Replace "Approval wiki checkpoint" (216–224) with a note: "No write at approval;
      approved decisions are filed at completion."
    - Replace "Completion wiki checkpoint" (226–232) with a **"Memory checkpoint (task
      end)"**: "After verification, load `memory-add` and file: approved decisions (choice,
      rejected alternatives, rationale), errors fixed (verbatim error text, cause, fix), new
      todos, reusable knowledge. Delete completed todos after filing their lessons. State
      the paths written."
    - Update the lines that reference "approval wiki checkpoint" (151, 196) and "completion
      wiki checkpoint" (160, 294) to the new names, or remove the approval one.
    - Line 51: drop "wiki,".
    - Line 124: "authorized wiki bootstrap" → "creating `wiki/tasks/`".
    - Remove every retry/block rule and every "wiki delegates must never…" sentence
      (line 101).
  - **deliver:71:** remove the approval-wiki-checkpoint precondition.
  - **`.dagi/skills/run_subagent/SKILL.md:13`:** "wiki query/add requests" → "memory
    findings for the main agent to file with memory-add".
  - **update-project-context:** rewrite as the DAGI version of the Claude skill. AGENTS.md
    holds only identity, standing rules, commands/environment and a Memory section
    (central wiki path plus `projects/<slug>/`). Route architecture, decisions, errors,
    notes, todos and user observations through **memory-add**. Task artifacts stay at
    `wiki/tasks/…`. Keep "main agent only" and "don't manufacture modifications".
  - **main_system.md:**
    - Lines 7–8 become `- **Memory wiki**: {memory_root}\wiki (see the [MEMORY] pointer for this project's folder)`.
    - Line 10: keep the path-resolution sentence, but replace its literal `dagi-memory/...`
      example with the central wiki path, and rename "memory root" to "memory wiki".
    - Line 18 becomes "Project and personal knowledge live in the central memory wiki; use
      the memory-query / memory-add skills (main agent, inline)."
    - Lines 65–67 become the two checkpoints plus the Task 1 advisory triggers: grep the
      exact error text before debugging; search before design choices; add after a fix or
      approved decision.
  - **improve-yourself/workflow.md:**
    - `skill("memory-query")` stays valid.
    - Lines 147–149: replace the `dagi-memory` sample paths with
      `G:\\My Drive\\black_grimoire\\wiki`.
    - Lines 330 and 391: keep the meaning, and remove the `memory-ingest` references that
      point at the retired store.
- [x] **Step 4:** Run the AC grep, `tests/test_workflow_plan_template.py` and
  `tests/test_system_prompt.py` → no hits / PASS.
- [x] **Step 5:** Return for review (include the diffs of the 5 modified files).

---

### Subtask 5: Repo cleanup and docs
**Goal:** `wiki/` holds only tasks; the Codex package is removed; AGENTS, README and TODO
are current.

**Acceptance Criteria:**
- `git ls-files wiki | grep -v "^wiki/tasks/"` → empty.
- `git ls-files integrations tests/test_codex_wiki_bootstrap.py` → empty.
- The AC5 grep audit (spec §12) → 0 hits.

**Files:**
- `git rm`: every tracked `wiki/` file outside `wiki/tasks/`; `integrations/codex/` (all);
  `tests/test_codex_wiki_bootstrap.py`.
- Create: `wiki/tasks/README.md` (the same text as `_TASKS_README` in Subtask 3).
- Modify:
  - `AGENTS.md`: slim it per the new update-project-context template; note that
    "`wiki/` holds only `tasks/`; knowledge lives in the central store". Route any removed
    knowledge through memory-add; the main agent does this in Subtask 7.
  - `README.md`: replace the 19 wiki/memory references with the new model. It has no Codex
    section; the single Codex mention is in `AGENTS.md`, so repoint that to `~/.codex`.
  - `TODO.md`: mark the rewire done; add "redesign memory-refresh". Also rewrite the stale
    lines 153 (`tools/_wiki_tools.py`) and 157 (`wiki-query`/`wiki-add`).
  - `config.example.yaml:89-92` (not just 92): the whole memory_root comment block.
  - `.gitignore:190` `dagi-memory/*`: keep it (harmless for old checkouts); the audit
    excludes `.gitignore`.

- [x] **Step 1:** Do the `git rm` commands and create the README.
- [x] **Step 2:** Doc edits.
- [x] **Step 3:** Run the audit grep. Don't pipe it; check the exit code:
  **exit 1 with no output = pass**, while exit 128 means the command itself is broken.
  ```bash
  git grep -nE "wiki_query|wiki_add|wiki-query|wiki-add|wiki-refresh|memory_query|memory_add|dagi-memory|_build_wiki_index_context" -- . \
    ':(exclude).superpowers' ':(exclude)docs/superpowers' ':(exclude)docs/fable' \
    ':(exclude)snapshots' ':(exclude)_todo' ':(exclude).dagi/plans' \
    ':(exclude).dagi/self-review' ':(exclude).dagi/handoffs' \
    ':(exclude).dagi/scripts/migrate_wiki.py' ':(exclude).dagi/dagi_simplified.jsonl' \
    ':(exclude)new_skills_planning.md' ':(exclude,glob)SUBAGENT_REPORT_*' \
    ':(exclude).dagi/skills/memory-refresh' ':(exclude).dagi/subagents/memory-refresh' \
    ':(exclude)wiki/tasks' ':(exclude).gitignore'; echo "exit=$?"
  ```
  Expected: no output, `exit=1`. Before any edits it gives 183 hits (review #1); use that
  run as the checklist of live files.
- [x] **Step 4:** Full suite deferred to integrated verification; independent review PASS.

---

### Subtask 6: Installed Codex (`~/.codex`), done by the main agent
**Goal:** The spec R8 edits, with backups first.

**Acceptance Criteria:** AC7.

**Files (outside the repo):**
- `~/.codex/skills/{memory-add,memory-query,enter-workflow,update-project-context,deliver,merging-git-branch,wiki-add,wiki-query,wiki-refresh}`
- `~/.codex/AGENTS.md`

- [x] **Step 1:** Copy those folders and `AGENTS.md` into
  `wiki/tasks/2026-09-27_rewire-central-memory/backup/codex/`. Git-ignore the backup folder
  by adding `wiki/tasks/*/backup/` to `.gitignore` (the backup is local only).
- [x] **Step 2:** Copy the Claude `memory-{add,query}/SKILL.md` over the Codex ones.
  Delete `~/.codex/skills/wiki-{add,query,refresh}`.
- [x] **Step 3:** Codex `enter-workflow`, `update-project-context` and `deliver` (line 21:
  "approval wiki checkpoint"; line 89: "wiki/context closure"), plus `merging-git-branch:33`
  ("wiki/context closure"): apply the same R5 rewrite as Subtask 4. Back these up too. Replace the `init_wiki.py` bootstrap step with "ensure `wiki/tasks/`
  exists"; delete `scripts/init_wiki.py`. Line 14's skill list: remove `wiki-query`,
  `wiki-add`; add `memory-query`, `memory-add`.
- [x] **Step 4:** In `~/.codex/AGENTS.md`, edit only the lines mentioning the wiki or
  memory, to match. Check it with `diff` against the backup.
- [x] **Step 5:** Verify with
  `grep -rnE "wiki-query|wiki-add|wiki_query|wiki_add|init_wiki" ~/.codex/skills ~/.codex/AGENTS.md`
  → only hits inside `memory-refresh`, if any. Also `cmp` the memory skills against the
  Claude ones.

---

### Subtask 7: Integrated verification (main agent)
- [ ] Full suite: passed ≥ 1382 − (removed tests) + (added tests), 0 failed. Record the exact
  numbers.
- [ ] The AC5 grep audit → 0 hits.
- [ ] Smoke test: construct `AgentLoop` with `memory_root=None` (as in
  `tests/test_subagent_main.py`) and check the first user message contains `[MEMORY]` and
  `projects/driverless-agi/`. Or run `python -c` with `_build_memory_context(resolve_memory_root(None), Path.cwd())`
  and inspect the output.
- [ ] Knowledge from the slimmed AGENTS.md → memory-add to
  `projects/driverless-agi/`.
- [ ] Final reviewer on `git diff 1bedccb9..HEAD` plus the `~/.codex` diff against the
  backup.

---

## Workspace
- **Branch:** `task/rewire-central-memory`
- **Parent:** `main`
- **Starting commit:** `1bedccb9`
- **Task folder:** `wiki/tasks/2026-09-27_rewire-central-memory/`

## Overall Status
Verification — Subtasks 1–6 implemented and independently reviewed.

## Notes
- Grilling decisions Q1–Q6: spec §10.
- Baseline: 1382 passed / 1 skipped at `1bedccb9` (2026-09-27).
- `.dagi/config.yaml` is tracked and set `memory_root` to the legacy `dagi-memory`. Found
  during planning.
- The log source label for the pointer stays `"wiki"`, to keep the session-log format stable.
- Plan review #1 returned ESCALATE with 4 blocking findings, all fixed in this revision:
  1. the broken audit pathspec (it now uses long-form excludes and an explicit exit code),
     plus the live files missing from the plan;
  2. 7 tests that depend on the machine because the vault exists, handled by an autouse
     conftest fixture;
  3. the wrong `build_subagent_registry` signature in the plan's test;
  4. `test_subagent_configs.py:93` reading deleted configs.

  Downstream fixes also applied: `__pycache__` cleanup, `run_subagent:13`, the Codex
  `deliver` and `merging-git-branch` lines, `disabled_tools: [memory_refresh]`, the
  `loop.py` line wrap, and the `_loop_helpers` docstring.
- Plan review #2 returned ESCALATE (narrow). Findings and fixes:
  - B1: the new tests' legacy-name strings tripped the audit. Tests now use
    `legacy-store`, with no pattern text.
  - B2: the subagent-fallback test passed against unchanged code. It now asserts the
    `read` tool's `cwd` and `allowed_roots`, which fails first.
  - The Step 1 import contradiction is fixed (module-attribute access).
  - Confirmed: the audit runs (124 current hits, all covered by edits); the autouse fixture
    is sound; `disabled_tools` from the base config is honoured (merged; applied via
    `filter_out`).
- Plan review #3 (narrow) found one leftover: `tests/test_project_init.py` asserted on the
  literal `wiki-query`/`wiki-add` strings. It now asserts `memory-query`/`memory-add` are
  present. The reviewer confirmed that the new subagent test fails against current code for
  the intended reason. The main agent then re-ran the reviewer's check (grep of every python
  block in plan.md for the audit pattern) → no hits (exit 1). **All review findings are
  resolved.**
- TODO entry "redesign memory-refresh" must note that its SKILL.md line 26
  `{memory_root} = …dagi-memory` renders confusingly now that `memory_root` is the vault.
- Cosmetic, accepted: the TUI and GUI sidebars show `mem` only when `config.memory_root` is
  set. `.dagi/config.yaml` sets it, so it still shows here.
- Implementation commits verified: `f00a1a5f` (Subtask 1), `f06e250d` (Subtask 2),
  `91bc382e` (Subtask 3), `07d38635` (Subtask 4), `4cc20455` (Subtask 5).
- Subtask 5 independent review: PASS; AC5 audit exited 1 with no output; staged diff check
  passed before commit.
- Subtask 6: installed Codex files backed up under the ignored task `backup/codex/` folder;
  both memory skills match the Claude copies byte-for-byte; retired `wiki-*` skills and
  `init_wiki.py` removed; independent review PASS. The installed files are outside Git.

## Open Issues
- Confirm Q6's reading: remove the repo's `integrations/codex/`, and treat `~/.codex` as the
  only home for Codex skills.

## Attempts and Resolutions
(none)

## Verification
- Subtasks 1–6: implementation/recovery evidence reconciled; independent reviews for
  Subtasks 5 and 6 passed. Full integrated suite and final review remain.

## Next Action
Run Subtask 7 integrated verification, record exact results, and obtain final review.
