---
title: 'Todo: prompt about unsaved settings on app close'
description: 'Closing the GUI or collapsing the Settings panel with unsaved settings edits gives no prompt; edits are lost on quit.'
tags: [settings_view, is_dirty, closeEvent, left_sidebar, unsaved]
updated: 2026-10-14
---
`pyside_gui/app.py` `closeEvent` doesn't check `left_sidebar.settings_view.is_dirty()`; quitting silently drops unsaved settings. Only the rail tooltip shows "Settings (unsaved changes)". Add a Save / Discard / Cancel prompt on close; consider a visible dirty dot on the rail button. No due date.
