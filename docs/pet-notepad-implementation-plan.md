# Pet Notepad — Implementation Plan

Branch: `feat/pet-notepad` · Date: 2026-09-30 · Status: **approved** (Vditor 3.11.3, highlight.js included)

A pinote-style WYSIWYG markdown notepad attached below the dagi desktop pet,
with KaTeX math, global auto-save, "Save as…", and a read-only `read_notepad`
agent tool.

## Agreed design (from grilling session)

| Area | Decision |
|---|---|
| Editor | Vditor, vendored (trimmed) into `pyside_gui/resources/notepad/vditor/`, hosted in `QWebEngineView`, no CDN at runtime |
| Mode | Instant-rendering (IR) only, no toolbar, KaTeX only, Catppuccin-reskinned dark theme, opaque |
| Window | One combined frameless always-on-top window: pet on top, header strip + editor below |
| Open/close | Right-click pet → context menu (Open/Close notepad, Save as…). Left-click = drag only. Header ✕ also collapses |
| `/show-pet` | Toggles pet only; notepad always starts collapsed; flush before hide |
| Geometry | Collapsed 210×182; expanded ≈360×(182+24+420); shift up/left to stay on screen; resize grip; size persisted |
| Storage | Global `DAGI_ROOT/.dagi/notepad/notepad.md`, autosave 1 s debounce + on collapse/hide/quit |
| Save as | Context menu + Ctrl+S → file dialog starting in project dir; writes a copy, backing file unchanged |
| External edits | `QFileSystemWatcher`: reload if no unsaved edits; else local wins and disk version → `conflict-<ts>.md` + header notice; ignore own writes (hash check) |
| Lifecycle | Editor created lazily on first open; collapse hides (keeps undo); `state.json` stores notepad size only |
| Agent tool | `read_notepad`, no params, read-only, always registered (GUI/TUI/Telegram), not in subagent lists; calls optional `on_flush_notepad` (≤2 s) then reads file; header w/ mtime + char count; truncate ~20k chars |

## Open decisions for approval

1. **Vditor version** — recommend **pin 3.11.3** (mature line). 4.0.0 is a
   one-month-old major release; we can bump later with the vendoring script.
2. **Code-block highlighting** — recommend **include highlight.js** (+1.1 MB,
   one dark style). Total vendored ≈ **6 MB** (lute 3.6 MB, KaTeX ~0.8 MB with
   woff2-only fonts, hljs 1.1 MB, core ~0.4 MB). Dropping hljs → ≈ 5 MB, code
   blocks unhighlighted.

## Subtasks (one commit each)

### T1 — Vendor Vditor
- `scripts/vendor_vditor.py`: `VDITOR_VERSION` constant; download npm tarball
  (`registry.npmjs.org/vditor/-/vditor-<v>.tgz`), verify `dist.integrity`
  (sha512), extract only: `index.min.js`, `index.css`,
  `css/content-theme/dark.css`, `js/lute/lute.min.js`,
  `js/katex/{katex.min.js,katex.min.css,fonts/*.woff2}`, `js/icons/ant.js`,
  `js/i18n/en_US.js`, `js/highlight.js/{highlight.min.js,third-languages.js,styles/<dark>.min.css}`.
  Write `VERSION` and copy `LICENSE` (MIT) + hljs/KaTeX licences.
- Commit the resulting `pyside_gui/resources/notepad/vditor/` tree.
- Test: script's file-filter function unit-tested (no network in tests).

### T2 — Notepad store (pure Python, no Qt)
- `agent/notepad_store.py`: `NOTEPAD_DIR`, `notepad_path()`, `read_text()`,
  atomic `write_text()` (tmp + `os.replace`), `content_hash()`,
  `backup_conflict(text) -> Path`, `load_state()/save_state()` (size only,
  tolerant of corrupt JSON).
- Tests: `tests/test_notepad_store.py` (tmp dir, atomic write, conflict naming,
  corrupt state.json).

