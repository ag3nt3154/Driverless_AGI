# Settings Tab Implementation Plan

**Goal:** Add a Settings view to the PySide GUI left rail that edits `{DAGI_ROOT}/.dagi/config.yaml` through a form and a raw-YAML tab, preserving every comment in the file.

**Architecture:** A Qt-free `agent/config_editor.py` owns the document: a `ruamel.yaml` round-trip tree plus text-level helpers for commenting/uncommenting list items, validation, content hashing and atomic, conflict-checked saves. `pyside_gui/sidebars/settings_view.py` is a thin view over one `ConfigDocument`: Form and Raw tabs edit the same document, one dirty flag, Save/Revert, and a file watcher with a conflict banner. `save_config()` is rewritten on top of `config_editor` so there is a single writer.

**Tech Stack:** Python 3, PySide6 6.11, `ruamel.yaml` (new), PyYAML (existing loader), pytest + pytest-qt.

## Global Constraints

- Edits **only** `{DAGI_ROOT}/.dagi/config.yaml` (`agent.config_loader._CONFIG_PATH`). Project `.dagi/config.yaml` is out of scope.
- Changes apply to **new sessions**; no live reload of running sessions. The view states this in a footer line.
- Comments, blank lines, key order and commented-out alternatives in config.yaml must survive load → edit → save.
- Never read the file for editing via `load_raw_config()` (it merges the whole model catalog into the dict).
- Save validates strictly; on any error nothing is written and the error is shown inline.
- `ruamel.yaml` pinned in `requirements-core.txt`; installed into the `dagi` env.
- `agent/config_editor.py` must not import Qt.
- Python: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt <paths>`.
- Qt tests (`pyside_gui/tests/`) cannot load in the sandbox — run them unsandboxed. Ad-hoc Qt scripts must `import pyside_gui` before any `PySide6` import.
- Match surrounding code style (module docstrings, `qss()` theme tokens, `icon()` glyphs). No new files beyond those listed.

---

## Workspace
- **Branch:** `task/settings-tab`
- **Parent:** `main`
- **Starting commit:** `db8dde9`
- **Task folder:** `wiki/tasks/2026-10-14_settings-tab/`

## Overall Status
Complete — all subtasks reviewed and committed; integrated verification done (2026-10-14).

## Notes
- `load_raw_config()` (`agent/config_loader.py:161`) merges `.dagi/model_config/*.yaml` into `raw["models"]`; the old `save_config()` (`:472`) then `yaml.dump`s that dict, which would write the full catalog into config.yaml and strip all comments. `save_config` has no production callers; its tests are `tests/test_config_resolution.py::TestSaveConfig`.
- `resolve_model_config(config_path=...)` loads the model catalog from `config_path.parent / "model_config"`, so validation must use a temp file **in the same `.dagi/` directory** as the real config.
- `resolve_model_config` raises `EnvironmentError` when an API key env var is missing — that is an environment problem, not a config error: report it as a **warning**.
- Loader semantics: `tools: raw.get("tools") or None` — an empty list means *all tools*. Hence the zero-tools guard.
- Tool names: built-ins are registered in `agent/tools.py:create_tool_registry` (`:370`), order pinned by `tests/test_tool_registry_contract.py`. Subagent tools come from `.dagi/subagents/*/main.py` class attribute `name = "..."` (e.g. `run_worker`, `review_work`, `web_research`, `explore_files`, `read_large_file`, `memory_refresh`). Project tools (`<project>/.dagi/tools/*.py`) are out of scope.
- Current config.yaml lists names not registered anywhere (e.g. `tmux_bash`, `enter_plan_mode`) — these must show as "unknown" with a warning, never block save.
- On Windows `os.replace` over a watched file drops it from `QFileSystemWatcher`; re-add the path after every `fileChanged` and after every own save.
- Left rail: `pyside_gui/left_sidebar.py` `_RAIL` tuple (`:29`), buttons built in a loop then `rail_layout.addStretch()` (`:108`); stack index == rail index (`:131`). Settings must be added after the stretch and still map to a stack page.
- ruamel byte-identity depends on indent settings: config.yaml uses `tools:` then `  - read` (sequence indent 4 / dash offset 2 → `yaml.indent(mapping=2, sequence=4, offset=2)`), `width` must be large enough not to re-wrap long lines, and `preserve_quotes = True` (e.g. `"G:\\My Drive\\..."`). If identity is not reachable for a construct, stop and report rather than loosening the test.
- Icons: SVG path snippets in `pyside_gui/icons.py` dict (`:19-39`).

## Open Issues
- None.

## Review Notes
- Subtask 1: `ruamel.yaml==0.19.1`. Test fixture `tests/fixtures/config_editor/config.yaml` is matched by the bare `config.yaml` pattern in `.gitignore` — committed with `git add -f`. `save()` preserves the file's CRLF/LF; `text()` is always LF. Known non-blocking limits: replacing a container value with a different shape misplaces comments (documented in `set()`), a deleted-then-re-set key moves to end of file (Subtask 6: avoid deleting on a transient empty edit), BOM dropped on save.
- Subtask 2: **disabling every tool leaves `tools:` empty → `get("tools") is None` → loader treats it as ALL tools.** Subtask 3 `validate()` must count enabled entries via `doc.list_items("tools")` whenever the `tools:` key exists, not via `get("tools")`. Appended names are written unquoted; flow/scalar values raise `ValueError` on toggle.
- Subtask 3: `validate(doc, *, dagi_root=None, catalog=None)`. **Explicit `tools: null` is a save error** (ruamel renders null as bare `key:`, indistinguishable from all-commented) — "all tools" = remove the key; the `.dagi/config.yaml` comment "Omit (or set to null)" is now inaccurate. `resolve_model_config` never raises for missing API keys (only prints) → `_check_api_key` warns instead. Resolve check skipped when earlier errors exist. Real config: 0 errors; warnings `Unknown tool: tmux_bash`, `Unknown tool: enter_plan_mode`. Minor open: fd leak if `os.fdopen` fails; `.dagi/.config.validate.*.yaml` not gitignored.
- Subtask 4: passed first review. `save_config` now raises `ConfigParseError` on invalid YAML; does not validate (unchanged behaviour). Reviewer saw the conftest RAM watchdog hang at setup in their environment; suites pass with `--noconftest`.
- Subtask 5: review PASS with polish round (public `ConfigDocument.replace_text`; unreadable/non-UTF-8 file → error banner, Save disabled, Raw read-only; banner wrapper hidden). `validate()` runs synchronously on the GUI thread. **Carry forward:** Subtask 6 must disable Form widgets while `_unreadable` is set; Subtask 7 must give the conflict banner its own kind/flag — `_apply_raw` currently clears any "error" banner on a successful Raw→Form switch. Nit: settings_view imports `CommentedMap` to build empty docs (a `ConfigDocument.empty()` classmethod would keep ruamel inside config_editor).
- Subtask 6: wheel guard on unfocused spin/combo; text fields commit on editingFinished; empty commit deletes the key. Open (non-blocking): horizontal scroll below ~265px panel width (long tool names); per-model overrides of context keys not reflected in the form.
- Subtask 7: 200 ms debounce; missing file never treated as a change; OSError on hash retried 10×. Open (non-blocking): half-written external file can flip view to Raw; clearing a conflict on hash-revert also hides any error lines under it.
- Subtask 8: review PASS first round. `LeftSidebar(..., config_path=None)` added for tests. Settings opens half-width. Pre-existing GUI failures (also on `main`): `test_desktop_pet_notepad.py::test_edits_are_flushed_on_hide`, `test_paste_cards.py::test_ctrl_shift_v_pastes_long_text_inline`. Open (non-blocking): no prompt on app close / panel collapse with unsaved settings; reopen clears post-save warning banner; glyph reads slightly sprocket-like.

## Attempts and Resolutions
- **Subtask 1, attempt 1:** review ESCALATE — pruning an emptied nested map dropped the comments after the block -> `set()` now deletes the highest container that would become empty in one `_delete`; plain dict/list values converted to Commented* before attaching moved comments; docstring note on container replacement; tests for os.replace failure + missing parent dir. Re-review PASS.
- **Subtask 2, attempt 1:** review ESCALATE — uncommenting `#   - b` (extra spaces) mis-indented the dash and merged it into the previous item -> `_uncomment_entry` strips all whitespace after `#`; quoted entries recognised; indent filter applied to commented-only blocks; clearer non-block-list error. Re-review PASS.
- **Subtask 3, attempt 1:** review ESCALATE — OSError from resolve (e.g. missing client_script) was only a warning, so a broken config could save -> every resolve exception is now an error; null bool flags treated as absent; per-call mkstemp temp file; drift test asserts order too (web_search/web_fetch moved after read_notepad). Re-review PASS.
- **Subtask 6, attempt 1:** review ESCALATE — with no `tools:` key, the first uncheck wrote a snapshot allowlist that silently dropped project-local and future tools -> Tools checklist edits `disabled_tools` when `tools` is absent (never creates `tools:`); `tools: null` shown disabled with note; spin warnings for invalid file values; computer_use_*/rpa_* disabled when computer_use on with a list; failed commit repopulates form. Re-review PASS.
- **Subtask 7, attempt 1:** review ESCALATE — watching both config.yaml and its directory made ~3–4% of saves fail with WinError 5 on os.replace (also the cause of flaky save tests); clean view reloaded over an uncommitted text field -> watch only the file (dir only while missing); `save()` retries os.replace on PermissionError (5×50 ms); pending text edits committed before deciding reload vs conflict; conflict cleared when disk returns to base_hash. 300-save probe: 0 failures. Re-review PASS.

