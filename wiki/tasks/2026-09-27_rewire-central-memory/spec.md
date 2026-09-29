# Spec — Rewire DAGI and Codex to the Central Memory Wiki (Task 2)

## 1. Document status
| Field | Value |
|---|---|
| Owner | Admiral; drafted by Claude |
| Version | v1, 2026-09-27 |
| Status | **Draft — in review** |
| Branch | `task/rewire-central-memory` from `main@1bedccb9` |
| Related | Task 1 spec: `G:\My Drive\black_grimoire\docs\tasks\2026-09-27_memory-wiki-redesign\spec.md` (store layout, schema, triggers) |

## 2. Summary and problem
Task 1 created the central memory wiki at `G:\My Drive\black_grimoire\wiki` and rewrote the
Claude Code memory skills. DAGI and Codex still use the retired systems:
- `.dagi/config.yaml` sets `memory_root` to `black_grimoire\dagi-memory`. Code fallbacks default
  to `<project>/dagi-memory` (`loop.py:101`, `tools.py:217,246`, `subagent_tools.py:199`,
  `tools/skill/_skill.py:80`). A per-turn `[WIKI]` pointer (`_loop_helpers.py:12`) aims at
  the legacy wiki.
- Four subagent tools spawn agents for memory: `memory_add`, `memory_query`, `wiki_add` and
  `wiki_query`. Plus `tools/_wiki_tools.py`.
- `/init` scaffolds a 7-page per-project knowledge wiki (`agent/_init_templates.py`) and an
  AGENTS.md that mandates `wiki-query`/`wiki-add` with retry/block semantics.
- DAGI workflow skills/prompts (`enter-workflow`, `update-project-context`, `main_system.md`,
  `improve-yourself` workflow) require `wiki_query` and `wiki_add`.
- The repo holds a Codex package `integrations/codex/`. The installed Codex skills live in
  `~/.codex/skills`: their `memory-*` are pointers to DAGI, and their `wiki-*` would dangle.
- The repo's `wiki/` holds 20 knowledge pages already migrated to
  `wiki/projects/driverless-agi/` in the central store.

**Outcome:** DAGI and Codex use the central store the same way Claude Code does. No memory
subagents, no per-project knowledge wiki, and `wiki/` holds only task specs and plans.

## 3. Goals, scope, non-goals
**Goals**
- G1: A DAGI session in any project gets the `[MEMORY]` pointer to the central wiki and its
  project folder, and can grep, read and write it with no configuration.
- G2: No live code, config, skill or prompt references the removed tools or the legacy paths
  (verified by grep audit).
- G3: The full test suite passes with a count ≥ baseline minus deliberately deleted tests
  (baseline: 1382 passed, 1 skipped at `1bedccb9`).

**In scope:** DAGI code, config, tests, `.dagi/skills`, `.dagi/prompts`, `.dagi/workflow`;
repo `wiki/` cleanup; removal of `integrations/codex/`; updating installed `~/.codex/`;
`AGENTS.md`, `README.md`, `TODO.md`.

**Non-goals**
- `memory-refresh` redesign. Its skill, subagent and scripts are kept but **disabled**
  (removed from the enabled tools list).
- Historical records: `.superpowers/`, `docs/superpowers/`, `snapshots/`, `_todo/`,
  `.dagi/plans/`, `.dagi/self-review/`, `.dagi/handoffs/`, `.dagi/scripts/migrate_wiki.py`,
  `new_skills_planning.md`, `SUBAGENT_REPORT_*.md`.
- Deleting `hedgefundie/wiki` or `dagi-memory/`.
- Changing `wiki/tasks/` paths in workflow skills.

## 4. Requirements
- **R1 Memory root.**
  - `agent/_loop_config.py` defines `DEFAULT_MEMORY_ROOT = Path(r"G:\My Drive\black_grimoire")`
    and `resolve_memory_root(configured: Path | None) -> Path` (configured, else default,
    resolved).
  - Every fallback listed in §2 uses it.
  - `.dagi/config.yaml` `memory_root` is set to `G:\My Drive\black_grimoire`.
  - `config.example.yaml` documents that it's optional and what the default is.
