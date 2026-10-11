# RPA + Computer Use Implementation Plan

**Goal:** Let dagi use desktop apps and Firefox interactively, record a successful exploration as a declarative workflow, replay it without a model, and repair it with the Admiral's approval.

**Architecture:** A new package `rpa/` holds the drivers (Windows UIA, Firefox via geckodriver, screen), one shared resolver, observations, the desktop lock, the workflow format, the compiler and the interpreter. `rpa/` never imports `agent/`, so `python -m rpa run` works with no agent. Thin dagi tools in `tools/ui/` and `tools/rpa/` expose it to the agent; the GUI adds a Workflows view on top.

**Tech Stack:** Python 3.11+ (`dagi` env), `uiautomation` 2.0.29, `selenium` 4.51.0 + conda-forge `geckodriver` 0.37.1 + conda-forge `firefox` 157.0.1, `mss` 10.2.0, Pillow (already present), PyYAML (already present), PySide6 (GUI stage only), pytest.

Spec: decisions D1–D15 and S0 results in [`research.md`](research.md).

## Global Constraints

- `rpa/` must not import `agent`, `tools`, `pyside_gui`, `tui` or `tg` (D11). An import test enforces it.
- Global config `computer_use: false` by default (D11). With `false`, no `ui_*` or `rpa_*` tool is registered.
- Locator ladder order (D2): rung 1 `automation_id` / DOM `data-testid`·`id`; rung 2 `role + name`; rung 3 OCR text; rung 4 image crop; rung 5 window-relative `coords`, opt-in per step with `allow_coords: true`. v1 resolves rungs 1, 2 and 5 only. v1 records rung 3 (OCR text is the element name) and rung 4 (a crop PNG) data for v2.
- Resolve rule (D2): first rung with exactly one match wins; more than one match → `Ambiguous` (HALT / refuse); no match on all rungs → `NotFound`. Never guess.
- Agent tools (D3): exactly `ui_roots`, `ui_observe`, `ui_act`, `ui_wait`. Every `ui_act` names an observation id. Every successful `ui_act` inside a recording goes to the trace.
- Screenshots (D4, S0): default width 1280 px; keep only the last 3 UI screenshots in a request; older ones become `[screenshot obs_N elided]` at request-build time; the event log is not changed.
- Set-of-marks overlay (S0): mark interactive leaf elements only; put each label inside its box's top-left corner; never mark containers; never draw zero-area boxes.
- Desktop lock (D4, D10): one process-wide lock file `{pid, agent, since}`; taken by the first act that needs real input; a claimant takes over when the holder PID is dead; browser-only (WebDriver) acts do not take it.
- Safety (D5): per-app / per-origin permission via `ask_user` on first act; sensitive-action confirm (keywords: send, submit, delete, remove, pay, purchase, buy, transfer, post, publish, confirm, sign out, log out) or `sensitive: true`; password fields render `[secure]` and are never in outlines, traces or logs; secrets only through `secrets: {env: NAME}`; in `autonomous` mode every gate denies.
- Replay confirm (D5): `confirm: once` (default when flagged) is pre-approved with the workflow; `confirm: every_run` asks each run; each approved confirm step stores a content hash; a changed step needs re-approval.
- Scheduler (D6): `scheduler/` is not changed in this task.
- Browser (D9): stock conda-forge Firefox via geckodriver + Selenium; persistent profile `.dagi/rpa/firefox-profile/`; dagi's own outline JS; uploads via `send_keys(path)`.
- Desktop driver (D14): `uiautomation`; restore a minimized window before observing it (S0); launch known Electron apps with `--force-renderer-accessibility` (S0).
- Workflow lifecycle (D8): `draft` → verify run → `approved`; also `degraded` (last run used a lower rung) and `halted`. `rpa_run` warns on non-approved workflows.
- Compiler (D8): deterministic; model cleanup may only delete, rename, parameterize and flag steps; it can never add a locator.
- Repair (D7): offered on halt in chat, never automatic; re-run from step 1 by default; resume from step N only if that step's pre-check passes.
- Tests (D12): unit tests run anywhere with fake drivers; desktop tests use marker `desktop` and are skipped unless `DAGI_DESKTOP_TESTS=1`; run unsandboxed.
- Tool registration order is the schema order (`wiki/tool-registration-order-is-schema-order.md`): update `tests/test_tool_registry_contract.py` in the same change that adds tools.
- Python: call `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt …` directly (no `conda run`).

---

## Stage S1 — Live computer use

### Subtask 1: Package skeleton, dependencies, test harness — ✅ `9b4ae903`

**Goal:** Create `rpa/` with its isolation rule, the dependency file and the `desktop` test marker.
**Requirements:**
- `rpa/__init__.py` with `RPA_HOME_DIRNAME = ".dagi/rpa"` and `class RpaError(Exception)` (base for all rpa errors).
- `requirements-rpa.txt` (pip pins: `uiautomation==2.0.29`, `selenium==4.51.0`, `mss==10.2.0`, `psutil==7.2.2` — psutil is only in `requirements-dev.txt` today) and a comment with the conda line `conda install -n dagi -c conda-forge firefox=157.0.1 geckodriver=0.37.1`.
- `pyproject.toml`: add `"rpa*"` to `[tool.setuptools.packages.find] include`; add optional extra `rpa`; add marker `desktop`.
- `tests/conftest.py`: skip `desktop`-marked tests unless env `DAGI_DESKTOP_TESTS=1`.
**Acceptance Criteria:**
- `tests/rpa/test_isolation.py` fails if any module under `rpa/` imports `agent`, `tools`, `pyside_gui`, `tui` or `tg` (AST scan of all `rpa/**/*.py`).
- A dummy `@pytest.mark.desktop` test is skipped by default and runs with `DAGI_DESKTOP_TESTS=1`.