---

### Subtask 1: ruamel dependency and `ConfigDocument` core ✅ (44710d3)

**Goal:** Load, edit and atomically save config.yaml with comments preserved and conflict detection.

**Requirements:**
- Add `ruamel.yaml==<latest stable in dagi env>` to `requirements-core.txt` (alphabetical position, exact pin) and install it: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -m pip install ruamel.yaml==<ver>`.
- `class ConfigDocument` with:
  - `ConfigDocument.load(path: Path) -> ConfigDocument` — missing file → empty document; records `base_hash` (sha256 of file bytes, `None` if absent).
  - `ConfigDocument.from_text(text: str, path: Path, base_hash: str | None)` — raises `ConfigParseError(message, line)` on invalid YAML or non-mapping root.
  - `text() -> str` — round-trip serialization.
  - `get(key: str, default=None)` — dotted keys, e.g. `"services.message_board.url"`.
  - `set(key: str, value)` — dotted keys; creates intermediate maps; `value=None` deletes the key. Setting an existing scalar keeps its inline comment.
  - `save(expected_hash: str | None = ..., force: bool = False) -> str` — if the on-disk hash ≠ `expected_hash` (default `self.base_hash`) and not `force`, raise `ConfigConflictError`; else write `path.with_suffix(".yaml.tmp")` then `os.replace`; update and return `base_hash`.
- `file_hash(path) -> str | None` helper.
- Encoding UTF-8; preserve the file's line endings as written by ruamel (LF is acceptable).

**Acceptance Criteria:**
- Round-trip of the real `.dagi/config.yaml` content (copied into a fixture) with no edits yields byte-identical text.
- `set("default_model", "x")` changes only that line; commented `# default_model:` alternatives and their order survive.
- Conflict raised when the file changed after load; `force=True` overwrites.
- No Qt imports.

