---
title: 'Auto-growing QPlainTextEdit with an AsNeeded scrollbar hangs Qt on wrap'
description: 'Composer froze (Not responding) typing across a wrap; fix: _fit_editor owns the scrollbar policy, AlwaysOff below cap, AlwaysOn at cap, AsNeeded only in compose mode.'
tags: [_fit_editor, PromptInput, QPlainTextEdit, ScrollBarAsNeeded, documentSizeChanged, insertPlainText, Not responding, AppHangB1, 'DLL load failed']
updated: 2026-10-09
---
Fixed 2026-10-09, commit e7601d9c, `pyside_gui/prompt_input.py`.

Symptom: typing a long draft in the composer lags, then the whole window freezes and Windows
reports "Not responding" (WER `AppHangB1`). Intermittent: depends on window width and text.
Restarting "fixed" it mostly because the new window had a different width.

## Cause
The editor auto-grows via `_fit_editor` (on `documentLayout().documentSizeChanged`) up to
`MAX_EDITOR_HEIGHT`, with word wrap and `ScrollBarAsNeeded`. When a keystroke wraps onto a
new line, the editor is briefly too short, Qt shows the scrollbar, the viewport narrows
(398→384 px), the text rewraps, `_fit_editor` grows the editor, and the bar stays visible
with range 0..0. The next keystroke hangs natively inside `insertPlainText` (no Python
frames on the stack). Most likely Qt is switching the scrollbar on and off forever.
Offscreen repro: card in a 504 px window, char 57 of `"lorem ipsum dolor sitamet ..."`.

## Fix
`_fit_editor` sets the policy itself, and only when it changes:
- below the cap: `ScrollBarAlwaysOff`;
- at the cap: `ScrollBarAlwaysOn`;
- compose mode (height not driven by the text): `ScrollBarAsNeeded`.

Each switch reinforces itself: a narrower viewport means more lines, so the editor stays
capped; a wider one means fewer lines, so it stays uncapped. It cannot oscillate.
Regression test: `test_typing_across_a_wrap_does_not_hang` (`pyside_gui/tests/test_composer.py`)
replays the keystrokes in a subprocess with a 60 s timeout.

## Gotchas for Qt probes
- Ad-hoc scripts must `import pyside_gui` before any `PySide6` import (DLL bootstrap),
  otherwise `ImportError: DLL load failed while importing QtWidgets`.
- Qt cannot load inside the Claude Code sandbox; run probes and GUI tests unsandboxed.
- The hang needs layout to settle between keys: about 15 `app.processEvents()` per
  keystroke. With a single call per key the old code did *not* hang.