**Files:**
- Create: `rpa/__init__.py`, `requirements-rpa.txt`, `tests/rpa/__init__.py`, `tests/rpa/test_isolation.py`
- Modify: `pyproject.toml:13-59`, `tests/conftest.py`

#### Tests
- `tests/rpa/test_isolation.py` — AST import scan; `desktop` marker skip behaviour.

- [ ] **Step 1: Write the failing test**

```python
import ast, pathlib
FORBIDDEN = {"agent", "tools", "pyside_gui", "tui", "tg"}
def test_rpa_does_not_import_dagi_agent_layers():
    bad = []
    for path in pathlib.Path("rpa").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            bad += [f"{path}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert pathlib.Path("rpa/__init__.py").exists() and bad == []
```
- [ ] **Step 2: Run test to verify it fails** — `pytest tests/rpa/test_isolation.py -v` → FAIL (`rpa/__init__.py` missing).
- [ ] **Step 3: Write minimal implementation** — create the files above; conftest hook:

```python
def pytest_collection_modifyitems(config, items):
    if os.environ.get("DAGI_DESKTOP_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="desktop test: set DAGI_DESKTOP_TESTS=1 (run unsandboxed)")
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)
```
- [ ] **Step 4: Run tests to verify they pass** — `pytest tests/rpa -v` → PASS.
- [ ] **Step 5: Return for review.**

### Subtask 2: Driver interface, data model, fake driver — ✅ `c08baefa`

**Goal:** One protocol that the UIA, browser and fake drivers implement, plus the shared data types.
**Requirements:**
- `rpa/model.py` dataclasses (frozen where possible):
  - `Root(id: str, kind: Literal["window","browser"], title: str, pid: int | None, url: str | None, app: str)` — `app` is the exe name or the browser origin (used by D5 permissions).
  - `Element(index: int, role: str, name: str, automation_id: str | None, bbox: tuple[int,int,int,int], value: str | None, secure: bool, interactive: bool, path: tuple[str, ...])` — `path` = role/name of ancestors (for rung-2 scoping); `value` is `"[secure]"` when `secure`.
  - `Locator` = `dict` with exactly one key of `uia`, `css`, `aria`, `ocr`, `image`, `coords` (validated by `validate_locator`).
  - `Outline(root: Root, elements: list[Element], taken_at: float)`.
- `rpa/drivers/base.py`: `class Driver(Protocol)` with `roots() -> list[Root]`, `outline(root, *, query=None, depth=None) -> Outline`, `find(root, locator) -> list[Element]`, `act(root, element, action, value=None) -> None`, `screenshot(root, region=None) -> PIL.Image`, `needs_desktop_lock(action) -> bool`, `launch(target: str) -> Root`.
- `ACTIONS = ("click","double_click","right_click","set_value","type","key","scroll","select","upload","focus","close_window")`.
- `rpa/drivers/fake.py`: `FakeDriver` built from a dict tree; records `acts`; `find` matches by the locator's fields exactly. Used by every unit test after this subtask.
**Acceptance Criteria:**
- `validate_locator({"uia": {...}, "css": "x"})` raises `RpaError`; unknown key raises; each of the 6 kinds passes.
- `FakeDriver.find` returns 0, 1 or many elements as the tree says.

**Files:**
- Create: `rpa/model.py`, `rpa/drivers/__init__.py`, `rpa/drivers/base.py`, `rpa/drivers/fake.py`
- Test: `tests/rpa/test_model.py`

#### Tests
- `tests/rpa/test_model.py` — locator validation; fake driver find counts; `Element` with `secure=True` never exposes a value.

- [ ] Step 1: write failing tests (validation cases, fake find with duplicate "OK" buttons → 2 hits).
- [ ] Step 2: run → FAIL (module missing).
- [ ] Step 3: implement.
- [ ] Step 4: run → PASS.
- [ ] Step 5: return for review.

### Subtask 3: Resolver — ✅ `5ec7ecb4`

**Goal:** Turn a locator list into exactly one element, and generate a ranked, unique locator list for a chosen element.
**Requirements:**
- `rpa/resolver.py`:
  - `resolve(driver, root, locators, *, allow_coords=False) -> Resolution(element, rung_index, locator)`; raises `Ambiguous(locator, count)` or `NotFound(locators)` (both subclass `RpaError`). Rungs 3–4 (`ocr`, `image`) are skipped in v1 with no error. `coords` is used only if `allow_coords`.
  - `generate_locators(driver, root, element) -> list[Locator]`: in ladder order, include a candidate only if `find` returns exactly that one element; for rung 2 narrow with `within: <parent path>` before giving up; always append rung-3 `{"ocr": {"text": name}}` and rung-4 `{"image": None}` placeholder (filled by the trace with the crop path); append `coords` (window-relative centre) last.
  - `is_unstable_id(value) -> bool`: true for GUIDs, hex ≥ 12 chars, or ids ending in a run of ≥ 3 digits after a separator (e.g. `item_1043`). Unstable ids are never emitted.
**Acceptance Criteria (must-fail tests from D12 live here):**
- Two identical "OK" buttons and locator `{"uia": {"role": "Button", "name": "OK"}}` → `Ambiguous`; the fake driver records no act.
- A rung-1 id that matches 0 elements falls through to rung 2; the result reports `rung_index == 1`.
- `generate_locators` for one of two "OK" buttons returns no bare role+name locator (it is not unique) but returns a `within`-scoped one if that is unique.
- A GUID automation id is never in the generated list.

**Files:**
- Create: `rpa/resolver.py`
- Test: `tests/rpa/test_resolver.py`

- [ ] Step 1: write failing tests for each criterion. Step 2: run → FAIL. Step 3: implement. Step 4: run → PASS. Step 5: return for review.