**Files:**
- Modify: `requirements-core.txt`
- Create: `agent/config_editor.py`
- Create: `tests/fixtures/config_editor/config.yaml` (copy of current `.dagi/config.yaml`)
- Test: `tests/test_config_editor.py`

#### Tests
`tests/test_config_editor.py`: round-trip identity; scalar set keeps comments; nested dotted set/create/delete; parse error carries line; missing file loads empty; save conflict / force; atomic write leaves no `.tmp`.

- [ ] **Step 1: Write the failing tests**

```python
def test_round_trip_is_byte_identical(tmp_path):
    src = (FIXTURES / "config.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(src, encoding="utf-8")
    assert ConfigDocument.load(path).text() == src

def test_set_scalar_keeps_commented_alternatives(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    doc.set("default_model", "local_model")
    out = doc.text()
    assert "default_model: local_model" in out
    assert "# default_model: minimax-2.7-openrouter" in out
    assert out.count("\n") == path.read_text(encoding="utf-8").count("\n")

def test_save_refuses_when_file_changed_on_disk(tmp_path):
    path = _copy_fixture(tmp_path)
    doc = ConfigDocument.load(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n# external\n", encoding="utf-8")
    doc.set("context_window", 1000)
    with pytest.raises(ConfigConflictError):
        doc.save()
    doc.save(force=True)
    assert "context_window: 1000" in path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run to verify failure** — `...python.exe -u -m pytest -q -p no:pytest-qt tests/test_config_editor.py` → ImportError.
- [ ] **Step 3: Install ruamel, pin it, implement `ConfigDocument`.**
- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Return for review** with changed files, pinned version, test output.

---

### Subtask 2: Comment-toggle list items (`tools`, `disabled_tools`) ✅ (bf75d46)

**Goal:** Toggle list entries by commenting/uncommenting their line so annotations and section headers survive.

**Requirements:**
- `ConfigDocument.list_items(key: str) -> list[tuple[str, bool]]` — ordered entries of the top-level sequence `key`, including commented-out entries of the form `# - name ...` that sit inside that block (between the `key:` line and the next top-level key), as `(name, enabled)`. Section-header comments (`# ── ... ──`) are not entries.
- `ConfigDocument.set_item_enabled(key: str, name: str, enabled: bool)`:
  - disabling an active `  - name   # note` line rewrites it to `  # - name   # note` (same indentation);
  - enabling a commented entry reverses that in place;
  - enabling a name not present appends `  - name` at the end of the block;
  - if `key` is absent, creates `key:` with the one item;
  - no-op if already in the requested state.
