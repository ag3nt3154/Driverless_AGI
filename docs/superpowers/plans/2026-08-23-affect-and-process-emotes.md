# Affect and Process-State Emotes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace DAGI's free-form emote tool with persistent VAD affect and
automatic process-state image channels, alternated every three seconds in PySide.

**Architecture:** Focused core modules own asset resolution, affect, and process
state. `AgentLoop` integrates their lifecycle without owning media logic; callbacks
carry immutable snapshots to renderers, and a dedicated PySide widget owns only the
presentation timer and Qt media objects.

**Tech Stack:** Python 3.11+, PyYAML, dataclasses, pytest, PySide6/Qt 6, Textual/Rich

**Spec:** `docs/superpowers/specs/2026-08-23-affect-and-process-emotes-design.md`

## Global Constraints

- Use `conda run -n dagi python` for every Python or pytest command.
- Functions <= 100 lines; cyclomatic complexity <= 8; files <= 500 lines.
- Positional parameters <= 5; line length <= 100 characters.
- VAD coordinates clamp to `[-1.0, +1.0]`; initial coordinates are independent
  uniform samples from `[-0.3, +0.3]`.
- Drift is `0.05 * (baseline - current) + uniform(-0.02, +0.02)` per axis.
- PySide alternates VAD and process assets every 3,000 ms without timer resets.
- Production image assets are user-supplied; tests create temporary fixtures.
- Any library or decode error renders `.dagi/emotes/default.md`, then literal
  `DAGI` if that file is unreadable.
- Do not make real model/API calls or incur LLM cost in tests.
- Preserve the current committed PySide styling and thread-safety rules.

---
### Task 1: Typed asset libraries and universal fallback

**Files:**
- Create: `agent/expression_assets.py`
- Create: `tests/test_expression_assets.py`
**Interfaces:**
- Produces: `ImageAsset`, `TextFallback`, `AssetRef`, `VadPoint`, `VadEntry`,
  `VadLibrary`, `ProcessStateLibrary`, and
  `load_fallback(emotes_root: Path) -> TextFallback`.
- `VadLibrary.resolve(vector, current_id, hysteresis) -> tuple[str, AssetRef]`.
- `ProcessStateLibrary.resolve(state: str) -> AssetRef`.
- [x] **Step 1: Write failing tests for valid manifests and path-safe resolution**
```python
def test_vad_library_selects_nearest_entry(tmp_path):
    root = tmp_path / ".dagi" / "emotes"
    (root / "vad").mkdir(parents=True)
    (root / "default.md").write_text("DAGI", encoding="utf-8")
    (root / "vad" / "calm.png").write_bytes(b"fixture")
    (root / "vad" / "manifest.yaml").write_text(
        "version: 1\nemotes:\n  - id: calm\n    file: calm.png\n"
        "    vad: [0.2, -0.5, 0.1]\n",
        encoding="utf-8",
    )
    library = VadLibrary.load(root / "vad", root / "default.md")
    emote_id, asset = library.resolve((0.2, -0.4, 0.1), None, 0.05)
    assert emote_id == "calm"
    assert asset.path == root / "vad" / "calm.png"
```
- [x] **Step 2: Run the focused tests and verify import failures**
Run: `conda run -n dagi python -m pytest tests/test_expression_assets.py -v`
Expected: FAIL because `agent.expression_assets` does not exist.
- [x] **Step 3: Implement immutable asset types and strict YAML loaders**
```python
@dataclass(frozen=True)
class ImageAsset:
    id: str
    path: Path

@dataclass(frozen=True)
class TextFallback:
    path: Path
    reason: str
    text: str

AssetRef = ImageAsset | TextFallback
VadPoint = tuple[float, float, float]
```

