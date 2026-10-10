# Research — RPA + computer use for dagi

| Field | Value |
|---|---|
| Status | Research and discussion (no implementation) |
| Branch | `task/rpa-computer-use` from `main@eb677f39` |
| Started | 2026-10-10 |

## Goal (from the Admiral)

- Targets: **desktop apps and the browser**.
- Model: assume `default_model` is a multimodal LLM.
- Flow: dagi **explores a task interactively**, then **builds a script** that runs on a schedule.

## What dagi already has

| Piece | Where | Relevance |
|---|---|---|
| Image tool results | `SideEffect.ATTACH_IMAGE` → `_attach_image` in `agent/_tool_dispatch.py` | A screenshot tool reuses it; the image rides in a follow-up user message (tool messages are text-only). |
| Multimodal gate | `supports_images` in model config; `current_supports_images` | Must be `true` on the default model. No current model config sets it. |
| Image store | `agent/image_assets.py` (`ImageAssetStore`, `dagi_image` parts) | Content-addressed under `.dagi/attachments/`; images stay in history until compaction. |
| Image token estimate | `tools/compact/_tail_boundary.py` (`_ESTIMATED_TOKENS_PER_IMAGE`) | Many screenshots fill context fast. |
| Subagents | `.dagi/subagents/<name>/` (`subagent_config.yaml`, `prompt.md`) | Host for an isolated `operator` agent. |
| Code mode | `tools/code/` (`code` tool, `tools.<name>(**args)` proxied to the parent registry) | A replay script could be a code-mode program over the same UI tools. |
| Scheduler | `scheduler/` (`ScheduledTask`: `prompt`, `interval`, `model`) | Runs **agent prompts** only; no "run a script" task type yet. |
| Confirmation | `ask_user`, `SOLO_TOOLS` | Gate for sensitive UI actions. |
| Known hazard | R20: `AgentLoop.interrupt` kills the process-global subagent set | Unsafe once a subagent drives real apps. |

## Reference projects