- Implemented as a text transform on `text()` followed by re-parse (`from_text`), keeping `base_hash`.
- `key: null` / `key:` with no items → `list_items` returns `[]`.

**Acceptance Criteria:**
- Disable then re-enable `bash` on the fixture → text identical to the original.
- Disabling the first entry under `# ── Shell tools ──` keeps that header line.
- Parsed `get("tools")` after disabling `bash` no longer contains `"bash"`; `list_items("tools")` still lists it as `("bash", False)` at the same position.

**Files:**
- Modify: `agent/config_editor.py`
- Test: `tests/test_config_editor.py`

#### Tests
Toggle round-trip identity; header preserved; append new; create missing key; commented entries listed in order; `disabled_tools` works the same.

- [ ] **Step 1: Write failing tests**

```python
def test_toggle_bash_round_trips(tmp_path):
    path = _copy_fixture(tmp_path)
    original = path.read_text(encoding="utf-8")
    doc = ConfigDocument.load(path)
    doc.set_item_enabled("tools", "bash", False)
    assert "  # - bash" in doc.text()
    assert "bash" not in doc.get("tools")
    doc.set_item_enabled("tools", "bash", True)
    assert doc.text() == original
```

- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Return for review.**

---

### Subtask 3: Tool catalog (`KNOWN_TOOL_NAMES`) and validation ✅ (e0645d5)

**Goal:** Provide the checklist's name catalog and the strict Save validation.

