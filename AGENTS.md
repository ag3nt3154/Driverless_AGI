# AGENTS.md

> Last updated: 2026-10-08 (Codex review refreshed; ordering contracts) | [README](README.md) | [TODO](TODO.md) | [Task specs & plans](wiki/tasks/)

## Overview

Driverless AGI (dagi) is a Python agentic coding assistant with tool use, subagent delegation,
session persistence, and multi-UI support (TUI, PySide desktop, Telegram).

## Rules

- Always update `AGENTS.md`, `README.md` and `TODO.md` after completing a task.
- Knowledge (architecture, decisions, errors, notes, todos) goes to the central memory wiki
  via memory-add — not AGENTS.md. The repo's `wiki/` holds only `tasks/` (specs and plans).
- Codex skills live in `~/.codex/skills` (the old `integrations/codex/` package was removed).
- Subagent API: import `tools/subagent_api.py`; never the private `_subagent_runner.py`.
- White-box tests of `agent/_*` loop modules must patch the owning module
  (e.g. `agent._compaction`), not `agent.loop`.
- Tool filtering: `.dagi/config.yaml` `tools:` restricts the main agent and `disabled_tools:`
  always removes (currently `memory_refresh`); `write_handoff` is always injected.
- Ordering contracts are pinned by tests; when a change is meant to alter them, update the
  expected sequence in the same commit: tool registration order
  (`tests/test_tool_registry_contract.py`), `AgentLoop` construction
  (`tests/test_loop_construction.py`), per-call dispatch events
  (`tests/test_end_turn_batch.py::TestDispatchEventTrace`), subagent argv
  (`tests/test_subagent_api.py::TestChildArgvContract`).

### Coding standards

- Functions: ≤ 100 lines | Cyclomatic complexity: ≤ 8 | Positional parameters: ≤ 5
- Line length: 100 characters | Files: ≤ 500 lines

### Behavioral guidelines

> Stable protocol/standards content — preserve verbatim across routine updates; only edit when
> the user gives an explicit standing behavioral instruction.

- **Calibrate to ambiguity:** high → ask clarifying questions first; medium → ask targeted
  questions, then proceed; low → verify quickly and proceed; trivial → trust user intent.
- **Before acting:** state assumptions; read before write (exports, immediate caller, shared
  utilities); assess downside and reversibility before risky changes.
- **During execution:** simplicity first — minimum code, nothing speculative; surgical scope,
  match conventions. NEVER create files unless necessary. NEVER commit secrets or .env files.
- **Verify invariants before shipping:** state ownership and consistency; feedback and
  observability; blast radius; timing and ordering; existing patterns; security risks.
- **After acting:** ground claims (mark or remove unsupported numbers); fail loud ("done" is
  wrong if anything was skipped silently); checkpoint what was done, verified, and left.
- **Tests** encode *why* behavior matters; a test that can't fail when logic changes is wrong.
- **Hard stops:** flag unclear state ownership, unknown blast radius, timing/race hazards,
  security issues, or significant complexity debt.
- **Errors:** fail fast with clear, actionable messages; never swallow exceptions silently.

### Git workflow

- Start with `git status --short` and `git branch --show-current`; never discard existing work.
- Implementation: after grilling, get branch approval and create `dagi/<task-name>` (Claude
  Code sessions use `task/<task>`); write spec + plan in `wiki/tasks/YYYY-MM-DD_<task>/`, get
  joint approval, commit both, then implement and commit reviewed subtasks.
- The main agent owns task commits under that scoped approval; workers do not stage or commit.
- Ask separately before merging a completed task branch into its recorded parent.
- Conventional Commit prefixes. Never commit, merge, push, stash, switch or create a branch
  without user approval.

## Commands & Environment

- Python env `dagi` (`DEFAULT_PYTHON_ENV`) for all scripts and installs.
- Install from the repo root: `python -m pip install -r requirements-core.txt`; add
  `-r requirements-gui.txt`, `-r requirements-tui.txt` or `-r requirements-tools.txt` as needed.
- Tests: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt`.
  `conda run` fully buffers stdout when not on a TTY (looks like a hang) — call the env's
  interpreter directly with `-u`. pytest-qt must be disabled as `-p no:pytest-qt` (not `no:qt`).
- Hooks use `envs/dagi/python.exe` directly (`conda run` drops stdin).

## Memory

- Project wiki: `G:\My Drive\black_grimoire\wiki\projects\driverless-agi\` (architecture,
  errors log, notes and terms, todos, reviews).
- Required checkpoints (see `enter-workflow`): memory-query at task start; memory-add at task
  end. Grep the exact error text before debugging. Memory is inline — no subagents.