- **R2 Pointer.** `_build_wiki_index_context` is replaced by
  `_build_memory_context(memory_root, project_path) -> str | None`:
  - it returns `None` if `memory_root/wiki` does not exist;
  - otherwise it returns:
    ```
    [MEMORY]
    Memory wiki: <memory_root>\wiki
    This project: projects/<slug>/  — search with memory-query at task start and before debugging; file with memory-add.
    [END MEMORY]
    ```
  - `<slug>` comes from `project_slug(project_path)`: the folder name lowercased, with
    non-alphanumeric runs turned into `-` and stripped (`Driverless_AGI` → `driverless-agi`).
  - It is injected where `[WIKI]` was, and is still skipped when `_preserve_request_prefix`
    is set.
- **R3 Remove memory subagents.**
  - Delete `.dagi/subagents/{memory-add,memory-query,wiki-add,wiki-query}/`,
    `tools/_wiki_tools.py` and `tests/test_wiki_tools.py`.
  - Remove `memory_add`, `memory_query`, `wiki_query`, `wiki_add` and `memory_refresh` from
    the enabled tool lists (`.dagi/config.yaml`, `benchmarks/dagi_eval/config_dagi_eval.yaml`).
  - Update the registry tests.
  - `.dagi/subagents/memory-refresh/` stays, but is no longer enabled (removed from `tools:`,
    and listed in `disabled_tools:` if the base config honours it).
  - Tests are isolated from the real store by an autouse fixture that patches
    `DEFAULT_MEMORY_ROOT`, because the vault exists on the dev machine.
- **R4 Skills.**
  - `.dagi/skills/memory-add/SKILL.md` and `memory-query/SKILL.md` are **byte-identical
    copies** of `~/.claude/skills/memory-{add,query}/SKILL.md`.
  - Delete `.dagi/skills/wiki-{add,query,refresh}/`.
  - A test asserts parity with the Claude copies when those exist (skipped otherwise).
- **R5 Workflow rules** (in `.dagi/skills/enter-workflow`, `update-project-context`,
  `.dagi/prompts/main/main_system.md` and `.dagi/workflow/improve-yourself/workflow.md`):
  - **Required checkpoint 1:** at the start of every substantive task, run memory-query on
    `projects/<slug>/` (plus keywords), and state the result (hits or "none").
  - **Required checkpoint 2:** at task end, use memory-add to file the approved decisions,
    errors fixed, new todos and reusable knowledge; delete completed todos after keeping
    their lessons; state what was filed.
  - Advisory triggers from Task 1: grep the exact error text before debugging; search
    before design choices; add after a fix or approved decision.
  - Remove the retry/block semantics, the "delegates confined to wiki" rules and the
    per-project-wiki knowledge routing.
  - `update-project-context` routes non-AGENTS knowledge to memory-add (as in the Claude
    version).
  - Task artifacts remain at `wiki/tasks/YYYY-MM-DD_<task>/`.
- **R6 /init.** `build_init_files` returns exactly:
  - `AGENTS.md`, using the slim template (Overview, Rules, Commands & Environment, Memory,
    where Memory names the central wiki and `projects/<slug>/`);
  - `wiki/tasks/README.md`, which explains that `wiki/` holds only task specs and plans and
    that knowledge lives in the central store.

  Existing files are never overwritten. The CLI "Next:" hint names memory-query and
  memory-add.
- **R7 Repo cleanup.**
  - `git rm` every tracked file under `wiki/` except `wiki/tasks/**`.
  - `git rm -r integrations/codex` and `tests/test_codex_wiki_bootstrap.py`.
  - Update `AGENTS.md` (slim; note that `wiki/` holds only tasks), `README.md` and `TODO.md`.
- **R8 Installed Codex** (outside the repo; back up to `wiki/tasks/<task>/backup/codex/`
  first):
  - `~/.codex/skills/memory-{add,query}/SKILL.md` become full copies of the Claude versions.
  - Delete `~/.codex/skills/wiki-{add,query,refresh}/`.
  - In `~/.codex/skills/enter-workflow/SKILL.md` and `update-project-context/SKILL.md`,
    apply the R5 rules. The bootstrap step becomes "ensure `wiki/tasks/` exists", and
    `scripts/init_wiki.py` is deleted.
  - In `~/.codex/AGENTS.md`, edit only the memory-related lines.
  - `~/.codex/skills/memory-refresh` is untouched.

## 5. Constraints and assumptions
- **Verified:** DAGI's main agent has `grep`, `find`, `read`, `edit` and `write`.
  `memory_root` is in `allowed_roots` (`loop.py:135`). Python env: `dagi`. Test command:
  `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt`.
