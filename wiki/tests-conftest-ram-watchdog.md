---
title: 'Test RAM watchdog errors every test above 85% system RAM'
description: 'tests/conftest.py raises _RAMExceeded in setup when system RAM is over 85%; run non-Qt suites with --noconftest when the machine is busy.'
tags: [pytest, conftest, _RAMExceeded, RAM watchdog, noconftest, psutil]
updated: 2026-10-13
---
```
E   tests.conftest._RAMExceeded
```
Every test (old ones included) errors in setup, so the failure says nothing about the change under test.

## Cause
The RAM watchdog fixture in `tests/conftest.py` aborts when `psutil.virtual_memory().percent` is above 85% (system-wide, not this process).

## Fix
- Free memory, or run non-Qt suites with `--noconftest` (e.g. `tests/message_board`). That also drops the conftest fixture isolating the real memory store, so re-run normally once RAM is lower.
- `pyside_gui/tests` need their own conftest (`qtbot`, qapp); run them without `--noconftest`, unsandboxed.
