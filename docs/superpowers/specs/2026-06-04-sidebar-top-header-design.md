# Sidebar → Top Header: Design Spec

**Date:** 2026-06-04  
**Status:** Approved

---

## Context

The TUI sidebar currently occupies the right 25% of the screen beside the conversation pane. This wastes horizontal real estate on terminals narrower than ~160 columns and places status info at eye-periphery. Moving it to a fixed 6-line horizontal header above the conversation pane gives the conversation pane the full terminal width while keeping all status info visible at a glance.

---

## Approach: Three-Column Header (Approved)

A 6-line `Sidebar` widget sits at the top of the screen, full width, with content arranged in three horizontal columns via a `rich.table.Table(expand=True)`:

| Column | Width (ratio) | Content |
|--------|--------------|---------|
| Left   | 2            | Emote face + status dot + model name |
| Center | 4            | Token counts (1 line) + condensed context breakdown (4–5 rows) |
| Right  | 3            | Plan subtasks (clips beyond 6 lines) |

The ASCII-art border decoration (`╭≋≋╮`) is removed; the emote face glyph is rendered inline in the left column. All other info (tokens, context, plan) is preserved.

---

## Layout Change

**Before:**
```
Screen (vertical)
├── #main-row (Horizontal, height=1fr)
│   ├── #conversation-col (Vertical, width=75%)
│   │   ├── ConversationPane
│   │   └── #running-indicator
│   └── Sidebar (width=25%, border-left)
└── PromptInput (docked bottom)
```

**After:**
```
Screen (vertical)
├── Sidebar (height=6, full width, border-bottom)
├── ConversationPane (height=1fr)
├── #running-indicator (height=1, hidden)
└── PromptInput (docked bottom)
```

---

## Column Content Design

### Left column — Status
```
(◉ ᴗ ◉)
● Running
qwen/qwq-32b
```
- Face from `_load_face()` (unchanged)
- Status dot: `●` green (running), `⏸` yellow (paused), `○` dim (idle)
- Model name bold

### Center column — Tokens + Context
```
in ~1,200  out ~42  think ~0  $0.00012
sys   ~2,400   12%
msgs  ~3,200   16%   ← sum of summary+user+assistant+tools
rsrv  ~800      4%
total ~6,400   32%   ← green/yellow/red by threshold
```
- Tokens on one inline line
- Context condensed to 4 rows: sys / msgs (aggregated) / reserve / total
- Color thresholds unchanged: red ≥95%, yellow ≥80%, green otherwise

### Right column — Plan
```
My Project Title
[~] Subtask 1
[x] Subtask 2
[ ] Subtask 3
[ ] Subtask 4
```
- Renders if `_subtasks` non-empty; empty `Text("")` otherwise
- Content clips beyond 6 lines (no scroll — header is fixed height)
- Status icons unchanged

---

## Files Changed

| File | Change |
|------|--------|
| `tui/sidebar.py` | Replace `render()` + old panel methods with 3 new column methods; update `DEFAULT_CSS` |
| `tui/app.py` | Simplify `compose()` (remove `Horizontal`/`Vertical` containers); update `CSS` |

### `tui/sidebar.py` — method changes

Remove:
- `_logo_panel()` — replaced by inline face in `_status_col()`
- `_model_panel()` — merged into `_status_col()`
- `_token_panel()` — replaced by `_tokens_context_col()`
- `_context_panel()` — condensed and merged into `_tokens_context_col()`
- `_plan_panel()` — replaced by `_plan_col()`

Add:
- `_status_col()` → face + dot + model name (returns `Table.grid`)
- `_tokens_context_col()` → token line + 4-row context table (returns `Group`)
- `_plan_col()` → subtask list (returns `Table.grid` or `Text("")`)

`render()` becomes:
```python
def render(self):
    t = Table(expand=True, box=None, padding=(0, 1))
    t.add_column(ratio=2)
    t.add_column(ratio=4)
    t.add_column(ratio=3)
    t.add_row(self._status_col(), self._tokens_context_col(), self._plan_col())
    return t
```

### `tui/app.py` — CSS + compose changes

```python
CSS = """
Screen { layout: vertical; }
ConversationPane { height: 1fr; }
Sidebar { height: 6; border-bottom: solid $panel; }
#running-indicator { height: 1; display: none; color: $success; text-align: center; }
#prompt { dock: bottom; height: 5; border-top: solid $panel; }
"""
```

```python
def compose(self) -> ComposeResult:
    cfg = resolve_model_config(self._model_id)
    dagi_root = Path(__file__).parent.parent
    yield Sidebar(self._model_name, cfg.context_window, cfg.reserve_tokens,
                  dagi_root=dagi_root, project_path=self._project_path)
    yield ConversationPane(id="conversation", highlight=True, markup=True, wrap=True)
    yield Static("", id="running-indicator")
    yield PromptInput(id="prompt")
```

Remove `Horizontal`, `Vertical` imports from `tui/app.py` (unused after change).

---

## Verification

1. Run `conda run -n dagi python tui.py` — header appears at top, full width, 6 lines
2. Start a task — left column shows `● Running`, tokens update in center
3. Load a plan — right column shows subtasks with correct status icons
4. Trigger emote change — face updates in left column
5. ESC pause — left column shows `⏸ Paused`
6. Resize terminal — 3-column table reflows correctly (ratio columns)
