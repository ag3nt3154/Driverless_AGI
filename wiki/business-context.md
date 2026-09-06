# Business Context

Project purpose, users, and constraints.

> Last updated: 2026-09-05

## Purpose

Driverless AGI (dagi) is a Python agentic coding assistant. It provides an agent loop
with tool use, subagent delegation, session persistence, and multi-UI support (TUI,
PySide desktop, Telegram).

## Users

The Admiral (primary user) — runs dagi locally for agentic coding tasks, delivered
via `/deliver`. The project itself is both the product and the test bed.

## Constraints

- **Windows / conda**: primary dev environment is Windows 11 with conda env `dagi`.
  Use `conda run -n dagi python` for scripts; hooks use `envs/dagi/python.exe` because
  `conda run` drops stdin.
- **RAM watchdog**: `tests/conftest.py` terminates tests when RAM ≥70%. Long test runs
  need `--noconftest` to avoid the watchdog, but also `--p "no:pytest-qt"` to disable
  Qt detection (pytest-qt entry point name is `pytest-qt`).
- **Provider**: DeepSeek via DeepSeek API by default; Claude via OpenRouter available.
- **Personal memory root**: `G:/My Drive/black_grimoire/dagi-memory` (explicit requests only).

[Project wiki](index.md)