Use one private manifest reader and one safe-path validator. Accept `.gif`, `.png`,
`.jpg`, and `.jpeg` case-insensitively. Reject path traversal, non-files, duplicate
IDs, invalid versions, and non-finite/out-of-range VAD values. Cache warning keys so
each distinct error is reported once.
- [x] **Step 4: Add failing malformed-manifest and fallback tests**
Cover invalid whole manifests, one invalid selected asset, escaping paths, required
state keys, exact `tool:read -> tool -> thinking -> idle` lookup, unreadable
`default.md`, and preservation of its Unicode whitespace.
- [x] **Step 5: Implement fallback behavior and hysteresis**
Compare Euclidean distances, keeping `current_id` unless the challenger is at least
`hysteresis` closer. A whole-manifest failure disables only that library; a bad
entry returns `TextFallback` only when selected.
- [x] **Step 6: Run tests and commit**
Run: `conda run -n dagi python -m pytest tests/test_expression_assets.py -v`
Run: `git add agent/expression_assets.py tests/test_expression_assets.py`
Run: `git commit -m "feat: add expression asset libraries"`
### Task 2: Affect values, controller, and replacement tool

**Files:**
- Create: `agent/affect.py`
- Create: `tools/adjust_affect/__init__.py`
- Create: `tools/adjust_affect/_adjust_affect.py`
- Create: `tests/test_affect.py`
- Create: `tests/test_adjust_affect_tool.py`
**Interfaces:**
- Produces: `AffectConfig`, `AffectVector`, `AffectRestore`, `AffectSnapshot`, and
  `AffectController`.
- `AffectVector.as_tuple() -> VadPoint` adapts controller state to Task 1.
- `AffectController.adjust(delta: AffectVector) -> AffectSnapshot`.
- `AffectController.drift() -> AffectSnapshot` and `context_line() -> str`.
- `AdjustAffectTool(controller: AffectController)` exposes three required deltas.
- [x] **Step 1: Write failing vector, initialization, clamp, and drift tests**
```python
def test_seeded_drift_pulls_toward_baseline():
    library = MagicMock()
    library.resolve.return_value = ("focused", MagicMock())
    rng = MagicMock()
    rng.uniform.return_value = 0.0
    controller = AffectController(
        library,
        baseline=AffectVector(0.0, 0.0, 0.0),
        current=AffectVector(1.0, -1.0, 0.5),
        rng=rng,
    )
    assert controller.drift().current == AffectVector(0.95, -0.95, 0.475)
```

Also assert independent baselines stay in range, non-finite construction fails,
adjustments clamp per axis, records publish after validation, and listener changes
take effect on a controller reused by another loop.
- [x] **Step 2: Run the tests and verify missing imports**
Run: `conda run -n dagi python -m pytest tests/test_affect.py -v`
Expected: FAIL because `agent.affect` does not exist.
- [x] **Step 3: Implement the controller with injected collaborators**
```python
class AffectController:
    def __init__(self, library, *, config=AffectConfig(), baseline=None,
                 current=None, current_emote_id=None, rng=None, record=None,
                 on_change=None):
        self._library = library
        self._record = record or (lambda event, payload: None)
        self._on_change = on_change or (lambda snapshot: None)

    def set_listener(self, listener: Callable[[AffectSnapshot], None],
                     *, emit_current: bool = True) -> None:
        self._on_change = listener
```

Keep mutation, persistence payload creation, and publication in one private method so
adjust and drift cannot diverge. `AffectRestore` carries baseline, current, and emote
ID without importing session/history modules.
- [x] **Step 4: Write the failing tool schema and output tests**
Assert `minimum=-1`, `maximum=1`, all three required properties, clamped adjustment,
and output containing prior vector, requested delta, result, and selected ID.
- [x] **Step 5: Implement `AdjustAffectTool` and remove no old files yet**
```python
def run(self, valence_delta: float, arousal_delta: float,
        dominance_delta: float) -> str:
    delta = AffectVector(valence_delta, arousal_delta, dominance_delta)
    before = self._controller.current
    snapshot = self._controller.adjust(delta)
    return (
        f"Affect: {before.as_tuple()} + {delta.as_tuple()} -> "
        f"{snapshot.current.as_tuple()}\nEmote: {snapshot.emote_id}"
    )
```
- [x] **Step 6: Run focused tests and commit**
Run: `conda run -n dagi python -m pytest tests/test_affect.py tests/test_adjust_affect_tool.py -v`
```bash
git add agent/affect.py tools/adjust_affect tests/test_affect.py \
  tests/test_adjust_affect_tool.py
git commit -m "feat: add persistent affect controller tool"
```
### Task 3: Session persistence and historical restore