### Subtask 4: Observations and diffs — ✅ `113b6bd0`

**Goal:** Give each outline an id, keep recent outlines per root, compute a short diff after each act, and format outlines as text for the model.
**Requirements:**
- `rpa/observe.py`: `ObservationStore` (per session) with `record(outline) -> "obs_N"`, `get(obs_id)`, `latest(root_id)`; keep the last 10 per root.
- `format_outline(outline, *, max_lines=300) -> str`: one line per element `[12] Button "Export CSV" id=btnExport` (indent by depth; `[secure]` values; non-interactive elements without a name are omitted).
- `diff(before, after) -> list[str]`: windows/elements appeared or disappeared, value changes, focus change; max 15 lines.
- `rebind(store, obs_id, index, driver, root) -> Element`: if the root's latest live outline differs from `obs_id`, re-resolve the element using its generated locators (Subtask 3); `Ambiguous` / `NotFound` → raise `StaleTarget` with the reason.
**Acceptance Criteria:**
- Formatting never prints a secure value (canary test).
- An act on `obs_1` index 4 after the list reorders re-binds to the same element by locator, not by index.
- If the target was removed, `StaleTarget` is raised and the fake driver records no act.

**Files:**
- Create: `rpa/observe.py`
- Test: `tests/rpa/test_observe.py`

- [ ] Steps 1–5 as above (TDD, then return for review).

### Subtask 5: Desktop lock — ✅ `53a18d77`

**Goal:** One holder of the real mouse and keyboard at a time across all agents and processes.
**Requirements:**
- `rpa/lock.py`: `DesktopLock(path=Path.home()/".dagi"/"rpa"/"desktop.lock")` with `acquire(agent: str) -> None` (raises `DesktopBusy(holder_agent, since)`), `release(agent)`, `holder() -> dict | None`. Atomic create with `os.open(O_CREAT|O_EXCL)`; content JSON `{pid, agent, since}`.
- Dead holder: if the stored PID is not alive (`psutil.pid_exists`, from `requirements-rpa.txt`), replace the file and take the lock.
- Same agent re-acquire is a no-op. `release` by a non-holder is a no-op.
**Acceptance Criteria:**
- Agent B gets `DesktopBusy` while A holds it.
- A lock file with a dead PID is taken over.
- Releasing removes the file.

**Files:**
- Create: `rpa/lock.py`
- Test: `tests/rpa/test_lock.py` (use `tmp_path` and a PID known to be dead).

- [ ] Steps 1–5.

### Subtask 6: Safety gates — ✅ `9397fb8b`

**Goal:** Per-app permission and sensitive-action confirmation, with deny-by-default when nobody can answer.
**Requirements:**
- `rpa/safety.py`: `SafetyGate(ask: Callable[[str, list[dict]], str] | None, autonomous: bool)`.
  - `check_app(root)`: first act on a new `root.app` asks "Allow dagi to control **{app}** for this session?" with options Allow / Deny (no recommended option, no timeout). Remember per gate instance. `ask is None` or `autonomous` → deny.
  - `check_action(root, element, action, *, sensitive_flag)`: if `action in {"click","double_click","set_value","type","key","select","upload"}` and (`sensitive_flag` or `is_sensitive(element)`), ask "Confirm: {action} on {role} "{name}" in {app}?" Allow once / Deny. Not remembered.
  - `is_sensitive(element)`: lower-cased `name` contains a keyword from Global Constraints (word boundary match).
  - Raises `SafetyDenied(reason)`.
**Acceptance Criteria:**
- `autonomous=True` denies without calling `ask` (spy asserts zero calls).
- A "Send" button click asks; a "Save" button click does not.
- App permission is asked once per app per gate instance.

**Files:**
- Create: `rpa/safety.py`
- Test: `tests/rpa/test_safety.py`

- [ ] Steps 1–5.

### Subtask 7: UIA desktop driver — ✅ `1ac009aa`

**Goal:** Implement `Driver` for Windows desktop apps with `uiautomation`.
**Requirements:**
- `rpa/drivers/uia.py` `UiaDriver`:
  - `roots()`: top-level `WindowControl`s, excluding windows of the current process and of any PID in an `exclude_pids` set (the dagi GUI passes its own PID — D13).
  - `outline(root)`: if the window is minimized, restore it first (WindowPattern `SetWindowVisualState(Normal)`); walk with `auto.WalkControl(maxDepth=depth or 30)`, max 1500 nodes; map ControlTypeName → role (strip `Control`); `secure` when `IsPassword`; `interactive` for the INTERACTIVE set from S0 probes.
  - `find(root, {"uia": {...}})`: match keys `automation_id`, `role`, `name`, `name_re`, `within` (ancestor role/name list) exactly; return all matches.
  - `act`: `click` → InvokePattern / TogglePattern / SelectionItemPattern, else real click at bbox centre (requires lock); `set_value` → ValuePattern; `type` → `SendKeys` with focus (requires lock); `key` → `SendKeys`; `scroll` → ScrollPattern; `focus` → `SetFocus`; `close_window` → WindowPattern.Close.
  - `needs_desktop_lock(action)`: true for real input (`type`, `key`, coordinate clicks, `double_click`, `right_click`) and for restoring a minimized window.
  - Failsafe (D5 gate 4): before real input, if the cursor is in any screen corner (within 2 px), raise `FailsafeAbort`.
  - `launch(target)`: start the exe; if its name is in `ELECTRON_APPS = {"Code.exe", "Claude.exe", "Slack.exe", "Discord.exe", "Teams.exe"}` or the target ends in an Electron marker, add `--force-renderer-accessibility`; wait up to 20 s for a new top-level window of that PID; return its `Root`.