**Requirements:**
- `agent/tools.py`: module constant `KNOWN_TOOL_NAMES: tuple[str, ...]` — every built-in name `create_tool_registry` can register (all feature flags on: code_mode, computer_use, board callbacks, rpa, show_file, advanced tier, skills, schedules, fallback web tools, write_handoff), excluding dynamically discovered subagent and project tools.
- Drift test in `tests/test_tool_registry_contract.py`: build registries for the maximal configurations used in that file (reuse `_config`/`_names`), strip the fake `spawn_*` / `project_x` names, assert the union equals `set(KNOWN_TOOL_NAMES)`.
- `agent/config_editor.py`:
  - `tool_catalog(dagi_root: Path = DAGI_ROOT) -> list[str]` — `KNOWN_TOOL_NAMES` (lazy import of `agent.tools`) + subagent names parsed statically with `ast` from `.dagi/subagents/*/main.py` (class attr `name = "<str>"`), de-duplicated, order preserved.
  - `@dataclass ValidationResult(errors: list[str], warnings: list[str])`, `ok` property.
  - `validate(doc: ConfigDocument) -> ValidationResult`:
    - errors: `context_window`, `keep_recent_tokens`, `reserve_tokens`, `null_response_retries`, `api_error_retries`, `max_output_tokens`, `max_continuations`, `truncate_edge_chars` present but not a positive int (retries may be 0); `sandbox_mode`/`code_mode`/`computer_use` present but not bool; `default_model` / `worker_model` / `advanced_model` set but not in `list_model_ids()` (catalog read from `doc.path.parent`); `memory_root` set but not an existing directory; `tools` is a list with zero entries enabled (message: `"At least one tool must be enabled."`); `services.message_board.url` set but not `http(s)://host[:port]`.
    - final check: write `doc.text()` to `doc.path.parent / ".config.validate.yaml"`, call `resolve_model_config(config_path=tmp)`, delete tmp in `finally`. `KeyError`/`ValueError`/other exceptions → error with the message; `EnvironmentError` → warning.
    - warnings: tool names in `tools` / `disabled_tools` not in `tool_catalog()` → `"Unknown tool: <name>"`.
- `ConfigDocument.save()` does **not** validate; the view calls `validate` first.

**Acceptance Criteria:**
- Fixture config validates with zero errors (model catalog fixture dir provided in test via `tmp_path/model_config/*.yaml`).
- Each error rule has a failing-input test. Unknown tool yields a warning, not an error. Missing API key yields a warning.
- Temp validation file never remains after `validate`.

**Files:**
- Modify: `agent/tools.py` (constant near `create_tool_registry`)
- Modify: `agent/config_editor.py`
- Test: `tests/test_tool_registry_contract.py`, `tests/test_config_editor.py`

#### Tests
Drift test; catalog includes `run_worker` from a tmp subagent dir; one test per validation rule; env-key warning; temp file cleanup.

- [ ] **Step 1: Write failing tests** (e.g. `test_zero_enabled_tools_is_an_error`, `test_unknown_model_is_an_error`, `test_unknown_tool_is_only_a_warning`, `test_known_tool_names_match_registry`).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_config_editor.py tests/test_tool_registry_contract.py` → PASS.
- [ ] **Step 5: Return for review.**

---

### Subtask 4: Rewrite `save_config` over `config_editor` ✅ (8692fc7)

**Goal:** Single writer path that preserves comments and never dumps the model catalog.

**Requirements:**
- `save_config(default_model: str) -> None`: `doc = ConfigDocument.load(_CONFIG_PATH)`; `doc.set("default_model", default_model)`; `doc.set("max_iterations", None)`; `doc.save(force=True)` (keeps prior last-write-wins semantics). Update docstring.
- Existing `TestSaveConfig` tests stay green.

**Acceptance Criteria:**
- New test: comments survive `save_config`, and a `model_config/` dir next to the file is **not** written into config.yaml (`"models:"` absent when it was absent before).

**Files:**
- Modify: `agent/config_loader.py:472-482`
- Test: `tests/test_config_resolution.py` (`TestSaveConfig`)

- [ ] **Step 1: Write failing tests** (`test_save_config_preserves_comments`, `test_save_config_does_not_inline_model_catalog`).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_config_resolution.py tests/test_config_loader.py` → PASS.
- [ ] **Step 5: Return for review.**