**Files:**
- Modify: `agent/session.py:34-299`
- Modify: `agent/history.py:71-87`
- Modify: `tests/test_session_tracker.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_history_integration.py`
**Interfaces:**
- Consumes: `AffectController`, `AffectRestore`, and `AffectSnapshot` from Task 2.
- Produces: `SessionTracker.affect_controller`, `bind_affect_controller(controller)`,
  `record_affect(event_type, payload)`, and `load_affect_restore(path)`.
- Private `_load_jsonl(path)` and `_parse_affect_restore(init, latest)` helpers are
  defined in `agent/history.py` and shared by restoration functions.
- [x] **Step 1: Write failing session-record tests**
```python
def test_record_affect_writes_structured_jsonl(tmp_path):
    tracker = SessionTracker("m", logs_dir=tmp_path)
    tracker.record_affect("affect_adjust", {"current": [0.2, 0.1, -0.1]})
    records = [json.loads(line) for line in tracker._path.read_text().splitlines()]
    assert records[-1]["type"] == "affect_adjust"
    assert records[-1]["current"] == [0.2, 0.1, -0.1]
```

Also assert a controller bound to the root tracker survives reuse and child trackers
cannot replace or mutate that binding.
- [x] **Step 2: Implement root-only controller binding and affect writes**
Initialize `_affect_controller = None` only on root trackers. `record_affect` must use
`_write()` so records receive timestamps and share the root session file.
- [x] **Step 3: Write failing history restoration tests**
Cover latest valid affect record, preservation of the original `affect_init` baseline,
legacy logs returning `None`, and malformed values returning `None` with one warning.
- [x] **Step 4: Implement `load_affect_restore` without changing raw-message APIs**
```python
def load_affect_restore(path: Path | str) -> AffectRestore | None:
    records = _load_jsonl(path)
    init = next((r for r in records if r.get("type") == "affect_init"), None)
    latest = next((r for r in reversed(records)
                   if r.get("type") in AFFECT_RECORD_TYPES), None)
    return _parse_affect_restore(init, latest)
```

Refactor `load_raw_messages` to share `_load_jsonl`; preserve all current return values.
- [x] **Step 5: Run persistence/history tests and commit**
Run:
```powershell
conda run -n dagi python -m pytest `
  tests/test_session_tracker.py tests/test_history.py `
  tests/test_history_integration.py -v
```
```bash
git add agent/session.py agent/history.py tests/test_session_tracker.py \
  tests/test_history.py tests/test_history_integration.py
git commit -m "feat: persist and restore affect state"
```
### Task 4: Automatic process-state controller

**Files:**
- Create: `agent/process_state.py`
- Create: `tests/test_process_state.py`
**Interfaces:**
- Consumes: `ProcessStateLibrary` and `AssetRef` from Task 1.
- Produces: immutable `ProcessSnapshot` and `ProcessStateController` methods
  `idle()`, `thinking()`, `tool_started(name)`, `tool_ended()`, `paused()`, and
  `error()`.
- [x] **Step 1: Write failing state transition and idempotency tests**
```python
def test_tool_lifecycle_publishes_exact_states():
    library = MagicMock()
    library.resolve.side_effect = lambda state: ImageAsset(state, Path(f"{state}.gif"))
    seen = []
    state = ProcessStateController(library, seen.append)
    state.thinking()
    state.tool_started("read")
    state.tool_ended()
    assert [item.state for item in seen] == ["idle", "thinking", "tool:read", "thinking"]
```

