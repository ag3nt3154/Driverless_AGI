# Desktop Pet — Design Spec

**Date:** 2026-09-07

## Overview

Move VAD expression emotes out of the right sidebar into a standalone desktop
pet window. The right sidebar's ExpressionWidget becomes process-state-only.

## Desktop Pet Window

New file: `pyside_gui/desktop_pet.py` — `DesktopPetWindow(QWidget)`

**Window properties:**
- Flags: `FramelessWindowHint | WindowStaysOnTopHint | Tool`
  - `Tool` keeps it off the taskbar
- `setAttribute(Qt.WA_TranslucentBackground)` for transparent surround
- Not shown on startup — user opts in via `/show-pet`

**Positioning:**
- Default position: bottom-right of the primary screen, ~20px inset from edges
- Draggable via `mousePressEvent` / `mouseMoveEvent` offset tracking
- Position resets to default each session (not persisted)

**Rendering:**
- Receives `ExpressionSnapshot` via a slot connected to `bridge.expression_changed`
- Plays the snapshot's `asset` using `QMovie` (GIF) or `QPixmap` (static), same
  scaling logic as the current ExpressionWidget (`_GIF_BOUND` size)
- When a GIF finishes its last frame, the widget holds that frame until the next
  `expression_changed` signal arrives (driven by the existing
  `ExpressionController.advance()` timer in `AgentLoop`)
- No channel rotation, no meme overlay — purely VAD expression display

**Lifecycle:**
- Created hidden during `DagiMainWindow._build_ui()`
- Closed when the main window closes

## Simplified ExpressionWidget (Right Sidebar)

Modify: `pyside_gui/expression_widget.py`

**Remove:**
- `_channel` field and `_rotate_channel()` method
- `_meme_asset` / `_meme_cycles_remaining` fields
- `update_expression()` slot (VAD snapshots go to the pet window now)
- Rotation timer logic

**Keep:**
- `update_process(snapshot)` slot — renders the current process state asset
  (idle, thinking, tool:bash, tool:read, error, etc.)
- Caption: "PROCESS {state}"
- Same widget size as before

The widget simply shows the latest process state and holds it until the next
state change. No timer-based rotation.

## Slash Command: `/show-pet`

Add to `pyside_gui/commands.py`:
- `/show-pet` toggles the desktop pet window visibility (show if hidden, hide if shown)
- Feedback message in conversation: "Desktop pet shown" / "Desktop pet hidden"

## Wiring (app.py)

- `bridge.expression_changed` → `DesktopPetWindow` slot (was: `ExpressionWidget.update_expression`)
- `bridge.process_state_changed` → `ExpressionWidget.update_process` (unchanged)
- Pet window reference stored on `DagiMainWindow` for the slash command to access

## No Agent-Side Changes

The following are unmodified:
- `ExpressionController` and `RandomEmoteLibrary`
- `AgentLoop._start_expression_timer()` / `_stop_expression_timer()`
- `AgentCallbacks.on_expression_changed`
- `AgentBridge.expression_changed` signal
- `AffectController` (if active)