- Desktop fixture app `tests/rpa/fixtures/qt_fixture.py` (PySide6; `import pyside_gui` first per AGENTS.md): menu bar with File/Reports, a form (date edit, text edit, password edit), "Export CSV" button opening a QFileDialog-style child window titled "Save As", two identical "OK" buttons, a button with a per-launch random objectName, and a button that appears after 1.5 s. Plus `tests/rpa/fixtures/tk_fixture.py` (poor-a11y case: two buttons and an entry).
**Acceptance Criteria (desktop tests):**
- Outline of the Qt fixture contains "Export CSV" with role Button; the password edit shows `[secure]`.
- `find` with role+name "OK" returns 2; with the stable object name returns 1.
- The per-launch random objectName is flagged by `is_unstable_id` on two launches.
- A minimized fixture window is restored and outlined.
- `click` on "Export CSV" opens the "Save As" child; `close_window` closes it.

**Files:**
- Create: `rpa/drivers/uia.py`, `tests/rpa/fixtures/__init__.py`, `tests/rpa/fixtures/qt_fixture.py`, `tests/rpa/fixtures/tk_fixture.py`
- Test: `tests/rpa/test_uia_driver.py` (all `@pytest.mark.desktop`), plus a non-desktop unit test for the ControlType→role map and the Electron flag rule.

- [ ] Steps 1–5. Run desktop tests with `DAGI_DESKTOP_TESTS=1` unsandboxed.

### Subtask 8: Browser driver (Firefox) — ✅ `608d0029`

**Goal:** Implement `Driver` for Firefox tabs through geckodriver + Selenium.
**Requirements:**
- `rpa/drivers/outline.js` — port of the S0 script (`research.md` S0) with two fixes: file inputs are named from `aria-label` / label / `name` attr / "Browse…"; only interactive leaves get `interactive: true`. Returns `{i, role, name, id, testid, value, bbox, secure, interactive, path}`.
- `rpa/drivers/browser.py` `FirefoxDriver(profile_dir, headless=False)`: locate `firefox.exe` at `<sys.prefix>/Library/bin/firefox.exe` and `geckodriver.exe` at `<sys.prefix>/Scripts/geckodriver.exe`; clear `RpaError` with the conda install line if missing. Start lazily on first use; `-profile <profile_dir>`.
  - `roots()`: one `Root` per window handle; `app` = page origin.
  - `find`: `css`, `aria: {role, name}` (via outline match), `uia`-style `id` / `testid` keys mapped to CSS.
  - `act`: click, set_value (clear + send_keys), type, key, select (Select by visible text), upload (`send_keys(path)` on `input[type=file]`), scroll (`scrollIntoView` / `window.scrollBy`), close_window.
  - `screenshot(root, region)`: `get_screenshot_as_png` cropped.
  - `needs_desktop_lock` → always False.
  - `launch(url)`: open in a new tab of the dagi profile.
- HTML fixture `tests/rpa/fixtures/site/index.html` (copy of the S0 page) served by a `ThreadingHTTPServer` pytest fixture.
**Acceptance Criteria (desktop tests, headless allowed):**
- Outline names the file input; the password value is `[secure]`; a canary typed into it never appears in any outline.
- `find` for the two "OK" buttons returns 2.
- Upload sets `#upname` to `uploaded:<file>`.
- Restarting the driver on the same profile keeps a localStorage value.
- Missing binaries produce the clear `RpaError` (unit test with a fake prefix).

**Files:**
- Create: `rpa/drivers/outline.js`, `rpa/drivers/browser.py`, `tests/rpa/fixtures/site/index.html`
- Test: `tests/rpa/test_browser_driver.py`

- [ ] Steps 1–5.

### Subtask 9: Screen capture and set-of-marks overlay — ✅ `046fd6b8`

**Goal:** Screenshots for the model, and crops for rung 4.
**Requirements:**
- `rpa/screen.py`:
  - `capture_window(root_bbox, region=None) -> Image` via `mss` (UIA); browser screenshots come from the browser driver.
  - `mark(image, elements, *, offset=(0,0)) -> Image`: interactive leaves with area > 0 only; red 2 px box; label = index in a filled tag **inside** the box's top-left corner; if the box is smaller than the tag, put the tag outside on the left with a 1 px leader line.
  - `fit_width(image, width=1280)`; `to_png_bytes(image) -> bytes`.
  - `crop_element(image, bbox, pad=4) -> Image` for the trace.
**Acceptance Criteria:**
- Unit test on a synthetic image: tags lie inside their boxes; container elements get no tag; zero-area elements get no tag.
- `fit_width` never upscales.

**Files:**
- Create: `rpa/screen.py`
- Test: `tests/rpa/test_screen.py`

- [ ] Steps 1–5.

### Subtask 10: `computer_use` config flag and the four `ui_*` tools

**Goal:** Expose computer use to the agent behind the global flag.
**Requirements:**
- `agent/_loop_config.py`: `computer_use: bool = False`. `agent/config_loader.py`: `computer_use = bool(raw.get("computer_use", False))` (global only, like `code_mode`).
- `tools/ui/_session.py` `UiSession`: one per registry; holds `UiaDriver(exclude_pids={os.getpid()})`, a lazily created `FirefoxDriver(profile_dir=<DAGI_ROOT>/.dagi/rpa/firefox-profile)`, `ObservationStore`, `DesktopLock`, `SafetyGate(ask=callbacks.on_ask_user wrapper with timeout=None, autonomous=config.autonomous)`, `agent_name` (config display name + short owner id), and an optional `recorder` hook (filled in Subtask 13).
- Tools (each `BaseTool`, descriptions state the rules from D3):
  - `ui_roots(launch: str | None)` → text list `root_id | kind | app | title`.
  - `ui_observe(root, mode="outline"|"screenshot"|"both", query=None, depth=None, region=None)` → outline text + `obs_N`; when `mode` includes a screenshot, or the outline has fewer than 5 interactive elements, return `ToolResult(side_effect=SideEffect.ATTACH_IMAGE, side_effect_data={"image": ImageAttachment(...), "path": f"ui_observe {obs_id}"})` with the marked, 1280-px-fitted PNG. `region` = element index to zoom on (crop its bbox + 40 px) or `[x,y,w,h]`.
  - `ui_act(root, target, action, value=None, obs, sensitive=False, allow_coords=False)` → order: validate obs → rebind target → safety `check_app` → `check_action` → lock if needed → act → new outline → diff → `"ok: <action> [i] Role \"name\"\n<diff>\nobs_M"`. Errors return `Error (...)` strings (Ambiguous, StaleTarget, SafetyDenied, DesktopBusy, FailsafeAbort).
  - `ui_wait(root, condition, timeout=10)` — conditions `present` / `gone` (locator), `text` (substring in outline), `window` (title regex), `file_exists` (path).