Test repeated identical transitions emit once, pause/error stay until an explicit next
transition, and library fallbacks are passed through without state rewriting.
- [x] **Step 2: Run tests and verify the module is missing**
Run: `conda run -n dagi python -m pytest tests/test_process_state.py -v`
Expected: FAIL because `agent.process_state` does not exist.
- [x] **Step 3: Implement the minimal state machine**
Use one `_transition(state)` method: resolve the asset, construct `ProcessSnapshot`,
skip exact duplicate snapshots, store, then publish. Do not import loop or Qt modules.
- [x] **Step 4: Run tests and commit**
Run: `conda run -n dagi python -m pytest tests/test_process_state.py -v`
Run: `git add agent/process_state.py tests/test_process_state.py`
Run: `git commit -m "feat: add automatic process state controller"`
### Task 5: Configuration, registry, and prompt migration

**Files:**
- Modify: `agent/loop.py:154-228`
- Modify: `agent/config_loader.py:131-186`
- Modify: `agent/tools.py:84-317`
- Modify: `.dagi/config.yaml:31-68`
- Modify: `.dagi/prompts/main/main_system.md:18-23`
- Modify: `tests/test_config_loader.py`
- Modify: `tests/test_tool_filter.py`
**Interfaces:**
- Consumes: `AffectConfig`, `AffectController`, `AdjustAffectTool`.
- Produces: `AgentConfig.affect_drift_pull`, `affect_drift_noise`, and
  `affect_emote_hysteresis`; registry argument `affect_controller`.
- [x] **Step 1: Write failing config validation tests**
Assert defaults `0.05`, `0.02`, `0.05`; configured overrides; rejection of negative,
non-finite, or noise-above-one values with messages naming the bad field.
- [x] **Step 2: Implement one `_load_affect_config(raw)` validator**
```python
def _load_affect_config(raw: dict) -> tuple[float, float, float]:
    data = raw.get("affect") or {}
    values = (
        float(data.get("drift_pull", 0.05)),
        float(data.get("drift_noise", 0.02)),
        float(data.get("emote_hysteresis", 0.05)),
    )
    if not all(math.isfinite(value) and value >= 0 for value in values):
        raise ValueError("affect values must be finite and non-negative")
    if values[1] > 1.0:
        raise ValueError("affect.drift_noise must be <= 1.0")
    return values
```

Pass the values through worker/advanced config construction unchanged.
- [x] **Step 3: Write failing registry migration tests**
Build a normal registry with a fake controller and assert `adjust_affect` exists and
`emote` does not. Assert config filtering keeps `adjust_affect` only when named and
plan/subagent registries never expose it.
- [x] **Step 4: Replace registration and configuration references**
Add `affect_controller: AffectController | None` to `create_tool_registry`. Register
`AdjustAffectTool` only in normal main mode when the controller is present. Replace
the `.dagi/config.yaml` allowlist item and system-prompt instruction with relative VAD
language. Leave the dormant legacy package until Task 6 removes its last TUI consumer.
- [x] **Step 5: Run config/registry tests and commit**
Run:
```powershell
conda run -n dagi python -m pytest `
  tests/test_config_loader.py tests/test_tool_filter.py `
  tests/test_subagent_configs.py -v
```
```bash
git add agent/loop.py agent/config_loader.py agent/tools.py .dagi/config.yaml \
  .dagi/prompts/main/main_system.md tests/test_config_loader.py \
  tests/test_tool_filter.py
git commit -m "feat: replace emote tool configuration"
```
### Task 6: AgentLoop lifecycle, dynamic context, callbacks, and TUI

**Files:**
- Create: `agent/dynamic_context.py`
- Modify: `agent/loop.py:230-1799`
- Modify: `tui/callbacks.py:125-188`
- Modify: `tui/sidebar.py:1-140`
- Modify: `tui/app.py:78-348`
- Modify: `pyside_gui/app.py:46-51,286-295,405-419`
- Delete: `tools/emote/__init__.py`
- Delete: `tools/emote/_emote.py`
- Modify: `tests/test_dynamic_context.py`
- Modify: `tests/test_agent_loop.py`
- Modify: `tests/test_tui_callbacks.py`
- Modify: `tests/tui/test_sidebar_render.py`
**Interfaces:**
- Consumes all core controllers plus session/history interfaces from Tasks 1-4.
- Produces callbacks `on_affect_changed(AffectSnapshot)` and
  `on_process_state_changed(ProcessSnapshot)`; removes `on_emote`.
