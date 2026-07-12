# Multi-line Input Design

**Date:** 2026-07-12  
**Status:** Approved  
**Files:** `tui/prompt_input.py`, `tui/app.py`

---

## Problem

`PromptInput` (a `TextArea` subclass) already handles `shift+enter` → insert newline in code, but Windows Terminal with cmd prompt sends identical bytes for `shift+enter` and `enter` (`\r`, ASCII 13). The `elif event.key == "shift+enter"` branch never fires, so pressing Shift+Enter submits instead of inserting a newline. Multi-line input is effectively broken on this terminal configuration.

---

## Solution

Three coordinated changes:

### 1. Newline Key Bindings

Add two additional "insert newline" key variants in `PromptInput.on_key`:

| Key | Mechanism | Reliability |
|-----|-----------|-------------|
| `shift+enter` | Existing — keep | Terminals with Kitty/Win32 input mode |
| `ctrl+n` | New — ASCII 0x0E | **Universal** — always distinct from Enter (0x0D) |
| `ctrl+enter` | New | Windows Terminal (newer versions) bonus |

All three branches call `self.insert("\n")` identically.

### 2. Default Height Increase

`#prompt` CSS height: `5` → `8`. Gives comfortable vertical space for multi-line drafting without crowding the conversation pane.

### 3. Compose Mode (`ctrl+o`)

A full-screen compose toggle. Two states:

| State | ConversationPane | PromptInput height |
|-------|-----------------|-------------------|
| Normal | visible (`1fr`) | `8` |
| Compose | hidden (`display: none`) | `1fr` (fills everything below Sidebar) |

Sidebar remains visible in both states (fixed `height: 12`).

**Trigger:** `ctrl+o` toggles between states.  
**Auto-collapse:** submitting (Enter) while in compose mode collapses back to normal automatically.  
**Hint:** `PromptInput` border title displays `ctrl+n = newline · ctrl+o = compose` so the bindings are passively discoverable.

---

## Architecture

### `tui/prompt_input.py`

- Add `elif event.key in ("ctrl+n", "ctrl+enter"):` branch → `self.insert("\n")`

### `tui/app.py`

- `DagiApp.__init__`: add `self._input_expanded: bool = False`
- `BINDINGS`: add `("ctrl+o", "toggle_compose", "Compose")`
- CSS: change `#prompt { height: 5 }` → `height: 8`
- Add `action_toggle_compose()`:
  ```
  flip _input_expanded
  conv.display = not _input_expanded
  inp.styles.height = "1fr" if expanded else 8
  ```
- `on_prompt_input_submitted`: if `_input_expanded`, call `action_toggle_compose()` before/after dispatch

---

## Out of Scope

- Dynamic auto-expansion as content grows (complexity not warranted; compose mode covers the use case)
- Paste handling changes (Textual's TextArea already handles bracketed paste correctly)
- Scroll-within-collapsed-input behaviour (Textual TextArea handles this natively)

---

## Testing

Manual verification:
1. `ctrl+n` inserts a newline in normal mode
2. `ctrl+n` inserts a newline in compose mode
3. `ctrl+o` hides conversation pane and expands input to full height
4. `ctrl+o` again restores conversation pane and collapses input
5. Enter in compose mode submits and auto-collapses
6. Paste of multi-line text inserts correctly without submitting