- Release the desktop lock at end of turn: register a hook from `AgentLoop` turn end → `UiSession.end_turn()` (call it from the turn-close path, `TurnBoundaries.close_turn` in `agent/_turns.py:53`, through `registry._tools.get("ui_act")` the same way `interrupt()` reaches `bash`; document the hook). Also release in `interrupt()` (same pattern as `bash.force_kill()`).
- Register in `agent/tools.py` after the file tools phase only when `config.computer_use` is true; update `tests/test_tool_registry_contract.py` ordered lists for the `computer_use=True` case (default lists unchanged).
**Acceptance Criteria:**
- With `computer_use=False` the registry has no `ui_*` tool (contract test unchanged).
- With `True`, the four tools appear in the documented position.
- `ui_act` with a stale index re-binds or returns the StaleTarget error; it never acts on the wrong element (fake driver).
- `ui_act` in an `autonomous` config returns a SafetyDenied error and the fake driver records no act.
- `ui_observe(mode="screenshot")` returns `ATTACH_IMAGE` with a PNG ≤ 1280 px wide.
- `interrupt()` releases the desktop lock.

**Files:**
- Create: `tools/ui/__init__.py`, `tools/ui/_session.py`, `tools/ui/_tools.py`
- Modify: `agent/_loop_config.py:95-104`, `agent/config_loader.py:300-370`, `agent/tools.py:140-160,326-366`, `agent/loop.py` (interrupt + turn end), `tests/test_tool_registry_contract.py`, `tests/test_config_loader.py`
- Test: `tests/test_ui_tools.py` (fake drivers injected into `UiSession`)

- [ ] Steps 1–5.

### Subtask 11: Screenshot retention at request build — ✅ `9fe1baa0`

**Goal:** Only the last 3 UI screenshots reach the model.
**Requirements:**
- In `agent/loop.py` near line 676 (the `materialize_messages` call), before materializing, replace `dagi_image` parts whose preceding text part starts with `[Image from read: ui_observe` with a text part `[screenshot obs_N elided]`, except the newest 3. Images from the normal `read` tool are not touched. The event log and history are not changed.
- Put the pure function in `agent/image_assets.py` as `elide_old_ui_screenshots(messages, keep=3) -> list[dict]`.
**Acceptance Criteria:**
- 5 UI screenshots in history → request has 3 images and 2 elided markers; the log still holds 5.
- A non-UI image older than the UI ones stays.

**Files:**
- Modify: `agent/image_assets.py`, `agent/loop.py:~670-676`
- Test: `tests/test_image_assets.py` (add cases)

- [ ] Steps 1–5.

**S1 checkpoint (manual, Admiral watching):** with `computer_use: true`, ask dagi in the GUI to open Notepad, type a line, and open the Save As dialog; then to open the HTML fixture in Firefox and fill the form. Confirm the per-app prompts, the sensitive prompt on a "Send"-like button, and ESC stopping input.

---

## Stage S2 — Record, compile, run

### Subtask 12: Workflow format, templating, approval store

**Goal:** Load, validate and hash `workflow.yaml` (D1 format).
**Requirements:**
- `rpa/workflow.py`:
  - `Workflow` / `Step` dataclasses for the D1 keys: `name, description, params, secrets, steps[id, root, act|launch, target.locators, value, expect, confirm, sensitive, allow_coords, retry, on_fail, for_each, if_present]`. Unknown keys → `RpaError` with the key path. `code:` steps → `RpaError("code steps are not supported in v1")` (see Open Issues).
  - Minimal templater `render(text, ctx)`: `{{ name }}`, built-ins `today`, `yesterday`, filter `| date('%Y-%m-%d')`; unknown name → `RpaError`. No Jinja2 (not in `requirements-core.txt`).
  - Secrets: `{env: NAME}` resolved at run time only; values never stored or logged.
  - `step_hash(step) -> str` = sha256 of the canonical JSON of the step (sorted keys).
  - `rpa/store.py`: workflow folder `.dagi/rpa/<name>/` (`workflow.yaml`, `crops/`, `runs/`, `trace.jsonl`, `state.json`). `state.json` = `{status, approved_hash_by_step, verified_at, last_run}`. Status values: `draft`, `approved`, `degraded`, `halted`. `approve(name)` records the hashes of all `confirm` steps; editing `workflow.yaml` afterwards makes the changed step's hash mismatch.
**Acceptance Criteria:**
- The D1 example workflow (from `research.md` / chat) loads (minus its `code:` example).
- A typo key fails with its path.
- Changing one confirm step's `value` makes `confirm_ok(name, step)` false for that step only.

**Files:**
- Create: `rpa/workflow.py`, `rpa/store.py`
- Test: `tests/rpa/test_workflow.py`, `tests/rpa/fixtures/sales_export.yaml`