- Adds the `AgentLoop` keyword `initial_affect: AffectRestore | None = None`.
- [x] **Step 1: Write failing loop construction and context tests**
Assert a new tracker creates/binds one affect controller, a reused tracker rebinds the
new callback listener without resetting state, and `_build_dynamic_context()` includes:

```text
Affect: V=+0.42 A=+0.31 D=+0.18 | emote=focused
```

Assert restored affect seeds a new tracker and legacy restoration randomizes safely.
- [x] **Step 2: Extract and extend the dynamic context builder**
Move the existing Python-environment and plan-board formatter into
`agent/dynamic_context.py` as `build_dynamic_context(config, affect_line)`. Keep all
current output byte-compatible, append the affect line, and make `AgentLoop` delegate
to it. This offsets lifecycle integration growth in the already oversized loop file.
- [x] **Step 3: Construct libraries/controllers before the tool registry**
Load from `DAGI_ROOT / ".dagi" / "emotes"`. Reuse `tracker.affect_controller` when
present; otherwise create from `initial_affect`, bind, record `affect_init` when new,
and pass the controller to `create_tool_registry`.
- [x] **Step 4: Write failing lifecycle-order tests with fake controllers**
Assert `thinking` before every API attempt, `tool:<name>` before `on_tool_start`,
`thinking` after bookkeeping, drift after `STEP_END` only when continuing, `idle` on
all completed returns, `paused` from `pause()`, `thinking` from resume, and `error`
before fatal `on_error`.
- [x] **Step 5: Integrate lifecycle calls through small helper methods**
Add `_set_thinking()`, `_finish_iteration(should_continue)`, and `_finish_process(state)`
helpers rather than duplicating transitions across return paths. Nested child relay
events must not update root process state.
- [x] **Step 6: Migrate restoration and TUI rendering**
PySide and TUI store `_restore_affect` beside `_restore_initial_messages`, load it from
the selected log, and pass it once to `AgentLoop`. TUI callbacks update textual VAD
ID/vector and process key. Remove `pad_to_lines`/old emote resolution imports, then
delete the now-unreferenced `tools/emote` package.
- [x] **Step 7: Run loop/TUI tests and commit**
Run:
```powershell
conda run -n dagi python -m pytest `
  tests/test_dynamic_context.py tests/test_agent_loop.py `
  tests/test_tui_callbacks.py tests/test_history_integration.py `
  tests/tui/test_sidebar_render.py -v
```
```bash
git add agent/dynamic_context.py agent/loop.py tui pyside_gui/app.py tools/emote \
  tests/test_dynamic_context.py \
  tests/test_agent_loop.py tests/test_tui_callbacks.py tests/test_history_integration.py \
  tests/tui/test_sidebar_render.py
git commit -m "feat: integrate affect and process lifecycle"
```
### Task 7: PySide expression widget and three-second rotation

**Files:**
- Create: `pyside_gui/expression_widget.py`
- Create: `pyside_gui/menu_style.py`
- Create: `pyside_gui/tests/test_expression_widget.py`
- Modify: `pyside_gui/bridge.py:12-183`
- Modify: `pyside_gui/right_sidebar.py:1-205`
- Modify: `pyside_gui/app.py:96-104,175-208`
- Modify: `pyside_gui/tests/test_bridge.py`
**Interfaces:**
- Consumes: `AffectSnapshot`, `ProcessSnapshot`, `ImageAsset`, `TextFallback`.
- Produces: `ExpressionWidget.update_affect(snapshot)` and
  `update_process(snapshot)` Qt slots.
- Bridge signals: `affect_changed = Signal(object)` and
  `process_state_changed = Signal(object)`.
- [x] **Step 1: Write failing bridge snapshot tests**
Connect each new signal, invoke the corresponding callback, process Qt events, and
assert the exact snapshot object is delivered. Remove the old emote signal assertion.
- [x] **Step 2: Write failing widget timer and caption tests**
Use a controllable `QTimer` or call the timeout slot directly. Assert initial VAD,
strict VAD/process alternation, no timer restart on snapshot arrival, VAD caption
format, and process-state caption format.
- [x] **Step 3: Implement the widget's channel state and text fallback first**
```python
@Slot()
def _toggle_channel(self) -> None:
    self._visible_channel = (
        "process" if self._visible_channel == "affect" else "affect"
    )
    self._render_visible()