---

### Subtask 5: `SettingsView` shell — Raw tab, dirty state, Save/Revert ✅ (de53742)

**Goal:** A working settings view with the Raw YAML editor and save pipeline.

**Requirements:**
- `pyside_gui/sidebars/settings_view.py`, `class SettingsView(QWidget)`, ctor `SettingsView(config_path: Path | None = None)` (default `agent.config_loader._CONFIG_PATH`). Export from `pyside_gui/sidebars/__init__.py`.
- Layout (top→bottom): title row "Settings" + dirty dot; error/warning banner (hidden when empty); `QTabWidget` with tabs "Form" (placeholder until Subtask 6) and "Raw YAML" (`QPlainTextEdit`, monospace); button row Save / Revert; footer label "Changes apply to new sessions."
- One `ConfigDocument` is the source of truth. Raw edits mark dirty. Leaving the Raw tab re-parses via `from_text`; on `ConfigParseError` stay on Raw and show the error with its line.
- Save: if Raw is current, parse first; `validate`; errors → banner, no write; warnings → shown, save proceeds; `ConfigConflictError` → banner with Reload / Overwrite actions (Subtask 7 reuses). Success → clean, banner shows "Saved." briefly.
- Revert: reload from disk, clean.
- Public: `is_dirty() -> bool`, `reload()`, signal `dirty_changed(bool)`.
- Styling via `qss()` tokens consistent with other sidebars; contents in a `QScrollArea` so the narrow panel works.

**Acceptance Criteria (pytest-qt):** editing raw marks dirty; invalid YAML blocks tab switch and Save; validation error writes nothing; valid save writes and clears dirty; Revert restores disk text.

**Files:**
- Create: `pyside_gui/sidebars/settings_view.py`
- Modify: `pyside_gui/sidebars/__init__.py`
- Test: `pyside_gui/tests/test_settings_view.py`

- [ ] **Step 1: Write failing tests** (fixture writes config + `model_config/m1.yaml` into `tmp_path`; patch `list_model_ids`/catalog to the tmp dir as needed; set API key env var or accept warning).
- [ ] **Step 2: Run unsandboxed** `...python.exe -u -m pytest -q -p no:pytest-qt pyside_gui/tests/test_settings_view.py` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Return for review.**

---

### Subtask 6: Form tab ✅ (75d50d2)

**Goal:** Form widgets for the agreed keys, bound to the shared document.

**Requirements:** Groups (`QGroupBox` or headed sections), each widget reads from and writes to `ConfigDocument` immediately (marks dirty):
- **Models:** `default_model`, `worker_model`, `advanced_model` — `QComboBox` from `list_model_ids()`; worker/advanced have a leading "(same as default)" item that maps to deleting the key. Unknown current value shown as an extra item suffixed " (missing)".
- **Context:** `context_window`, `keep_recent_tokens`, `reserve_tokens` — `QSpinBox` (range 1…10_000_000).
- **Reliability:** `null_response_retries`, `api_error_retries` — `QSpinBox` 0…100.
- **Features:** `sandbox_mode`, `code_mode`, `computer_use` — `QCheckBox`, tooltips from loader semantics.
- **Tools:** checklist built from `list_items("tools")` order, then remaining `tool_catalog()` names alphabetically; unknown names get a "unknown" tag; toggling calls `set_item_enabled`. Same for `disabled_tools` (collapsible, collapsed by default).
- **Paths & services:** `memory_root` — `QLineEdit` + "Browse…" (`QFileDialog.getExistingDirectory`), empty clears the key; `services.message_board.url` and `.bind` — `QLineEdit`.
- Absent keys show the loader default (from `_build_config_from_entry` defaults) as placeholder/initial value and are only written when changed.
- Switching Raw→Form repopulates widgets from the document without marking dirty (block signals while populating).

**Acceptance Criteria:** changing each widget type updates `doc.text()` as expected; unchecking a tool comments its line; Form→Raw shows updated text; populate does not mark dirty.