- [ ] Steps 1–5.

### Subtask 13: Trace recorder and `rpa_record` / `rpa_save`

**Goal:** Record successful acts during an explicit recording session.
**Requirements:**
- `rpa/trace.py` `Recorder(store_dir)`: `start(name, goal)`, `add(root, element, action, value, before_outline, after_outline, crop_png)`, `stop()`. Each JSONL entry: root descriptor (kind, app, title regex built from the title with digits/dates generalised), action, value (secure → `{"secret": true}`), `locators` from `generate_locators` (rung-4 placeholder replaced by `crops/<n>.png`), `expect` candidates from the diff (window appeared / element present / value equals), and the `before` element summary (for repair).
- `UiSession.recorder` is set while recording; `ui_act` calls `recorder.add` only after success.
- Tools `rpa_record(name, goal)` and `rpa_save()` in `tools/rpa/`. `rpa_save` runs the compiler (Subtask 14) and returns the draft YAML path and text.
**Acceptance Criteria:**
- A failed or refused `ui_act` adds nothing.
- A typed password is stored as `{"secret": true}`; a canary never appears in `trace.jsonl`.
- Two recordings with the same name are refused unless the old one is removed.

**Files:**
- Create: `rpa/trace.py`, `tools/rpa/__init__.py`, `tools/rpa/_record.py`
- Modify: `tools/ui/_tools.py`, `agent/tools.py`, `tests/test_tool_registry_contract.py`
- Test: `tests/rpa/test_trace.py`, `tests/test_rpa_tools.py`

- [ ] Steps 1–5.

### Subtask 14: Compiler and restricted cleanup

**Goal:** Trace → draft `workflow.yaml`, deterministically; the model may only delete, rename, parameterize and flag.
**Requirements:**
- `rpa/compiler.py`:
  - `compile_trace(entries, name, goal) -> Workflow`: one step per entry; ids `step_01…`; first `expect` candidate in the order window → present → value_equals; a `launch` step if the first root was launched in the session; adjacent duplicate `focus` acts collapsed.
  - `apply_cleanup(workflow, ops) -> Workflow` with ops `{"op":"delete","step":id}`, `{"op":"rename","step":id,"to":new_id}`, `{"op":"param","step":id,"field":"value","name":p,"default":literal}`, `{"op":"flag","step":id,"confirm":"once"|"every_run"|None,"sensitive":bool,"expect_file":path}`. Any other op, or any op that adds/changes `locators`, → `RpaError`.
  - Steps whose element matched a sensitive keyword get `confirm: once` by default.
- `rpa_save(cleanup: list[op] = [])` applies ops after compiling and writes the draft with status `draft`.
**Acceptance Criteria:**
- Same trace → byte-identical YAML twice.
- An op trying to set `locators` is rejected.
- A step on a "Send" button compiles with `confirm: once`.

**Files:**
- Create: `rpa/compiler.py`
- Modify: `tools/rpa/_record.py`
- Test: `tests/rpa/test_compiler.py`

- [ ] Steps 1–5.

### Subtask 15: Interpreter