```

Use a single image label plus caption label. Preserve whitespace and monospaced font
for `TextFallback`; never restart `_timer` in either update slot.
- [x] **Step 4: Add failing static-image and GIF lifecycle tests**
Mock `QMovie` to assert the previous movie's `stop()` runs before replacement. Create
a tiny PNG fixture to assert aspect-ratio scaling after `resizeEvent`. Make an invalid
image path resolve to the loaded `default.md` text.
- [x] **Step 5: Implement `QPixmap`/`QMovie` rendering and sidebar composition**
Keep Qt media ownership entirely in `expression_widget.py`. Replace `_emote_label`
with `ExpressionWidget(dagi_root / ".dagi" / "emotes" / "default.md")`. Wire both
bridge signals directly to its update slots; keep all sidebar sections below intact.
Move the existing menu stylesheet byte-for-byte to `menu_style.py` so modified
`pyside_gui/app.py` returns below 500 lines without changing appearance.
- [x] **Step 6: Run PySide tests and commit**
Run:
```powershell
conda run -n dagi python -m pytest `
  pyside_gui/tests/test_bridge.py `
  pyside_gui/tests/test_expression_widget.py `
  pyside_gui/tests/test_commands.py -v
```
```bash
git add pyside_gui/expression_widget.py pyside_gui/menu_style.py pyside_gui/bridge.py \
  pyside_gui/right_sidebar.py pyside_gui/app.py pyside_gui/tests
git commit -m "feat: render alternating expression channels"
```
### Task 8: Full regression, project context, and final review

**Files:**
- Modify: `AGENTS.md`
- Modify only if tests expose documented coupling: affected existing tests
**Interfaces:**
- Consumes the completed feature; produces no new runtime API.
- [x] **Step 1: Run all focused feature suites together**
Run:
```powershell
conda run -n dagi python -m pytest `
  tests/test_expression_assets.py tests/test_affect.py `
  tests/test_adjust_affect_tool.py tests/test_process_state.py `
  tests/test_session_tracker.py tests/test_history.py `
  tests/test_dynamic_context.py tests/test_agent_loop.py `
  tests/test_tui_callbacks.py tests/tui/test_sidebar_render.py `
  pyside_gui/tests/test_bridge.py `
  pyside_gui/tests/test_expression_widget.py -v
```
Expected: PASS with no real provider calls.
- [x] **Step 2: Run the complete test suite**
Run: `conda run -n dagi python -m pytest -v`
Expected: PASS. If a documented pre-existing failure remains, record its exact test
name and unchanged reproduction; do not label the suite passing.
- [x] **Step 3: Verify file and complexity constraints**
Run:
```powershell
$sourceFiles = rg --files agent tools pyside_gui tui tests
$sourceFiles | ForEach-Object {
    $count = (Get-Content $_).Count
    if ($count -gt 500) { "$count $_" }
}
```
Expected: new files stay below 500 lines; `pyside_gui/app.py` returns below 500 lines;
`agent/loop.py` does not grow from its pre-task size. Review each changed function for
<=100 lines, <=8 branches, <=5 positional parameters, and <=100 columns.
- [x] **Step 4: Update project context**
Invoke the `update-project-context` skill. Record the new controllers, asset folders,
tool replacement, callback contract, PySide widget, session restoration, and any
verified errors. Preserve the Behavioral Guidelines section verbatim.
- [x] **Step 5: Inspect the final diff and commit context updates**
Run: `git diff --check` and `git status --short`.
Expected: no whitespace errors and only intended final-review/context changes.

Run: `git add AGENTS.md`
Run: `git commit -m "docs: update context for expression channels"`
- [x] **Step 6: Request code review and resolve findings**
Invoke `superpowers:requesting-code-review`. Re-run the smallest affected test after
each fix, then repeat the complete suite before claiming completion.
