---
title: 'Electron apps expose no UIA tree unless launched with --force-renderer-accessibility'
description: 'UiaDriver.launch adds --force-renderer-accessibility for known Electron apps; even then they have almost no stable automation ids.'
tags: [rpa, uiautomation, UIA, Electron, force-renderer-accessibility, ELECTRON_APPS, UiaDriver]
updated: 2026-10-12
---
Found in the RPA S0 spikes (2026-10-10).

- Chromium-based Electron apps (VS Code, Slack, Teams, Discord, Claude desktop) build their
  accessibility tree only when an assistive tool asks for it. A plain launch gives UIA an
  almost empty window.
- `rpa/drivers/uia.py` `ELECTRON_APPS` lists known executables; `launch()` adds
  `--force-renderer-accessibility` for them (any path, any case).
- Even with the flag the tree has almost no `automation_id`s, so the locator ladder falls to
  rung 2 (role + name). Expect `degraded` runs and ambiguity halts more often.
- An app that is already running without the flag cannot be fixed: dagi only drives windows
  it launched (Admiral's privacy decision in the S1 check), so close the app and let dagi
  launch it.