- **Constraints:** functions ≤100 lines; cyclomatic complexity ≤8; ≤5 positional
  parameters; lines ≤100 characters.
- **A1:** `~/.claude/skills/memory-*` are final for now. If they change later, the parity
  test flags DAGI drift.
- **A2:** the Codex install is used by only this machine and user.

## 6. Architecture
```
DAGI AgentLoop ──resolve_memory_root(config)──► G:\My Drive\black_grimoire
      │  per turn: [MEMORY] wiki path + projects/<slug>/
      ├─ skill("memory-query") → main agent grep/read  ─┐
      └─ skill("memory-add")   → main agent grep/write ─┴─► black_grimoire\wiki\
Codex (~/.codex/skills memory-*, enter-workflow) ───────────────► same store
repo wiki/ = tasks/ only (specs & plans, git-tracked)
```

## 7. Contracts
- `resolve_memory_root(configured: Path | None) -> Path`
- `project_slug(project_path: Path) -> str`
- `_build_memory_context(memory_root: Path, project_path: Path) -> str | None`
- The subagent `root: memory_root` mechanism stays (memory-refresh still declares it), with
  its fallback switched to `resolve_memory_root(None)`.

## 8. Quality
- Pointer cost: 3 short lines per turn, static per project, so it stays cache-friendly.
- Security: `allowed_roots` now spans the whole vault, not `dagi-memory`, which is the same
  trust level Claude Code has. Accepted.

## 9. Failure and recovery
- Missing store (another machine): the pointer is omitted, memory skills find nothing, and
  work proceeds. Override via config.
- Rollback: everything in the repo is on the task branch (merge is optional). `~/.codex` is
  restored from the backup folder.

## 10. Decisions
| # | Decision | Rejected |
|---|---|---|
| Q1 | Task artifacts stay in `wiki/tasks/` | `docs/tasks/`; central store |
| Q2 | `git rm` the migrated knowledge pages; `/init` creates only `wiki/tasks/` | Keep frozen copies |
| Q3 | Inline skills; delete 4 memory subagents | Query subagent; keep both |
| Q4 | Code default plus config override; `[MEMORY]` pointer | Config-only; env var |
| Q5 | Task 1 triggers plus 2 required checkpoints; no retry/block | All advisory; strict |
| Q6 | Codex skills live in `~/.codex`; remove `integrations/codex/` | Keep repo package |
| — | Disable `memory_refresh` tool (guard, since `memory_root` widens) | Leave enabled |

## 11. Compatibility and release
- Irreversible outside git: the `~/.codex` edits, mitigated by backups.
- The merge to `main` is a separate approval at closure.

## 12. Acceptance
| ID | Check |
|---|---|
| AC1 (R1, R2) | Unit tests for `resolve_memory_root`, `project_slug`, `_build_memory_context`; `AgentLoop` uses the resolved default when config is `None` |
| AC2 (R3) | The four subagent dirs and `_wiki_tools.py` are gone; config lists are clean; registry tests pass |
| AC3 (R4) | Parity test passes; `.dagi/skills/wiki-*` are gone |
| AC4 (R6) | `/init` tests: creates exactly `AGENTS.md` and `wiki/tasks/README.md`; preserves existing files |
| AC5 (R5, R7, G2) | The exact `git grep` audit in plan Subtask 5 Step 3 (long-form excludes for historical paths, `docs/fable`, `.dagi/dagi_simplified.jsonl`, `.gitignore` and the `memory-refresh` files) prints nothing and exits 1 |
| AC6 (R7) | `git ls-files wiki` lists only `wiki/tasks/**`; `integrations/codex` is gone |
| AC7 (R8) | `~/.codex/skills` has no `wiki-*`; `memory-*` match the Claude copies; `~/.codex/AGENTS.md` diff vs backup touches only memory lines |
| AC8 (G3) | Full suite passes |

## 13. Risks and open questions
| Risk | Mitigation |
|---|---|
| Hidden importer of `_wiki_tools` or the removed subagents | Full test suite plus grep audit |
| DAGI small models skip memory checkpoints | Required checkpoints in `enter-workflow` plus the per-turn pointer |
| Reading of Q6 ("remove `integrations/codex`") is wrong | Confirmed at spec approval |

**Readiness:** ready for plan writing.