### T3 — `read_notepad` tool
- `tools/read_notepad/` (`ReadNotepadTool`, no params): call
  `on_flush_notepad()` if provided (swallow errors/timeouts, note "may be
  stale"), read file, header `Notepad (last edited <iso>, <n> chars)`, empty →
  "Notepad is empty.", truncate at 20 000 chars with marker.
- `AgentCallbacks.on_flush_notepad: Callable[[], None] | None = None` in
  `agent/_loop_config.py`.
- Register unconditionally in `create_tool_registry` (not added to
  `_tools_from_list`; inherited subagent registries already block unlisted tools).
- Tests: `tests/test_read_notepad_tool.py` (empty, content, truncation, flush
  called, flush raising).

### T4 — Editor widget (web side)
- `pyside_gui/resources/notepad/notepad.html|.js|.css`: Vditor IR,
  `toolbar: []`, `cdn` → local `vditor/` folder, KaTeX engine, hljs local,
  Catppuccin CSS overrides; `QWebChannel` bridge: JS → Py `contentChanged`
  (throttled), `saveRequested` (Ctrl+S); Py → JS `setMarkdown`,
  `getMarkdown` (callback). Links → `QDesktopServices.openUrl`.
- `pyside_gui/notepad_editor.py`: `NotepadEditor(QWebEngineView)` with
  `ready`, `content_changed(str)`, `save_requested` signals and
  `set_markdown()`; custom `QWebEnginePage.acceptNavigationRequest` for
  external links; local-file access settings.
- Tests (pytest-qt): loads, `set_markdown` → `content_changed` round-trip
  preserves `$e^{i\pi}$` and `$$\int_0^1 x\,dx$$` verbatim.

### T5 — Notepad controller (save / watch / conflict)
- `pyside_gui/notepad_controller.py` (`QObject`, no widgets): holds current
  text + dirty flag; 1 s debounce autosave via store; `flush()`;
  `QFileSystemWatcher` with own-write hash suppression, re-add path after
  atomic replace; reload-or-conflict logic; `save_as(path)`; signals
  `external_reload(str)`, `conflict_saved(Path)`, `dirty_changed(bool)`.
- Tests: debounce, flush, external change clean → reload, dirty → conflict
  file + local wins, own writes ignored, save-as writes copy.

### T6 — Combined pet window
- Refactor `pyside_gui/desktop_pet.py`: pet label stays top; lazily-built
  notepad panel (header strip: label, saved dot, ✕, drag handle; editor;
  `QSizeGrip`). Right-click context menu (menu_style). `expand()/collapse()`
  with on-screen clamp and restore of pre-expand position. Hide/close →
  `controller.flush()`. `showEvent` from `/show-pet` → collapsed.
  Save-as dialog starts in project dir (setter from app).
- Keep file < 500 lines (split panel into `pyside_gui/notepad_panel.py`).
- Tests: expand/collapse geometry + clamp (offscreen), context-menu actions,
  hide flushes, starts collapsed after re-show.

### T7 — GUI wiring
- `bridge.py`: `on_flush_notepad` → emit signal to GUI thread with
  `threading.Event`, wait ≤2 s (pattern of `_ask_user`); no-op if notepad
  never opened.
- `app.py`: pass project path to pet; `closeEvent` flush; update project
  path on `/wd`.
- Tests: bridge flush round-trip + timeout.

### T8 — Docs
- `README.md`: desktop pet section (notepad, math, storage path, save as),
  tool table row for `read_notepad`, vendoring script note.
- `TODO.md`: completed entry; follow-ups (write/append tool, opacity,
  images, Vditor 4.x bump).

## Verification
- Per subtask: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest <new tests> pyside_gui/tests tests -q`
- Final: full suite + manual run of the GUI (`/show-pet`, right-click → open,
  type markdown + math, Save as, external edit, `read_notepad` from dagi),
  then hand over for your check (step 5).