| Project | Perception | OS | Record/replay | Idea to borrow |
|---|---|---|---|---|
| [dsh-computer-use](https://github.com/anionex/dsh-computer-use) | AX tree first, optional screenshot | macOS | none | Fail-closed resolver (re-resolve on fresh state; refuse ambiguous); one-use confirm tokens; process-targeted input, no global cursor; `[secure]` redaction |
| [pi-computer-use](https://github.com/injaneity/pi-computer-use) | Progressive a11y outline; desktop + CDP pages as **one forest** | macOS/Win/Linux | none | Coarse tools (`find_roots`, `observe_ui`, `search_ui`, `act_ui`, `wait_for`); raw `screenshot`/`click` deprecated |
| [OculiX](https://github.com/oculix-org/Oculix) (SikuliX successor) | OpenCV template match + Tesseract/PaddleOCR | Win/macOS/Linux | is a script runtime (Jython) | Image match as last-resort locator |

## Record/replay library survey

| Library | Records | Output | Surface | Notes |
|---|---|---|---|---|
| [muscle-mem](https://github.com/pig-dot-dev/muscle-mem) | Agent tool calls | Cached trajectory; replay on precheck hit, agent on miss | Any tools | Python, Apache-2.0, v0 API, last activity ~Jun 2025. Borrow `Check(capture, compare)` pre/post. |
| [openadapt-flow](https://pypi.org/project/openadapt-flow/) | Human demos only | Bundle (`workflow.json` + crops), zero model calls on healthy path | Desktop + browser | MIT, v1.35.1 (Sep 2026), Py 3.10–3.12. Ladder: structural → OCR → pixel; halts instead of guessing. |
| [workflow-use](https://github.com/browser-use/workflow-use) | Human ext. or agent from prompt | `.workflow.json`, agent fallback | Browser | AGPL-3.0, "not production". |
| [Stagehand](https://docs.stagehand.dev/v4/best-practices/caching) | Agent act/observe | Cached actions, `selfHeal` | Browser | TypeScript-first. |
| [pywinauto_recorder](https://github.com/beuaaa/pywinauto_recorder) | Human, Windows | Python script, UIA paths | Desktop | MIT. |
| Playwright codegen | Human | Playwright script | Browser | — |

**Finding:** nothing takes an *agent's* exploration across desktop + browser and emits a script.
Recorders that capture OS input events (openadapt, pywinauto_recorder) cannot see dagi acting through
UIA `Invoke` or CDP. dagi must own the trace format and the compiler.

## Working hypothesis (to be challenged in discussion)

explore (operator subagent, UI tools) → trace JSONL (action + ranked locators + pre/post checks)
→ compile to script → scheduler runs script with no model calls → on halt, operator repairs the
failing step, Admiral approves.

## Open questions (discussion log below)

1. Replay artifact: standalone Python (pywinauto/Playwright) vs code-mode program over dagi's UI tools vs data-only trace + interpreter.
2. Locator ladder order and what is recorded per step.
3. Agent-facing tool surface (coarse pi-style vs fine).
4. Operator subagent vs main loop; screenshot retention.
5. Safety: which actions need confirmation; unattended runs.
6. Where scheduled runs execute (unlocked desktop vs VM); scheduler task type.
7. Repair loop and approval channel.
8. Prerequisites (R20).

## Discussion log

_(decisions recorded here as they are made)_

### D1 — Replay artifact: declarative workflow + dagi interpreter (option C) — 2026-10-10

- Saved script = `.dagi/rpa/<name>/workflow.yaml` (+ `crops/`, `runs/`, `trace.jsonl`).
- Each step: `root` (window or browser tab), `act`, `target.locators` (ranked list), `value`,
  `expect` (post-check with timeout), optional `confirm`, `on_fail`, `retry`.
- `params` (templated, e.g. `{{ yesterday }}`), `secrets` (from env/vault, never stored),
  `for_each`, `if_present`, and a `code:` escape hatch run through code mode.
- Interpreter per step: pre-check → resolve (first unique match; ambiguous or none → HALT) →
  confirm gate → act → `expect` → log matched rung. Lower-rung match = run OK but step *degraded*.
- Halt → `runs/<ts>/` evidence → notify → operator proposes a step-level YAML patch → Admiral approves.
- One resolver + drivers shared by live agent tools and replay; only the interpreter is C-specific.
- Rejected: A (standalone Python — resolver/checks duplicated per script, repairs edit code);
  B (code-mode program — same repair problem, needs live registry).

### D2 — Locator ladder and v1 driver scope — 2026-10-10

- Ladder (first unique match wins; >1 match → HALT ambiguous):
  1. UIA `automation_id` / DOM `data-testid`·`id` — dropped at record time if unstable
     (regenerated per launch: GUID/counter patterns or relaunch check).
  2. UIA `role + name` under parent path / ARIA `role + name`.
  3. OCR text near an anchor / visible text.
  4. Image crop (template match).
  5. Window-relative `coords`, marked `fragile`; opt-in per step (`allow_coords: true`).
- v1 replay resolves rungs 1–2 (+5 when opted in). Rungs 3–4 are **recorded** in v1
  (crop + OCR text per step) and **resolved** from v2, so v1 workflows upgrade without re-recording.
- Screenshots for the model (mss + set-of-marks from UIA/CDP bboxes) ship in v1.
- Assumption: no known canvas-heavy or Citrix/RDP target apps; if one appears, image/OCR moves to v1.

### D3 — Agent tool surface: four coarse tools — 2026-10-10

- `ui_roots(launch?)` — windows + browser tabs as roots.
- `ui_observe(root, mode=outline|screenshot|both, query?, depth?)` — numbered outline, optional
  set-of-marks screenshot with the same numbers; returns an observation id.
- `ui_act(root, target, action, value?, obs)` — target = index from obs | locator | coords (opt-in);
  actions mirror workflow `act:`; returns result + diff + new obs id.
- `ui_wait(root, condition, timeout)` — present/gone/text/window/file_exists.
- Rules: act is bound to an observation and re-resolved if the UI changed (ambiguous → refuse);
  every successful act is auto-appended to the trace; observe is text-first, screenshot on request
  or when the outline is near-empty.
- Rejected: fine-grained click/type/screenshot tools (coordinate guessing, big schema); single
  `ui(action=…)` tool (argument union confuses the model).

### D4 — Where exploration runs; screenshot retention; desktop lock — 2026-10-10

- `ui_*` are ordinary registry tools enabled by config (e.g. `computer_use: true`), usable in the
  main loop, a spawned GUI agent, or a subagent.
- Interactive exploration: whichever session the Admiral is talking to (main loop, or a spawned
  GUI agent to keep the main chat clean).
- `operator` typed subagent: unattended repair of halted runs and delegated UI subtasks.
- Screenshot retention: keep the last 3 screenshots in the request; older ones become
  `[screenshot obs_N elided]` at request-build time (`materialize_messages`); event log untouched.
- Desktop lock: process-wide; first `ui_act` that needs real input takes it; others get
  `desktop is held by @agent`; released on end of turn, idle timeout or interrupt.
  CDP-only browser actions do not take it.

### D5 — Safety gates — 2026-10-10

Live exploration:
1. Per-app/origin permission: first `ui_act` on a new exe or browser origin → `ask_user`; granted
   for the session. Primary boundary.
2. Sensitive-action confirm: keyword check on target name/role (send, submit, delete, pay,
   purchase, transfer, post, confirm, sign out, …) or model flag `sensitive: true` → `ask_user`.
3. Secrets never transit the model: password fields render `[secure]` in outlines/traces;
   credentials only via `secrets: {env: …}` refs resolved by the driver.
4. Kill switch: GUI ESC + global failsafe (mouse to screen corner) aborts real input.

Unattended replay (R3): per-step `confirm: once` (pre-approved with the workflow; default) or
`confirm: every_run` (ping Telegram/board, wait, halt on timeout; for send/pay/post/external).
Each approved confirm step stores a content hash; a repair patch that changes it requires
re-approval.

### D6 — Scheduler: out of scope for this task — 2026-10-10

- `scheduler/` is not touched. Future integration: the scheduler **only replays recorded
  workflows** (no agent, no model). The interpreter's confirm gate is its own code, never an
  agent `ask_user` callback.
- Facts recorded for the future task:
  - `scheduler/runner.py` `_on_ask_user` auto-answers "Proceed with your best judgment" —
    must never gate UI actions; an agent prompt with `ui_*` tools must not run unattended.
  - Schedules are end-to-start intervals only; RPA wants wall-clock (`at`/cron).
  - Windows Task Scheduler "run whether logged on or not" = session 0, no desktop → UIA empty.
    Desktop workflows need an interactive, unlocked session (or a dedicated auto-login VM).

### D7 — v1 run and repair — 2026-10-10

- Run entry points: CLI `python -m rpa run <name> [--param k=v]` (the future scheduler calls
  exactly this) and agent tool `rpa_run(name, params)`. No slash command in v1. Same interpreter,
  same `runs/<ts>/` evidence; a run makes no model calls.
- Repair (P2): when `rpa_run` halts in chat, the agent offers repair; never automatic.
  Operator gets halted step + recorded "before" state + live screen → explores with `ui_*` →
  proposes a YAML patch → Admiral approves (D5 hash rule) → re-run from start by default;
  "resume from step N" allowed only if that step's pre-check passes live.

### D8 — Recording and compiling — 2026-10-10

- Explicit recording sessions: `rpa_record(name, goal)` … `rpa_save()`; the agent may start one
  itself when asked to "learn" a task. Only successful `ui_act`s inside the session are traced.
- Compile is deterministic (trace → steps: locators, `expect` from the act diff, root, act, value,
  crops). Model cleanup may only delete, rename, parameterize, and flag (`confirm`, `file_exists`)
  — never invent locators.

### D9 — Browser: stock Firefox via geckodriver + Selenium (F3) — 2026-10-10

- conda-forge `firefox` (157.0.1) + `geckodriver` (0.37.1), both win-64, pinned in the `dagi` env;
  Selenium (classic WebDriver + BiDi events) from pip.
- Dedicated persistent profile `.dagi/rpa/firefox-profile/`; Admiral logs into sites once by hand
  (dagi never handles those passwords; personal sessions stay out of reach).
- dagi writes its own page outline (injected JS: DOM walk with computed ARIA role/name, bboxes,
  indices) and explicit waits. Upload via `send_keys(path)` on `input[type=file]` (no native dialog).
- The "CDP driver" of D2/D3 becomes a protocol-neutral **browser driver** interface; locators
  (`css`, `aria: {role, name}`) are protocol-independent.
- Facts: Firefox removed CDP in 141 (WebDriver BiDi only); Playwright's default Firefox is a
  patched build; Playwright `channel="moz-firefox"` (stock, BiDi) is experimental with driver-crash
  bugs (#42669, #43044). Revisit F2 when it stabilizes. Chrome 136+ blocks remote debugging on the
  default profile (moot with Firefox).
- Rejected: F1 Playwright patched Firefox (not stock, not conda); F2 moz-firefox (experimental);
  Chrome options B1–B3.

### D10 — R20 is a separate prerequisite task — 2026-10-10

- Fix R20 (`AgentLoop.interrupt` → `force_kill_active_subagents` kills every agent's children)
  in its own task/branch **before this task's implementation starts**; planning continues meanwhile.
- Desktop lock gets dead-holder detection regardless: lock file `{pid, agent, since}`; a claimant
  takes over when the holding PID is gone (covers crashes, timeouts, Task Manager kills).

### D11 — Code layout, dependencies, staging — 2026-10-11

- New package `rpa/` (drivers/{base,uia,browser,screen}, resolver, observe, trace, compiler,
  workflow, interpreter, lock, `__main__`). **`rpa/` must not import `agent/`** (import test) so
  `python -m rpa run` works without an agent.
- Thin wrappers: `tools/ui/` (ui_roots/observe/act/wait), `tools/rpa/` (rpa_record/save/run);
  `.dagi/subagents/operator/`.
- `requirements-rpa.txt` (pip: selenium, uiautomation|pywinauto, mss, opencv-python-headless);
  conda: firefox, geckodriver.
- Global config `computer_use: false` (off by default).
- Stages: S0 spikes (UIA coverage on real apps; geckodriver + conda Firefox + persistent profile;
  set-of-marks token cost) → S1 live computer use → S2 record/compile/run → S3 repair.
  Later: image/OCR matching, scheduler, VM host, Playwright BiDi.
- Open: which 2–3 real desktop apps S0 spikes against.

### D12 — Testing — 2026-10-11

- Unit (anywhere): schema/params/confirm-hash, locator ranking + ambiguity, compiler, lock
  takeover — against fake drivers.
- Fixture integration (`@pytest.mark.desktop`, unsandboxed, skipped by default): Qt fixture app
  (menus, form, Save dialog, dynamic-id button, two identical "OK" buttons, late element) +
  tiny tkinter app (poor-a11y case) + local HTML page (form, upload, delayed and ARIA-only
  elements). Record → compile → replay → break a locator → halt.
- Real-app acceptance: manual walkthrough per stage.
- Must-fail acceptance tests: ambiguous match halts; stale observation re-resolves or refuses;
  changed unapproved confirm step refused; canary secret never in trace/outline/log;
  `rpa/` has no `agent` imports.

### D13 — S0 spike targets: representative spread — 2026-10-11

No specific target app yet. S0 probes: Notepad (WinUI/XAML), File Explorer + common Save As
dialog (Win32), Settings or Calculator (UWP), VS Code if installed (Electron), dagi's PySide GUI
(Qt; also the window the agent must exclude), Firefox window chrome (Gecko). Add real targets
when they appear.

### D14 — Desktop driver library: `uiautomation` — 2026-10-11

- `uiautomation` 2.0.29 (Aug 2025, Apache-2.0): thin UIA wrapper, exact-property matching,
  direct pattern access, fast tree walk — fits the fail-closed resolver. S0 confirms speed on
  large trees (File Explorer).
- `pywinauto` 0.6.9 (Jan 2025, BSD-3) not used in v1: default `best_match` fuzzy matching
  conflicts with D2; its `win32` backend is held in reserve as a second desktop driver for
  legacy MFC/VB6/Delphi apps.

### D15 — GUI: Workflows rail view + chat cards, stage S4 — 2026-10-11

- Left-rail "Workflows" view: list with status chips (draft/approved/degraded/halted); detail with
  lifecycle stepper (draft → verify run → approved), params/secrets, per-step last matched rung
  and confirm gate; primary action follows lifecycle (Verify run → Approve → Run).
- Chat cards: halt card (Screenshot / Repair / Dismiss); repair-patch card (YAML diff, confirm-step
  change notice → double confirm, Approve and re-run / Edit YAML / Reject).
- GUI is a view over CLI + `rpa_*` tools; delivered as stage S4 after S1–S3.

## S0 spike results — 2026-10-11

Installed into `dagi`: pip `uiautomation` 2.0.29, `selenium` 4.51.0, `mss` 10.2.0; conda-forge
`firefox` 157.0.1 (`Library/bin/firefox.exe`), `geckodriver` 0.37.1 (`Scripts/geckodriver.exe`).
Probe scripts were throwaway (session scratchpad); only aggregates recorded here.

**UIA (desktop)** — nodes / walk time / interactive controls with AutomationId / with Name:

| Surface | Nodes | Walk | Inter. id | Inter. name | Note |
|---|---|---|---|---|---|
| Calculator (UWP) | 89 | 0.07 s | 97% | 100% | ids **52/52 identical across relaunch** |
| Notepad (WinUI) | 70 | 0.07 s | 60% | 96% | menu items carry ids (`File`, `Edit`) |
| Common Save dialog (Win32) | 144 | 0.19 s | 58% | 100% | "File name:" id `1001`, "Save" id `1` |
| Windows Terminal | 38 | 0.03 s | 71% | 82% | (minimized when probed) |
| Chrome (browser chrome) | 291 | 0.16 s | 42% | 75% | |
| VS Code (Electron), default | 19 | 0.03 s | 17% | 67% | thin tree |
| VS Code + `--force-renderer-accessibility` | 403 | 0.28 s | **2%** | **98%** | full tree; ids absent |
| Claude desktop (Electron, maximized) | 24 | 0.02 s | — | — | thin; a UIA "nudge" did not help |
| File Explorer (minimized) | 8 | 0.01 s | — | — | minimized windows expose ~nothing |

Walk cost ≈ 0.7–1.3 ms/node, so a 400-node tree is ~0.3 s.

Consequences for the design:
- **Minimized windows** expose almost nothing → the UIA driver must restore a window (takes focus,
  so takes the desktop lock) before observing it.
- **Electron apps** need `--force-renderer-accessibility` at launch (workflow `launch:` should
  support extra args; `ui_roots(launch=…)` adds it for known Electron apps). With it, ids are ~absent,
  so Electron targets resolve on rung 2 (role + name) — the ladder holds.
- Win32/UWP/WinUI ids are stable across relaunch → rung 1 is reliable there.
- `uiautomation` is fast enough without caching for v1 (D14 confirmed).

**Browser (Firefox 157 via geckodriver + Selenium, headless)** — all checks passed:
start 3.7–5.2 s; persistent `-profile` dir kept localStorage across restarts; outline JS 14 nodes in
5 ms; two identical "OK" buttons both matched (ambiguity is detectable); explicit wait caught a late
element (1.5 s); upload via `send_keys(path)` on `input[type=file]` with no native dialog; canary
password never appeared in the outline (`[secure]`).
- WebDriver-computed `aria_role` is **empty for date and password inputs** in Firefox → dagi's own
  outline JS is required (D9 confirmed); use computed name only as a cross-check.
- Outline JS gap: file inputs got no name → fall back to `name` attr / "Browse…" text.

**Set-of-marks screenshot cost** (1920×1080 viewport; primary monitor is 2560×1440):

| Sent width | PNG | ≈ tokens (Claude w·h/750) | ≈ tokens (512-tile models) |
|---|---|---|---|
| 1920 | 19 KB | ~1,530 (provider downscales) | ~1,100 |
| 1280 | 26 KB | ~1,130 | ~1,100 |
| 1024 | 19 KB | ~720 | ~770 |
| 800 | 13 KB | ~440 | ~430 |

Estimates from documented formulas, not measured on the (not yet chosen) multimodal default model.
dagi's compaction assumes 1,024 tokens/image (`_ESTIMATED_TOKENS_PER_IMAGE`) — consistent.
- Marks are legible at 1024 px wide. Default screenshot width **1280** (≈1.1k tokens); with D4's
  last-3 retention ≈ 3.3k tokens of images in context.
- Overlay lessons: draw marks only on interactive leaves (skip `nav`/`form`/heading containers);
  place labels so they don't cover the control's text; skip zero-area boxes.

**Live vision check — deepseek-flash through dagi's `AgentLoop` + `read` tool** (2026-10-11).
`deepseek-flash.yaml` has no `supports_images`, so `_attach_image` refuses images by default; the
test set `supports_images=True` in memory only. The image reached the model in both runs.

| Image | Marks read correctly | Failure mode |
|---|---|---|
| v1: full 1024×530, marks on every role incl. containers, labels at top-left | ~6 / 15 | stacked labels; invented text ("From: / Now", "FX", "Approved table") |
| v2: cropped to content (996×134), interactive leaves only, labels alternating above/below | 7 / 11 | every miss = a label sitting in the gap between two adjacent controls (3↔5, 13↔14 swapped); it also invented entries for absent numbers (1, 4, 12) |

Conclusions:
- Screenshots are **context, not the source of truth**. The model picks targets from the text
  outline (exact role/name/id); the screenshot only disambiguates layout. Confirms D3 text-first.
- Overlay rule: the label must be unambiguous — **inside the box's top-left corner** (or attached
  with a leader line), never in the gap between controls; never label containers.
- Send a crop of the region of interest rather than the full window: add `region` (or a target
  index to zoom on) to `ui_observe(mode=screenshot)`. The model itself asked for a zoom.
- The model flags its own uncertainty and over-reports ("list every number") — the outline, not
  the image, must define which indices exist.
- Before S1, `supports_images: true` must be set on the default model's config.

## Closing summary (grill, 2026-10-11)

- Shared understanding reached on D1–D15.
- Tested and held: replay format, locator ladder, tool surface, safety gates, browser choice
  (revised Chrome → Firefox after the Chrome 136 / Firefox CDP facts), driver library, staging.
- Unresolved: verify-run details (clean-start preconditions per workflow); notification channel
  for halts outside chat (deferred with the scheduler).
- Before planning: S0 spikes (D13/D14); R20 prerequisite task (D10).
- Lifecycle: `draft` → Admiral reviews YAML → verify run (full replay from a clean start,
  Admiral watching) → `approved`. `rpa_run` warns on non-approved; future scheduler refuses them.