**Files:**
- Modify: `pyside_gui/sidebars/settings_view.py`
- Test: `pyside_gui/tests/test_settings_view.py`

- [ ] Steps 1–5 as above (failing tests per widget group → implement → pass → return).

---

### Subtask 7: File watcher and conflict banner ✅ (28d1cdd)

**Goal:** Handle external changes to config.yaml.

**Requirements:**
- `QFileSystemWatcher` on the config path; on `fileChanged`: re-add path if dropped; ignore if on-disk hash equals `doc.base_hash` (own save); if clean → `reload()` silently; if dirty → banner "config.yaml changed on disk." with **Reload** (discard edits) and **Overwrite** (save with `force=True` after validation).
- Same banner on `ConfigConflictError` from Save.
- Debounce change bursts (single-shot `QTimer`, ~200 ms).

**Acceptance Criteria:** external write while clean reloads; while dirty shows banner and keeps edits; Reload/Overwrite behave; own save does not trigger a reload or banner; watcher still active after a save (os.replace).

**Files:**
- Modify: `pyside_gui/sidebars/settings_view.py`
- Test: `pyside_gui/tests/test_settings_view.py` (call the change handler directly and also one `qtbot.waitUntil` real-watcher test)

- [ ] Steps 1–5.

---

### Subtask 8: Rail wiring and settings icon ✅ (1b6c691)

**Goal:** Bottom-pinned gear button opening the Settings view.

**Requirements:**
- `pyside_gui/icons.py`: add `"settings"` gear glyph (24×24 stroke style matching neighbours).
- `pyside_gui/left_sidebar.py`: add `("settings", "settings", "Settings")` handled so the button is added **after** `rail_layout.addStretch()`; it behaves like other rail buttons (checkable, toggles panel, styles via `_update_rail_styles`) and its view is in the stack with the stack-index == view-name-index invariant preserved. Expose `settings_view` property.
- On `activate_view("settings")` call `settings_view.reload()` only if not dirty.

**Acceptance Criteria:** `activate_view("settings")` shows `SettingsView`; settings button is the last widget in the rail layout after the stretch; existing `test_left_sidebar.py` tests pass.

**Files:**
- Modify: `pyside_gui/icons.py`, `pyside_gui/left_sidebar.py`
- Test: `pyside_gui/tests/test_left_sidebar.py`

- [ ] Steps 1–5.

---

## Verification

1. Full suite: `C:\Users\alexr\anaconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt` (unsandboxed for Qt) — all pass; compare failures against `main` baseline if any pre-existing.
2. Manual GUI (unsandboxed): launch `pyside_gui.py`, open Settings from the bottom gear:
   - Form shows current values; change `context_window`, uncheck/recheck a tool, Save → `git diff .dagi/config.yaml` shows only those lines changed, comments intact.
   - Raw tab: introduce bad YAML → cannot switch/save, error shown.
   - Edit config.yaml externally while clean → view refreshes; while dirty → banner.
   - Restore `.dagi/config.yaml` to its original content afterwards (`git checkout -- .dagi/config.yaml`) unless the Admiral wants the change.
3. `git diff main --stat` touches only the files listed above plus this plan.

## Verification Results (2026-10-14)
- Non-GUI suite: 2538 passed, 26 skipped, 4 failed — all 4 also fail on `main` (pre-existing): `tests/message_board/test_viewer.py::test_identity_collision_retries_with_new_suffix`, 3× `tests/test_workflow_plan_template.py`.
- GUI suite (`pyside_gui/tests`, unsandboxed): 447 passed, 2 failed — both pre-existing on `main` (notepad web editor load; Windows clipboard).
- Visual check: `LeftSidebar` rendered against a temp copy of the real `.dagi/config.yaml`: Form shows real values, Raw shows all comments, view clean and `doc.text()` byte-identical to the file. Real config never written.

## Next Action
Ask the Admiral whether to merge `task/settings-tab` into `main`; then record wiki entries.
