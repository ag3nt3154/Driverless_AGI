# AGENTS.md

> Last updated: 2026-10-17 (review refreshed; self-improvement exit status reviewed) | [README](README.md) | [TODO](TODO.md) | [Task specs & plans](wiki/tasks/)

## Overview

Driverless AGI (dagi) is a Python agentic coding assistant with tool use, subagent delegation,
session persistence, and multi-UI support (TUI, PySide desktop, Telegram).
The message board is a standalone browser app; the desktop GUI shows a read-only feed and owns a
private throwaway board only while the configured central board is unavailable.

## Rules

- Knowledge (architecture, decisions, errors, notes, todos) goes to `wiki`, including `tasks/` (specs and plans).

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

## Commands & Environment

- Python env `dagi` (`DEFAULT_PYTHON_ENV`) for all scripts and installs.
- Install from the repo root: `python -m pip install -r requirements-core.txt`; add
  `-r requirements-gui.txt`, `-r requirements-tui.txt` or `-r requirements-tools.txt` as needed.
- Tests: `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt`.
  `conda run` fully buffers stdout when not on a TTY (looks like a hang) — call the env's
  interpreter directly with `-u`. pytest-qt must be disabled as `-p no:pytest-qt` (not `no:qt`).
- Hooks use `envs/dagi/python.exe` directly (`conda run` drops stdin).
- RPA desktop tests (`desktop` marker; real UI, global keyboard hook) are skipped unless
  `DAGI_DESKTOP_TESTS=1`; run them unsandboxed and only with the Admiral's consent.
- Qt (tests, ad-hoc probes) cannot load in the Claude Code sandbox — run unsandboxed. Ad-hoc
  scripts must `import pyside_gui` before any `PySide6` import (DLL bootstrap).

## Memory

- Project wiki: `wiki` (architecture, errors log, notes and terms, todos, reviews).
- Offline PyTorch wheel requests and verified ZIP bundle: [Windows x64 / Python 3.13 reference](wiki/pytorch-offline-windows-python313.md).
- Required checkpoints (see `enter-workflow`)