**Goal:** Run a workflow step by step with no model calls.
**Requirements:**
- `rpa/interpreter.py` `run_workflow(workflow, *, drivers, params, confirm: Callable[[Step], bool] | None, start_at=None, run_dir) -> RunResult(status: "ok"|"degraded"|"halted", halted_step, reason, steps: list[StepLog])`.
- Per step: render templates → find root (title regex / url regex; wait up to 10 s) → pre-check (root present; for `start_at`, the step's own pre-check must pass or HALT) → `resolve` → confirm gate (`confirm: once` requires `store.confirm_ok`; `every_run` calls `confirm`; no callback → HALT `needs approval`) → lock if needed → act → `expect` with timeout (default 10 s) → log `{step, rung, ms}`.
- HALT writes `runs/<ts>/`: `run.json`, the failing root's outline (`outline.txt`, secure-safe) and a screenshot `halt.png`.
- `retry: n` retries resolve+act n times with 1 s backoff; `on_fail: continue` logs and continues; `if_present: <locator>` skips the step when absent; `for_each: "{{ list_param }}"` runs the step per item with `{{ item }}`.
- Status update in `state.json`: any rung > 0 (rung 1 is index 0) → `degraded`; HALT → `halted`; else keep `approved`/`draft`.
**Acceptance Criteria (fake drivers):**
- Ambiguous target → HALT; zero acts after the ambiguous step.
- A changed unapproved `confirm: once` step → HALT `needs approval`; no act on it (D12 must-fail).
- Rung-2 match → `degraded`.
- A secret canary never appears in `run.json` or `outline.txt`.
- `start_at` with a failing pre-check halts before any act.

**Files:**
- Create: `rpa/interpreter.py`
- Test: `tests/rpa/test_interpreter.py`

- [ ] Steps 1–5.

### Subtask 16: CLI, `rpa_run`, verify and approve

**Goal:** Run from the shell and from chat; move workflows through draft → verify → approved.
**Requirements:**
- `rpa/__main__.py` (argparse): `run <name> [--param k=v]... [--from-step id] [--verify]`, `approve <name>`, `list`, `show <name>`. Exit codes: 0 ok, 1 degraded, 2 halted, 3 usage/config error. `every_run` confirm on a TTY uses `input()`; without a TTY it halts. `approve` asks on the TTY and requires a prior successful `--verify` run with no degraded steps.
- `tools/rpa/_run.py`: `rpa_run(name, params={}, from_step=None, verify=False)` calls `run_workflow` with `confirm` bound to the session's `ask_user` (no timeout; autonomous → deny). It warns when the workflow is not `approved`. On HALT the result text ends with: "Step `<id>` halted: <reason>. Evidence: <run_dir>. Offer the Admiral a repair (rpa_repair) — do not start it unasked."
- `rpa_approve(name)`: asks the Admiral (Approve / Reject, no timeout); records hashes only on an explicit Approve; autonomous → refuse.
**Acceptance Criteria:**
- CLI exit codes match for ok / degraded / halted (fake drivers via an env hook or dependency injection in `main(argv, drivers=None)`).
- `approve` before a clean verify run is refused.
- `rpa_approve` in autonomous mode records nothing.

**Files:**
- Create: `rpa/__main__.py`, `tools/rpa/_run.py`
- Modify: `agent/tools.py`, `tests/test_tool_registry_contract.py`
- Test: `tests/rpa/test_cli.py`, `tests/test_rpa_tools.py`

- [ ] Steps 1–5.

**S2 checkpoint (manual):** record "export the fixture form to CSV" on the Qt fixture + HTML fixture, save, review YAML, `python -m rpa run <name> --verify`, approve, run again; then rename a button in the fixture and confirm the run halts with evidence.

---

## Stage S3 — Repair

### Subtask 17: Repair context, patch tool, `operator` subagent

**Goal:** Fix a halted workflow with a small, reviewed YAML patch.
**Requirements:**
- `rpa/repair.py`: `repair_context(name) -> dict` = the halted step (YAML), its recorded `before` summary from `trace.jsonl`, the halt reason, paths to `outline.txt` / `halt.png`; `apply_patch(name, ops) -> (diff_text, changed_confirm_steps)` with ops `replace_step` (new locators allowed only if each came from a live `generate_locators` call in this session — the tool passes them in, see below), `insert_step_after`, `delete_step`. Writes the new YAML only after approval.
- Tools in `tools/rpa/_repair.py`:
  - `rpa_repair(name)` → returns `repair_context` text + instructions to explore with `ui_*` and then call `rpa_patch`.
  - `rpa_patch(name, ops)`: each new target is given as `{root, obs, index}`; the tool resolves it and calls `generate_locators` itself, so the model cannot invent locators. It shows the unified diff via `ask_user` (Approve and re-run / Reject, no timeout). On Approve: write YAML; if any confirm step changed, ask a second, explicit confirmation and clear its approved hash; then run from step 1 (or `from_step` when its pre-check passes) via `rpa_run`.
- `.dagi/subagents/operator/` (`subagent_config.yaml`: `model_tier: default`, tools `ui_roots, ui_observe, ui_act, ui_wait, rpa_repair, rpa_patch, read`; `prompt.md`: repair-only instructions, never approve, never edit YAML by file tools). Discovery follows `agent/subagent_tools.py` rules.
**Acceptance Criteria:**
- A patch that changes a confirm step clears its hash and needs a second confirmation (fake ask).
- `rpa_patch` with a locator literal (not `{root, obs, index}`) is rejected.
- Reject leaves `workflow.yaml` byte-identical.

**Files:**
- Create: `rpa/repair.py`, `tools/rpa/_repair.py`, `.dagi/subagents/operator/subagent_config.yaml`, `.dagi/subagents/operator/prompt.md`
- Modify: `agent/tools.py`, `tests/test_tool_registry_contract.py`
- Test: `tests/rpa/test_repair.py`, `tests/test_rpa_tools.py`

- [ ] Steps 1–5.

---

## Stage S4 — GUI

### Subtask 18: Workflows rail view

**Goal:** List workflows and show the detail view from D15.
**Requirements:**
- `rpa/api.py` (no Qt): `list_workflows(project) -> list[Summary]`, `workflow_detail(name) -> Detail` (steps with last matched rung and confirm mode, params, secret names, status, last run).
- `pyside_gui/sidebars/workflows_view.py`: list with status chips; detail with lifecycle stepper; primary action follows status (Verify run → Approve → Run). Actions call the same functions as the CLI in a worker thread and post results to the conversation as text.
- Add a rail icon in `pyside_gui/left_sidebar.py` (after Agents). Hidden when `computer_use` is false.
**Acceptance Criteria:**
- Qt test (unsandboxed): the view lists two fixture workflows with the right chips; the primary button label follows status.
- With `computer_use: false` the rail icon is absent.

**Files:**
- Create: `rpa/api.py`, `pyside_gui/sidebars/workflows_view.py`
- Modify: `pyside_gui/left_sidebar.py:53-150`, `pyside_gui/icons.py`
- Test: `tests/rpa/test_api.py`, `pyside_gui/tests/test_workflows_view.py`

- [ ] Steps 1–5.

### Subtask 19: Halt and patch cards in the conversation

**Goal:** Show a halt card (Screenshot / Repair / Dismiss) and a patch card (diff, Approve and re-run / Edit YAML / Reject).
**Requirements:**
- First inspect `pyside_gui/conversation.py` and `pyside_gui/paste_cards.py` for an existing card widget pattern; reuse it. If no card pattern exists, render the halt card as a markdown block with links handled by the conversation's link handler, and the patch card through the existing `ask_user` dialog (its options become the buttons). Record the choice in Notes.
- Repair button → sends "Repair <name>" as a user message (it starts nothing by itself).
**Acceptance Criteria:**
- Qt test: a halt result renders the card with the three actions; Repair queues the user message; Reject in the patch card leaves the YAML unchanged.

**Files:**
- Modify: `pyside_gui/conversation.py` (or the card module found), `pyside_gui/bridge.py`
- Test: `pyside_gui/tests/test_rpa_cards.py`

- [ ] Steps 1–5.

---

### Subtask 20: Documentation

**Goal:** Users can install, enable and use the feature.
**Requirements:**
- `README.md`: "Computer use and RPA" section (install line, `computer_use: true`, Firefox profile login once, recording → verify → approve → run, CLI commands, safety gates, limitations: no scheduler, no image/OCR matching, no `code:` steps).
- `AGENTS.md`: commands for desktop tests (`DAGI_DESKTOP_TESTS=1`, unsandboxed).
- `wiki/`: entries for the Electron accessibility flag, minimized-window gotcha, Firefox computed-role gap (via `wiki-add`).
**Acceptance Criteria:** README commands run as written on this machine.

**Files:** Modify `README.md`, `AGENTS.md`; create wiki entries.

---

## Workspace
- **Branch:** `task/rpa-computer-use`
- **Parent:** `main`
- **Starting commit:** `b71bbb8b`
- **Task folder:** `wiki/tasks/2026-10-10_rpa-computer-use/`

## Overall Status
In Progress — Subtask 10

## Notes
- R20 prerequisite merged to `main` (`467ad01b`) and into this branch (`b71bbb8b`).
- `deepseek-flash` now has `supports_images: true` (`3079386f`); S0 vision check: the model must pick from the text outline; screenshots are context only.
- S0 data: UIA walk ≈ 0.7–1.3 ms/node; Calculator ids stable across relaunch; Save dialog ids `1001`/`1`; Electron needs `--force-renderer-accessibility` and then has ~no ids; minimized windows expose ~nothing.
- `ask_user` default handler (`agent/tools.py:_default_ask_user`) returns the recommended option: safety prompts must offer **no** recommended option and treat timeouts / `autonomous` as deny.
- `scheduler/runner.py` auto-answers `ask_user` — never run `ui_*` tools there (D6).
- Subtask 2: `Element.bbox` = (left, top, right, bottom), relative to the root window / browser viewport; every driver converts to this frame. `tests/__init__.py` added so `tests/rpa/` does not shadow the real `rpa` package. FakeDriver API: `FakeDriver(roots, trees, sizes=..., lock_actions=...)`; tree nodes are dicts with `role, name, automation_id, value, secure, css, bbox, children`.
- Subtask 3: browser drivers store `Element.automation_id` as a ready CSS token (`#id`, else `[data-testid="x"]`); the resolver emits `{"css": token}` and checks stability on the raw value inside. `ocr` is omitted for unnamed elements. Review fix: `0x`-prefixed hex ids are unstable.
- Subtask 5: in-process `threading.Lock` serializes agent threads; an unreadable lock file younger than 2 s is treated as mid-write (busy), not corrupt. Residual: two *processes* taking over the same dead holder at the same instant can both succeed (rare; GUI agents share one process).
- Subtask 6: keyword gate cannot see that Enter in a message field sends; the per-app permission is the real boundary (D5).
- Subtask 4: `rebind` trusts the observed index only when the element key is unique in both outlines or the outline is unchanged (review fix: duplicate "OK" buttons shifted silently); otherwise it re-resolves and refuses on ambiguity. No focus tracking in the model, so diffs omit focus changes. `resolver.css_token_value` is public.
- Subtask 8: `outline.js` tags nodes with `data-dagi-i`; `act()` re-outlines and raises `drivers.base.WrongElement` unless the live node's role/name/automation_id equal the given Element (review fix). No iframe/shadow DOM traversal; `aria-hidden` not checked; `depth` ignored (v1).
- Subtask 7: every real mouse/keyboard event goes through `_before_real_input` (failsafe corner, `SetActive`, foreground must be root or a window it owns, else `WrongElement`); `key` focuses the control first; `click` always needs the desktop lock (pattern-less fallback); new protocol method `needs_desktop_lock_to_observe(root)` (UIA: True when minimized) — Subtask 10 must take the lock before observing such a root. Qt AutomationIds are dotted paths (`...QWidget.btnExport`); a Qt modal dialog is nested in the parent's UIA tree, so `close_window` closes the nearest window ancestor. Process is made per-monitor DPI aware (best effort). `act`/`find` re-walk the whole tree (≈1–2 s worst case). `tk_fixture.py` has no test yet (poor-a11y case).
- Subtask 11: `elide_old_ui_screenshots` runs in `_build_request_messages`; UI screenshots are recognised by the preceding text `[Image from read: ui_observe obs_N]`, so Subtask 10 must pass `path=f"ui_observe {obs_id}"`. Cost: each new screenshot elides an older one, which changes an earlier message and breaks the prompt-cache prefix from there (accepted by D4).

## Open Issues
- `code:` escape-hatch steps (D1) need dagi's tool registry, which conflicts with "rpa/ must not import agent" for CLI runs. v1 rejects them with a clear error. Decide later: run them only from `rpa_run` (in-agent), or drop.
- Halt notifications outside chat are deferred with the scheduler (D6).

## Attempts and Resolutions
_(none yet)_

## Verification
1. `C:\Users\alexr\miniconda3\envs\dagi\python.exe -u -m pytest -q -p no:pytest-qt tests` → all pass except the known `tests/test_workflow_plan_template.py` failures (R15).
2. Unsandboxed: `set DAGI_DESKTOP_TESTS=1` then the same command plus `pyside_gui/tests/test_workflows_view.py pyside_gui/tests/test_rpa_cards.py` → all desktop tests pass.
3. Manual S1, S2 checkpoints above, then: record a workflow that crosses Qt fixture → Firefox fixture page, verify, approve, run (exit 0); break a locator → exit 2 with `runs/<ts>/`; repair via chat → approve patch → run exit 0.
4. Must-fail checks (D12) all present: ambiguous halt (`test_resolver`, `test_interpreter`), stale observation (`test_observe`, `test_ui_tools`), unapproved changed confirm (`test_interpreter`, `test_repair`), secret canary (`test_observe`, `test_trace`, `test_interpreter`, `test_browser_driver`), import isolation (`test_isolation`).

## Next Action
Admiral reviews and approves this plan; then `deliver` starts with Subtask 1.
