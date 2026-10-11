---
title: 'A minimized window exposes almost no UIA tree: restore before observing'
description: 'UiaDriver restores a minimized root before outlining it; that is real input, so the desktop lock is taken first (needs_desktop_lock_to_observe).'
tags: [rpa, uiautomation, UIA, minimized, restore, needs_desktop_lock_to_observe, DesktopLock]
updated: 2026-10-12
---
Found in the RPA S0 spikes (2026-10-10).

- A minimized top-level window answers UIA with little more than its title bar, so an
  outline or a locator search on it finds nothing and a replay would halt with `NotFound`.
- `UiaDriver` restores the window before observing it. Restoring changes the desktop, so it
  is treated like real input: the driver protocol method `needs_desktop_lock_to_observe(root)`
  returns True for a minimized UIA root, and both `ui_observe` and the interpreter take the
  desktop lock before the first observe of such a root (Subtask 15 review fix).
- Browser roots never need this: WebDriver reads the DOM of a minimized Firefox window.
