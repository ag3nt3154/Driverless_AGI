# TODO

## In progress

- **Events-log restore (if ever wired up)** — no shipped path restores a loop from
  `*.events.jsonl` (`/hist` uses tracker `raw_messages`). `SessionLog(seed=...)` does not
  enforce call/result pairing, so a truncated events file would send an unpaired call.
  Add a pairing check on seed before building any events-log restore.

- **Session tool-chain improvements** (from the
  [fix/session review](_CODEX_FIX_SESSION_REVIEW_2026-10-03.md)) — all items handled.
  Dropped: schema-arg validation (a clearer error still costs the retry); multi-step tool
  chains (needs a stop-rule language the review itself warns about).
  Done 2026-10-03:
  - `bash` description names the real OS/version/shell; prompt OS-detection step removed.
    Gap: Windows Server labelled by build (10/11); switch to `platform.release()` once the
    Python floor is >=3.12 (3.11 reports 10 on Windows 11).
  - Piped commands get an exit-status note; description says output is already
    head/tail-trimmed. Gap: regex misses `^^|`/`\|`; heredoc/comment `|` false-positives.
  - `parallel_tool_calls` configurable, default true (was hard-coded False).
  - `ask_user` batched with other calls: the whole batch is refused before anything runs
    (`SOLO_TOOLS` in `agent/_tool_dispatch.py`); prompt + tool description state the rule.
    Add any future user-question tool (e.g. a revived `show_plan`) to `SOLO_TOOLS`.
  - `edit` takes an `edits` list for one file: in order, all-or-nothing, placeholder-tolerant.

- **2026-10-05 review refresh on main.** See
  [_CODEX_CODE_REVIEW_2026-10-05.md](_CODEX_CODE_REVIEW_2026-10-05.md) and
  [_CODEX_SUGGESTIONS_2026-10-05.md](_CODEX_SUGGESTIONS_2026-10-05.md).
  R2 and R6 fixes verified; R3's constructor mismatch is fixed, but initialization
  failures still escape without recording a run. R4/R8/R9 reproduced; R7 improved
  (`run` is now 39 lines), with construction/dispatch and adapter contracts remaining.
  New R10: scheduler records ghost-response exhaustion as success despite the loop's
  terminal error. Historical September Telegram defects revalidated as R11/R12:
  final handoffs are dropped and answers cannot dispatch while a task is waiting.
  New R13: typing-send failure leaves the chat busy. Proposed repairs remain unimplemented,
  except R9 (fixed 2026-10-05: tolerant decode, log-independent drain, failure notes in
  the output tail; real-process tests showed the old reader left chatty children blocked
  on a full pipe until timeout) and R8 (fixed 2026-10-05: timed-out children keep their
  identity by PID; immediate and resumed results share `_finalize`, so resumed inherited
  results are rejected as `stale` with a reason). R8 residual: entries for children never
  resumed or force-killed linger until PID reuse/process exit; fold into the R7/S1 owned
  run handle. R7 is being taken one function at a time: `subagent_api.run_subagent`
  done 2026-10-05 (CC 25 -> 7; argv contract pinned by `TestChildArgvContract`);
  `agent/tools.py::create_tool_registry` done 2026-10-05 (158 lines/CC 36 -> CC 2;
  ordered tool-name contract in `tests/test_tool_registry_contract.py` — order is the
  provider-visible schema order); `AgentLoop.__init__` done 2026-10-05 (168 lines/CC 13
  -> ordered `_init_*` phases, CC 2; attribute set and tracker/snapshot contract in
  `tests/test_loop_construction.py`); `dispatch_tool_calls` done 2026-10-06 (126 lines/CC 20
  -> `_Batch` + per-call phases, CC 5; full event trace pinned by
  `TestDispatchEventTrace`). All four R7 functions are done. Still open from R7:
  `agent/loop.py` is ~1,080 lines vs the 500-line cap. Small leftovers in `agent/tools.py`: `_load_project_tools`
  CC 12, 106-char `_default_ask_user` line. Scheduler/Telegram/TUI items deferred.
  Note: the intentional `.dagi/skills/` removal breaks 3 tests in
  `tests/test_workflow_plan_template.py` (they read `write-plan/references/plan-template.md`).
  Campaign R1/R5 remain outside this checkout, not resolved. Selected tests: 179 core
  passed; 263 broader checks passed; two WebEngine setup errors passed on unsandboxed
  rerun (444 selected tests ultimately passed). Offline probes made no network calls.

- **2026-10-02 automation review follow-ups.** The review covered `task/iteration-engine`
  at `6917b131`. Its report files, `_CODEX_CODE_REVIEW_2026-10-02.md` and
  `_CODEX_SUGGESTIONS_2026-10-02.md`, are in the repo root. R2 and R6 are fixed (2026-10-05);
  R7 is in progress; the rest are still open.
  - **P1 R1 (campaign):** tampering during the *holdout* pass is swallowed by
    `_holdout_if_better` (`campaign/engine.py`), so the trial can still be accepted.
    Fix: propagate `evaluator_modified` and fail the trial, as `_rescore_holdout` already
    does. Add a regression test where holdout inference alters the labels.
  - ~~**P1 R2 (agent):** multiple END_TURN results in one tool batch~~ — fixed 2026-10-05.
    The first END_TURN call wins. Every later call in the batch is skipped without running,
    but still gets a `[skipped]` result. Tests: `tests/test_end_turn_batch.py`. (A parallel
    local fix, `0f93469c`, ran every call and let the last handoff win; the merge of
    2026-10-05 kept first-wins.)
  - **P1 R3/R4 (scheduler):** ~~`scheduler/runner.py` passes an unsupported `tracker=` to
    AgentLoop~~ — fixed 2026-10-05 by R7 step 2 (`tracker=` is now the public argument).
    Still open: its timeout does not stop the worker (known from the 2026-09-06 review;
    consider reusing `campaign/process.py`).
  - **P2 R5 (campaign):** an engine killed during the agent stage neither archives the
    workspace nor counts the attempt. This is the documented §9 trade-off; revisit it
    with a started-attempt record.
  - ~~**P2 R6:** the garbled-response revision is not persisted~~ — fixed 2026-10-05 by R7
    step 3. Recovery now goes through `AgentLoop.revise_last_steps`, which rewrites the
    events file (`write_session` is now atomic: temp file + replace). The events path is
    fixed at construction, so appends and rewrites keep hitting one file after the tracker's
    slug rename (previously a revise after the rename wrote to a different file).
    Test: `test_garbled_recovery_is_saved_to_the_events_file` reloads the file and compares.
    Still open: a durable revision *event* instead of a whole-file rewrite.
  - **P2 R7 (agent):** core orchestration is too large. Step 1 done 2026-10-05: the request
    retry loop moved out of `AgentLoop.run` into `agent/_request_executor.py`
    (`RequestExecutor` returns RESPONSE / ABORTED / PAUSED / NULL_EXHAUSTED); `run()` is
    351 → 239 lines. Tests: `tests/test_request_executor.py`. Step 2 done 2026-10-05:
    frontends (GUI, TUI, Telegram, subagent runner, benchmarks) use a public surface —
    `messages` (copy), `is_paused`, `is_running`, `revise_last_steps(n)` (replaces the
    duplicated GUI/TUI revise+persist+sync code, and now refreshes messages even if the
    save fails), and `tracker=` / `session_log=` constructor arguments. Tests:
    `tests/test_loop_public_api.py`. Remaining private access: `subagent_main.py` sets
    `_extra_body` / `_parallel_tool_calls`. Step 3 done 2026-10-05: garbled-response
    detection/recovery moved to `_garbled_streak_reached` / `_recover_from_garbled_loop`
    (`run()` now 216 lines) and fixed R6. Step 4 done 2026-10-05: `tests/test_run_contract.py`
    drives every `run()` exit path (handoff, tool step, max continuations, double END_TURN,
    null exhausted, non-transient error, retries exhausted, retry success, garbled recovery,
    /reload, consecutive runs, pause-on-error + resume, interrupt + resume) and checks the
    log is well-formed (turn/step brackets, call/result pairing, turn-end reason) and that the
    events file replays to the live log. It found and fixed one bug: pausing after exhausted
    API retries left the step open, so the next step started inside it. Step 5 done
    2026-10-05: `agent/_turns.py` `TurnBoundaries` (`loop.turns`) is the one writer of
    turn/step start/end events; `/reload`, `/wtf` and GUI compact use its `side_turn()`.
    `run()` is now a ~40-line loop over `_run_step()`, which returns (result, turn-end
    reason) or None; reply handling is in `_handle_text_reply` / `_handle_tool_reply`.
    Fixed two garbled-recovery bugs found by a new contract test: recovery after any real
    step in the same turn crashed with `InvariantError` (turn already open), and when every
    step was garbled it deleted the user's task message. Recovery now removes only the empty
    steps (`revise_last_step(keep_turn=True)`) and continues in the same turn.
    Tests: `tests/test_turns.py`, `tests/test_run_contract.py`. Remaining R7 ideas: a
    tool-batch finalizer for call/result pairing (R2 is already fixed in `_tool_dispatch`);
    `__init__` is still 167 lines. No repository-wide cosmetic split.

- **Windows shell contract and quoting (investigated 2026-10-02; awaiting approval)** —
  preserve the `bash` name; resolve and advertise its actual shell, CWD and Python executable
  from runtime; add shell-free argv/stdin execution for Python scripts; replace Unix shell
  examples in memory skills with native tools, resolving the Claude-copy parity requirement.
  Include main/subagent registries, prompt overrides, tool filtering and `run_skill_script`.
  Live probe: multiline `python -c` printed only its first line and returned success;
  argv plus stdin printed both lines and preserved shell-sensitive arguments.
  Verify Windows/POSIX execution, errors, timeout and force-kill behavior. No runtime changes.

- ~~**Persist history revisions through one save path**~~ — fixed 2026-10-05 by R6/R7:
  `AgentLoop.revise_last_steps()` is the one save path (atomic `write_session`), used by
  garbled recovery and `/revise-history` in both frontends. Original note:
  `SessionLog.revise_last_step()`
  never reaches `on_append`, so garbled recovery leaves the removed steps in
  `*.events.jsonl`, while `/revise-history` in both frontends rewrites the file itself with a
  non-atomic `write_session` (a crash mid-rewrite loses the log). Fix: one save hook on
  `SessionLog`, installed by `AgentLoop`, that writes a temp file and `os.replace`s it; drop
  the frontend rewrites. A replayable revision event (format v4) was considered and
  deferred: nothing reads the events file back yet, and the tracker log already keeps the
  raw responses. Revisit only together with "Events-log restore" above.

- **Stale "compacting" status after a no-op recovery compaction** (cosmetic) — garbled
  recovery fires `on_compaction_started` before `compact(summarize_all=True)`; when that
  compaction is a no-op (turn 1, or a second recovery in a turn with no new completed step)
  `on_compaction` never fires, so the PySide sidebar shows "compacting" until the worker's
  `finally` resets it to idle. Fire a matching end callback, or skip the start when no
  selection exists.

- **`dispatch_tool_calls` is over the size cap** — `agent/_tool_dispatch.py`'s per-call
  orchestrator is 116 lines / ~17 decision points (standards: ≤ 100 lines / ≤ 8). It was
  already 104 lines / ~16 before `0f93469c` added 12; the cap was waived for that bounded
  fix so it stayed surgical. Needs its own refactor task: extract the per-call body into
  `_dispatch_one_call(loop, tc, tool_records, deferred)` with a `_DeferredStep` accumulator
  (system notices, image parts, end-turn output), then split the side-effect routing further
  to meet the complexity cap. That task must unit-test the guards covered only by
  `tests/test_agent_loop.py` today: the pause-cancel path, the malformed-JSON repair path,
  and `ATTACH_IMAGE`.

- **Shared truncation for remaining self-capping tools** — `web_fetch` (`_MAX_CHARS`, rest
  lost) and `read_notepad` (`MAX_CHARS`) still cut their own output; move them onto the
  shared head + marker + tail filter so the full output is saved and reachable with
  `read_large_file`. Also decide on pruning `.dagi/hash_cache/tool_output/`.

- **OpenGhost-inspired GUI refresh — next passes** —
  UI pass 1, mermaid, the visualize prompt line, global instant Esc and the context
  meter, long-paste cards and typing while the agent runs are done (see Completed). The
  OpenGhost review list is finished.
  Decided against (2026-10-01): the `files` block, "talk while you work" / tool
  `description`, selection menu + mini chat, and permission modes / approval cards —
  DAGI stays yolo-only (no approval gate).
  - Mind the LICENSE carve-out on OpenGhost's visual design (non-commercial only, keep attribution).

- **Redesign `memory-refresh` for the central memory wiki** — pending. The skill,
  subagent and scripts still target the retired layout (its SKILL.md line
  `{memory_root} = …` now renders confusingly because `memory_root` is the vault root);
  the `memory_refresh` tool is disabled via `disabled_tools`. Rebuild it as a lint of the
  four-field frontmatter, layout, stale todos and duplicates
  (`black_grimoire/src/migrate_wiki/validate.py` is a starting point).

- **Production review (R5, R8, R11, R17)** — remaining deferred findings from
  `projects/driverless-agi/production-review-2026-09-15.md` in the central memory
  wiki. R5 (session filename
  collisions) and R8 (pipe subagent prompt loss) deferred pending design
  decisions; R11 (interrupted restore from events) deferred for complexity;
  R17 (orderly GUI shutdown) deferred — needs design for worker cancellation,
  process-tree cleanup, and state persistence.

- **Grep tool hardening** — grep now excludes `.dagi/`, `__pycache__/`, `.git/`,
  `.mypy_cache/`, `.pytest_cache/`, `node_modules/`, `.tox/`, `.venv/`, `venv/`,
  and binary file extensions (`.pyc`, `.pyo`, `.pyd`, `.so`, `.dll`, `.exe`,
  `.bin`, `.whl`, `.egg`) from both the ripgrep and Python-fallback code paths.
  Tool description updated to mandate a specific subdirectory path (not `.` or
  project root), mention ripgrep explicitly, and forbid bash `findstr`/`grep`
  workarounds. (The output-filter "refine your search" message was later replaced by
  the head + marker + tail format — see the large-file reading entry in Completed.)

## Completed

- **`main.py` UTF-8 stdout (2026-10-07)** — the single-shot CLI crashed with
  `UnicodeEncodeError` printing a result containing `→` on Windows (cp1252 stdout).
  `main()` now reconfigures stdout to UTF-8 with `errors="replace"`. Test:
  `tests/test_main_cli.py`.

- **Code mode v1 (2026-10-07)** — `code` tool (`tools/code/`): one Python script chains
  `read`/`grep`/`find`/`write`/`edit`/`copy`/`bash` calls through the parent registry over
  JSON-lines RPC; only printed output and the return value come back. Global `code_mode`
  (file default `true`). `BashTool.run_structured` gives scripts the exit code as data.
  Spec/plan: `wiki/tasks/2026-10-07_code-mode/`. Follow-ups, not done: an `only` mode (normal
  tools hidden); a per-model switch for weak models; nested tool cards and session events
  for calls inside a script; read-only parallel calls; benchmark `on` vs `off` in
  `benchmarks/dagi_eval` (steps, tokens, success rate).

- **GUI light theme (2026-10-06)** — Material 3 light palette (`theme.LIGHT`, Google's
  M3 web roles: `#0b57d0` primary, `#f0f4f9` surface containers, white chat surface) beside
  the existing dark one. **View → Theme → Dark / Light / System**, saved to
  `.dagi/gui_settings.json`, `DAGI_THEME` env override; applies on restart (offered from the
  menu). Hard-coded colours (overlay scrim, status pills, icon state) now come from tokens;
  conversation/notepad pick highlight.js and Vditor themes from `--hljs-style` /
  `--color-scheme`. Vendored highlight.js `github.min.css` and Vditor `content-theme/light.css`.
  Tests: palette parity, `use()` swap, preference round-trip, WCAG 4.5:1 contrast for light
  text tokens; GUI tests pin `DAGI_THEME=dark`. Not done: live switching without restart
  (needs every widget to rebuild its stylesheet from a theme-changed signal).

- **Garbled recovery fixed 2026-10-03** — it deleted the human prompt when the empty steps
  were the turn's first (whole turn wrapper revised away), crashed with
  `InvariantError: turn N is already open` when a completed step preceded the streak, and
  counted empty replies across tool steps (so "revise the last 3" hit a real tool step).
  Now: `revise_last_step(keep_turn=True)`, no new turn, no `iteration` reset, tool steps
  reset `_empty_content_streak`; `_selected_source_nodes` limits `summarize_all` to nodes
  up to the worker's cut (`takewhile seq <= step_end_seq`), so a later turn's prompt is no
  longer replaced unsummarised. Still open: subagent events interleaved in a removed step
  are deleted with it (`revise-history-open-questions` in the wiki).

- **Batched END_TURN results paired (2026-10-03)** — `0f93469c`. A response asking for
  `write_handoff` twice kept only the last call in a single deferred slot, so the first
  call's result was never recorded and the transcript shipped an unanswered tool call
  (rejectable by a strict provider, and read as unfinished work on replay). `dispatch_tool_calls`
  now bookkeeps every call of the batch in the model's call order and defers only the turn's
  termination; that also fixed results being filed out of order and the reload/image notice
  landing between the assistant `tool_calls` message and a tool result. Closes review item
  R2. Tests in `tests/test_agent_loop.py`: `TestBatchedHandoffPairing`, plus a
  `TestDispatchToolCallsExtraction` case asserting a deferred reload notice never
  separates a call from its result.
  Verification: 1457 passed / 2 skipped in `tests/`, 255 passed in `pyside_gui/tests`; the one
  failure is the known markitdown `[docx]` optional-dependency one.

- **GUI render stalls on some machines (2026-10-06)** — reported: flashing "Thinking…",
  handoff not shown in full, `ask_user` question not shown. Cause found: every reasoning
  delta re-sent the *whole* reasoning text to the page (quadratic; 3,000 deltas left the page
  ~200 s behind, so later handoffs/questions queued behind it). `ConversationView` now
  coalesces previews on a 120 ms timer and sends only the last 4,000 chars (3,000 deltas: ~2 s).
  Also: `renderMarkdownInto` falls back to plain text instead of throwing (a throw dropped the
  handoff/question and left "Thinking…" pulsing forever); page JS errors are logged to
  `.dagi/logs/pyside_worker.log`; the `write_handoff` card no longer stays "running"; a late
  reasoning delta after answer text no longer throws. New `python -m pyside_gui.check_render`
  self-check. Root cause on the affected machine: its checkout predated the `.gitignore`
  re-include of `pyside_gui/resources/vditor/dist/` (global `dist/` rule), so Lute/Vditor never
  loaded. `.gitattributes` `-text` now points at the shared `pyside_gui/resources/vditor/**`
  (it still named the old `notepad/vditor` path), keeping the engine byte-exact. Open: Lute is
  quadratic on a single huge paragraph (40k chars ≈ 6 s).

- **GUI auto-scroll after sending (2026-10-03)** — the chat pane no longer gets stuck above
  the newest message after a send. Follow mode changes only on real scroll events (within
  48px of the bottom); the composer resizing the view re-pins; sending always pins; Show
  more and sent-image loads re-scroll. Tests in `pyside_gui/tests/test_scroll_to_bottom.py`.

- **Session log review (2026-10-02)** — findings, causes, scriptable tool sequences and
  instruction inconsistencies are in
  [_CODEX_SESSION_LOG_REVIEW_2026-10-02.md](_CODEX_SESSION_LOG_REVIEW_2026-10-02.md).
  Recommendations remain proposals; no runtime fixes were implemented.
  Marked the 32 reviewed families (55 files including companions) with
  `__reviewed_2026-10-02`; verified contents unchanged and updated evidence links.

- **read: Office, PDF fallback and images (2026-10-01)** — `.docx`/`.xlsx`/`.xls`/`.pptx`
  convert in-process with markitdown (`tools/read/_convert.py`); PDFs try the conversion
  API (`services.doc_converter`, now just `POST /convert` in `_doc_service.py`) and fall
  back to markitdown, with form-feed page breaks turned into `<!-- Page N -->` markers.
  Results are hash-cached (`doc_convert/`, fallbacks in `doc_convert_markitdown/`). Images
  (`tools/read/_image.py`) return `SideEffect.ATTACH_IMAGE`; `_tool_dispatch.py` stores the
  image and logs it in a user message after the step's tool results, only when the active
  tier has `supports_images: true` (`current_supports_images()` in `_model_switch.py`).
  Every unconvertible case returns a `DAGI_CANNOT_PROCESS` tool result. New `read` extra
  (markitdown extras + Pillow). Tests: `test_doc_convert.py`, `test_read_image_dispatch.py`,
  updated `test_read_tool.py` / `test_doc_service.py`. Not yet run against a live
  multimodal endpoint.

- **grep/find on the shared truncation filter (2026-10-01)** — the 200-line (`grep`) and
  500-path (`find`) caps are gone; results go through `filter_tool_output`, so large ones
  show the first and last matches with the full list saved. A 100,000-line `_SAFETY_LIMIT`
  in each tool only guards memory against runaway searches. New `tests/test_find_tool.py`.

- **RAM watchdog threshold raised to 85% (2026-10-01)** — `tests/conftest.py`
  (`RAM_WARN_PCT`) and `scripts/monitor_tests.py` (`RAM_THRESHOLD_PCT`) went from 70% to
  85%; idle RAM on the dev machine was already above 70%, so every test failed in setup.
  The 90% hard-kill threshold is unchanged.

- **Large file reading redesign (2026-10-01, branch `feat/large-file-reading`)** — plan in
  `docs/large-file-reading-plan.md`. `read` no longer delegates or stops at 2000 lines: an
  oversized result is head + marker + tail (4000 chars each end, whole lines, real line
  numbers; `tools/_truncate.py`, `truncate_edge_chars`). `filter_tool_output` (bash and every
  other tool) uses the same format and keeps the tail; the marker points at the saved output.
  New `read_large_file(path, query?, offset/limit, pages)` replaces `read_large_text`: a fixed
  loop where each call holds only a capped running summary + one numbered chunk, append-only
  per-chunk notes merged (batched if needed) into an index with verbatim excerpts; unverified
  excerpts flagged; cached by content + query + model. Also fixed: section line ranges, the
  bytes-vs-tokens request estimate, and the reader running on the main model with the file's
  folder as project. `use_legacy_reader` removed.

- **Typing while the agent runs (2026-10-01, branch `feat/type-while-running`)** — the GUI
  composer stays live during a run; Send queues the message (`pyside_gui/steer_queue.py`)
  and `AgentLoop.steer()` logs it at the next checkpoint without pausing, confirmed by the
  new `on_user_injected` callback. Queued bubbles pin below the live turn with a ✕ (first
  JS→Python bridge in the conversation pane, QWebChannel); unconfirmed leftovers become the
  next turn. Send/Stop follows whether the field has content. TUI unchanged.

- **Long-paste cards (2026-10-01, branch `feat/paste-cards`)** — big pastes become an inline
  `[Pasted text #N · L lines]` token in the composer (`pyside_gui/paste_cards.py`), expanded on
  send into a ```` ```pasted ```` fence; user bubbles render that fence as a collapsed card and
  cap tall messages behind "Show more".

- **Composer slimmed (2026-10-06)** — removed the composer's model pill and context ring
  (`context_meter.py` deleted, `RightSidebar.context_usage` dropped); both duplicated the right
  sidebar. Model switching moved to the sidebar: the model name is a centred, bordered button with a `▾`
  chevron that opens the catalog menu
  (`_ModelPicker` in `pyside_gui/right_sidebar.py`, routed through `/model`).

- ~~**Context meter (2026-10-01)**~~ — composer ring; removed 2026-10-06 (see above).

- **GUI open-folder button (2026-09-30)** — header folder button performs `/wd` with a
  native picker and the 5 most recent folders (missing ones greyed); `/wd <path>` is now
  refused while the agent runs; recents in `.dagi/recent_folders.json`
  (`pyside_gui/recent_folders.py`, `header.py`).

- **Global instant Esc (2026-09-30, branch `feat/instant-esc`)** — `AgentLoop.interrupt()`
  closes the in-flight stream (verified: `stream.close()` from another thread unblocks the
  httpx read at once), drops late blocking responses, cancels the rest of the tool batch,
  and keeps partial streamed text. A separate `_abort_request` flag plus loop-thread
  injection at the checkpoint fixes a race where a quick resume let the interrupted
  response's tools run, or logged the user's message between a tool call and its result.
  GUI: app-wide event filter (`pyside_gui/esc_stop.py`) so Esc works from web views and the
  pet window; popups, dialogs and `claim_escape()` widgets get Esc first; the stream bubble
  freezes. TUI's Esc uses the same `interrupt()`.

- **Visualize prompt line (2026-09-30)** — one `Guidelines` bullet in
  `.dagi/prompts/main/main_system.md` asks for a mermaid diagram when structure, flow,
  sequence, timeline or numbers explain better than prose (≤ ~15 nodes, short quoted
  labels, no colours / `%%{init}` / `click`). Shared by every frontend; the TUI and
  Telegram show the fence as a code block.

- **Mermaid diagrams in the conversation pane (2026-09-30, branch `feat/mermaid`)** —
  mermaid 11.16.1 vendored via `scripts/vendor_vditor.py`; own renderer in
  `conversation.js` (not `Vditor.mermaidRender`, which forces `securityLevel: "loose"`
  and only offers a light/dark theme).
  - Strict security, token-derived `themeVariables`, SVGs cached by source.
  - A "Drawing diagram…" placeholder while a fence is still streaming.
  - Code/Copy hover toolbar; invalid syntax falls back to the source plus an error line.
  - The notepad's Vditor preview now draws mermaid too, pinned to strict by a
    `window.mermaid` setter guard in `notepad.js`.

- **GUI UI pass 1 (2026-09-30, branch `feat/openghost-ui-review`)** — neutral dark theme
  from one token table (`pyside_gui/theme.py`, `icons.py`) replacing every hard-coded
  Catppuccin colour in Qt and web.
  - The conversation pane is rendered with Vditor (Lute + KaTeX + highlight.js + callouts) from raw markdown.
  - Model HTML stays literal; `\(\)` and `\[\]` math works.
  - OpenGhost-style layout:
    - user bubbles;
    - quiet tool one-liners with derived labels (`tool_labels.py`);
    - "Thought for Ns";
    - a pet welcome screen.
  - A composer card (auto-grow, `+` attach, send/stop; model picker now in the right sidebar) and a header bar with sidebar toggles.
  - Vditor moved to the shared `pyside_gui/resources/vditor/`.
  - Review, decisions and mockup: `docs/2026-09-30_openghost-ui-review.md`, `docs/mockups/`.

- **Pet notepad (2026-09-30, branch `feat/pet-notepad`)** — pinote-style WYSIWYG
  markdown notepad in the desktop-pet window: right-click the pet to open/close/save-as;
  vendored Vditor 3.11.3 (IR mode, no toolbar, KaTeX, highlight.js, Catppuccin) via
  `scripts/vendor_vditor.py`; global autosaved `.dagi/notepad/notepad.md` with a file
  watcher and `conflict-<ts>.md` backups; read-only `read_notepad` tool (always
  registered, flushes GUI edits first). Plan: `docs/pet-notepad-implementation-plan.md`.
  Follow-ups: optional `append_notepad` write tool; opacity / fade-when-unfocused;
  pasted images; Vditor 4.x bump once it matures.

- **Flaky notepad GUI test fixed (2026-10-01)** — `test_edits_are_flushed_on_hide`
  ("editor did not load") failed under machine load only when the whole module ran.
  Cause: tests `deleteLater()` widgets but never run a top-level event loop, and
  `processEvents()` skips DeferredDelete at loop level 0, so every earlier pet window
  stayed alive and its notepad web view kept loading Vditor alongside the new one
  (5 concurrent loads, ~4 s each idle; >15 s under CPU stress). New autouse fixture in
  `pyside_gui/tests/conftest.py` flushes deferred deletes before/after each test.
  Under 16 busy processes: `main` failed 2/3 runs, fixed 3/3 pass; GUI suite 217 passed.

- **PySide GUI test suite green (2026-09-30)** — `pyside_gui/tests` went from 7 failed /
  32 errors to 135 passed. `qtbot` errors: pytest-qt stays disabled globally in
  `pyproject.toml` (Windows QtCore DLL crash, added in 3815cb7) and is now re-registered
  from `pyside_gui/tests/conftest.py` after the `pyside_gui` DLL bootstrap. Rewrote
  `test_expression_widget.py` for the process-only `ExpressionWidget.update_process` API
  (affect channel + rotation timer were removed), updated the bridge test for the removed
  `expression_changed` signal, and fixed the stale 4-button rail assertion in
  `test_left_sidebar.py` (5 views since the message board). Full
  `pytest tests pyside_gui/tests`: 1518 passed, 3 skipped.

- **Test-suite skips/failures triage (2026-09-30)** — `chonkie` (used optionally by
  `tools/read/_chunking.py`) was undeclared, so 6 chunking tests always skipped; now in
  `requirements-tools.txt` and the `chunking` extra. Remaining skips are environmental:
  `test_memory_skill_parity` needs `~/.claude/skills/memory-{add,query}` installed, and one
  `test_image_assets` symlink test needs Windows Developer Mode.

- **Standalone client-script models (2026-09-29)** — a `.py` file in
  `.dagi/model_config/` is now a catalog model on its own (no YAML): it defines
  `client` (sync `openai.OpenAI`, for mTLS / guardrail headers / custom transports),
  optional `request_kwargs` (model name via `request_kwargs["model"]`) and optional
  `dagi_config` (YAML-entry keys, read statically for the picker). Scripts are
  cached per mtime; `base_url`/`api_key` come from the built client so subagent
  inheritance re-resolves the script; `AsyncOpenAI` is rejected with a sync hint;
  broken worker/advanced scripts warn and fall back. Tests:
  `tests/test_client_script_models.py`.

- **Rewired DAGI to the central memory wiki (2026-09-27)** — `memory_root` defaults to
  `G:\My Drive\black_grimoire`; per-turn `[MEMORY]` pointer; memory-query/memory-add run
  inline as byte-identical copies of the Claude Code skills (parity test); required memory
  checkpoints in `enter-workflow`; memory/wiki subagents and the per-project knowledge wiki
  removed (`wiki/` keeps only `tasks/`); `/init` slimmed; `integrations/codex/` removed in
  favour of `~/.codex`. Spec/plan: `wiki/tasks/2026-09-27_rewire-central-memory/`.

- **Garbled Loop Recovery** — all 8 tasks complete. Detects when the model
  falls into a degenerate loop of empty-content responses, strips those
  turns, and compacts the context. Task 1: `AgentCallbacks`
  (`agent/_loop_config.py`) gained `on_compaction_started: Callable[[], None]`
  (no-op default), fired before compaction begins. Task 2:
  `ProcessStateController.compacting()` (`agent/process_state.py`) added
  alongside `idle`/`thinking`/`paused`/`error`, and the PySide right sidebar
  (`pyside_gui/right_sidebar.py`) gained a matching `"compacting"` entry in
  `_STATUS_DOTS` (`⟳`, `#89b4fa`). Task 3: `on_compaction_started` wired into
  both frontends — `pyside_gui/bridge.py` gained a `compaction_started`
  Signal connected to `MainWindow._on_compaction_started`, and
  `tui/callbacks.py` gained an `on_compaction_started` closure that posts a
  "Compacting context..." info line. Task 4: `_compact_context`
  (`agent/loop.py`) calls `self.callbacks.on_compaction_started()` before
  `self.compact()`, so the frontends' compacting status fires during real
  compaction runs. Task 5: `compact()` (`agent/_compaction.py`) gained a
  `summarize_all: bool = False` parameter; when `True`, it bypasses
  `compute_tail_boundary` and puts all steps in `middle_steps` with an empty
  `tail_steps`, summarizing the entire context with no tail retention.
  Task 6: garbled-loop detection and recovery in `agent/loop.py` — a
  module-level `_EMPTY_CONTENT_THRESHOLD = 3` and instance variable
  `_empty_content_streak` track consecutive empty-content responses; on
  reaching the threshold, empty steps are revised out via
  `revise_last_step()`, a new turn is opened (superseded 2026-10-03: recovery now
  stays in the open turn — see "Garbled recovery fixed" above), and
  `compact(summarize_all=True)` runs for full context recovery. Task 7 and
  Task 8 (final wiring/verification and documentation) done: full test suite
  passing (`tests/test_continuation.py`, 25 passed, covering
  `TestCompactionStartedCallback`, `TestCompactionStartedFired`,
  `TestFullCompaction`, and `TestGarbledLoopRecovery`), and README.md,
  TODO.md, `wiki/architecture.md`, and `wiki/index.md` updated to document
  the feature.

- **`/revise-history [n]` slash command** — fully implemented per
  `docs/superpowers/plans/2026-09-17-revise-history.md` (11 tasks, all done).
  `SessionLog.peek_last_step()` / `revise_last_step()` (`agent/session_log.py`)
  remove the last N steps (each a `step/start`...`step/end` bracket) from the
  tail of the session event log, auto-removing the enclosing turn if it was
  the turn's only step. Both `tui/commands.py` (Textual `ReviseConfirmScreen`
  modal, async callback) and `pyside_gui/commands.py` (blocking
  `QMessageBox.question`) show a confirmation dialog summarizing what will be
  removed (via the shared `tui/revise_history.py::format_step_summaries`)
  before mutating the log, rewriting the session's JSONL file
  (`write_session`), and re-rendering the conversation from
  `log.derive_messages()`. Hardened during review: persistence/re-render
  failures are caught and reported via `conv.append_error` rather than
  crashing (the in-memory revision still applies), and image content blocks
  render as an `"[image]"` placeholder instead of vanishing. Guards against
  running while the agent loop is active or with no active conversation;
  errors clearly if more steps are requested than exist. Bug fix (2026-09-18):
  `revise_last_step()` no longer removes the `turn/end` event when removing a
  step from a multi-step turn — previously left the turn "open", causing
  `InvariantError("turn N is already open")` on the next user message.
  43 tests across
  `tests/test_session_log_revise.py` (20, core `SessionLog` logic including
  regression test for partial-step-removal turn closure),
  `tests/test_revise_history_tui.py` (13: 3 for `format_step_summaries` plus
  10 handler-level tests for `tui/commands.py::_cmd_revise_history`, using a
  lightweight `SlashCommandsMixin` stand-in with `push_screen` stubbed to
  invoke the confirm callback directly), and `pyside_gui/tests/test_commands.py`
  (10 handler-level tests for `pyside_gui/commands.py::_cmd_revise_history`,
  alongside 5 pre-existing tests for other commands in that file, monkeypatching
  `QMessageBox.question`), all passing.
  Two known limitations recorded in
  `wiki/notes/revise-history-open-questions.md` for follow-up: behaviour at
  the `/hist`-restore seed boundary is undefined, and revising a step that
  spawned a subagent branch can delete the subagent's interleaved events too
  (positional slice, not branch-filtered).

- **Slash-command autocomplete (PySide GUI)** — fully complete. Typing `/` in
  the prompt input shows a `SlashCompleterPopup` (`pyside_gui/slash_completer.py`)
  listing all built-ins, skills, and workflows; filters as you type; Tab/Enter
  accepts the highlighted command (inserts it with a trailing space); Up/Down
  navigate the list; Escape dismisses; first space dismisses. Popup refreshes
  automatically when `/wd` changes the working directory via an
  `_on_completions_changed` callback on `SlashCommandHandler`. 40 tests in
  `tests/pyside_gui/test_slash_completer.py`.

- **Production review fixes (R1–R4, R6–R7, R9–R10, R12–R16, R18–R19)** —
  fifteen findings from `wiki/notes/production-review-2026-09-15.md` fixed:
  - R1: Compact fork now resolves credentials from the parent's actual model,
    not the default, preventing cross-provider key/endpoint mismatch.
  - R2: All model-output markdown render paths use `allow_html=False`,
    preventing injected HTML/event attributes from executing in the
    conversation page.
  - R3: Session restore and title derivation now use the last `session_end`
    record instead of the first, recovering all turns in a multi-turn session.
  - R4: GUI submissions carry the existing `SessionLog` to the new
    `AgentLoop` instead of creating a fresh one, keeping event sequence
    numbers monotonic across turns.
  - R6: Tool dispatch checks pause state before each tool execution,
    cancelling remaining tools instead of running them after the user pauses.
  - R7: A nonzero child exit code now always produces an error result, even
    when a handoff file exists on disk from a prior failed validation attempt.
  - R9: When the model groups `write_handoff` with other tool calls, the
    handoff is deferred and executed last so no calls are orphaned.
  - R10: Session restore is blocked while a worker thread is running,
    preventing the old worker from contaminating the restored view.
  - R12: Idle GUI compaction wraps `compact()` in a maintenance turn so
    the CONTEXT_COMPACTION surface event doesn't violate the open-turn
    invariant.
  - R13: Malformed tool-argument repair now re-projects the surface cache
    entry so the stale deep copy doesn't send broken JSON to the API.
  - R14: Bridge emits `ask_user_expired` on question timeout, clearing
    the pending-ask sink so the next user input isn't silently swallowed.
  - R15: `/clear` now resets pending restored history and affect state so
    the next task starts fresh.
  - R16: Observer callback and log-write failures inside the child stdout
    drain loop are individually caught so a throwing callback can't block
    the pipe.
  - R18: The stream deduplication flag resets after suppressing one
    duplicate so post-stream diagnostic messages still appear.
  - R19: Preflight work (wiki context, submission content, slug generation)
    is inside the try/finally that closes the turn, so a preflight failure
    can't leave a turn permanently open.


- **Reader subagent crash fixed** — `_run_with_job` in
  `tools/read/_reader_controller.py` passed the selection's parent directory as
  the positional `model_id` argument to `resolve_model_config` instead of as
  `project_path`, causing an immediate crash. Additionally, `_build_runtime`
  never set `handoff_tool` or `callbacks` on the `ReaderRuntime`, so the
  subprocess would also fail when writing the handoff. Both bugs are fixed;
  stale test assertions in `test_read_tool.py` updated to match the current
  delegation flow ("`Delegated to reader`" instead of the old
  "`Delegated to read_large_text`", `reader_job_spec.query` instead of
  `custom_instructions`).


- **Wiki handoff validation made case-tolerant** — *(superseded 2026-09-27: the per-project
  wiki delegation tools and their handoff protocol were removed; see the central-memory
  rewire entry above.)* Handoff heading matching had been made case-tolerant and the child
  protocols tightened to a fenced handoff format.

- **Subagents now inherit the main agent's context settings** — previously,
  `_apply_worker_config` and `_apply_advanced_config` in `tools/subagent_main.py`
  (and the equivalent in `agent/sub_agent.py`) replaced `context_window`,
  `reserve_tokens`, and `keep_recent_tokens` with the worker/advanced model's own
  values. Now only LLM-identity fields (model, base_url, api_key, thinking) come
  from the tier-specific config; context budget always stays from the main agent's
  `.dagi/config.yaml` top-level settings.

- **Malformed tool-call arguments no longer crash the agent loop** — when a model
  produces invalid JSON in tool-call arguments (e.g. unclosed `"` or `{}` in markdown
  content for `write_handoff`), the dispatch code already caught the `JSONDecodeError`
  and returned an error to the model, but the raw malformed string remained in the
  conversation history. On the next API call the provider rejected it with a 400,
  which was not retried and crashed the loop. Fix: `_tool_dispatch.py` now wraps
  the malformed string in valid JSON (`{"_malformed": "..."}`) and patches both the
  `TOOL_CALL` and `ASSISTANT_MESSAGE` log events before re-syncing messages.

- **Image input — all 6 stages complete** (see `docs/image-input-implementation-plan.md`).
  Stage 1 landed: `agent/user_input.py` (Qt-free `ImageAttachment`/`UserSubmission`
  value objects) and `agent/image_assets.py` (`ImageRef`, `ImageAssetStore`,
  `materialize_messages` — content-addressed store under `.dagi/attachments/`,
  atomic writes, hash/size validation, path-traversal guards). Covered by
  `tests/test_image_assets.py` (24 tests).
  Stage 2 landed: `agent/loop.py` — `AgentLoop.run()` and `inject_and_resume()`
  now accept `str | UserSubmission` (string input still works unchanged);
  images are stored via `ImageAssetStore(self.config.project_path)` and logged
  as `dagi_image` content parts (never base64 in the event log);
  `_build_request_messages()` now calls `materialize_messages()` so the
  provider only ever sees `image_url` data URLs; image-only first turns use
  the local `"image-conversation"` slug fallback instead of an LLM call or
  synthetic user text; `agent/session.py` `SessionTracker.record_user()`
  widened to `str | list`; `agent/session_events.py` `SESSION_FORMAT_VERSION`
  bumped 2 -> 3 (old runtimes reject v3 logs; `session_store.py` already read
  any version <= current, so v2 logs still load fine). Covered by
  `tests/test_loop_image_integration.py` (11 tests).
  Stage 3 landed (fork/resume/configuration): `agent/_loop_config.py` `AgentConfig`
  gained flat `supports_images` / `image_input_*` fields (None=unknown-permit,
  True=permit, False=block); `agent/config_loader.py` `_build_config_from_entry`
  now reads `supports_images` and a per-model `image_input:` block from
  `.dagi/config.yaml`; `agent/_model_switch.py` `handle_switch_model` gained a
  preflight (`_history_has_images`) that rejects a tier switch *before* any
  config/client mutation when the surface history contains `dagi_image` parts
  and the target tier's `supports_images` is explicitly `False`;
  `agent/_compaction.py` `compact()` now runs the reconstructed fork prefix
  through `materialize_messages()` before building the fork snapshot, so the
  compaction subprocess only ever sees data-URL images, never internal refs;
  `agent/history.py` gained a shared `_content_label()` helper used by
  `_derive_title()`, `build_turn_list()`, and `build_copyable_messages()` so
  image-only/mixed messages render as `"text [N images]"` instead of being
  stringified or skipped; `tools/compact/_tail_boundary.py` `estimate_tokens()`
  and `tui/utils.py` `_breakdown()` replaced the flat 200-token image
  placeholder with a per-image estimate (1024 tokens/image) added on top of
  real text-token counts. Covered by `tests/test_image_config_and_labels.py`
  (22 tests); `tests/test_tail_boundary.py` updated for the new per-image
  estimate.
  Stage 4 landed (PySide GUI composer): `pyside_gui/app.py`'s submission/dispatch
  logic (`_on_input_submitted`, `_dispatch_agent`, `_agent_work`,
  `_handle_special_command`) was extracted into `pyside_gui/_dispatch.py` as
  free functions taking the window as their first arg, keeping `app.py` under
  its 500-line cap (436 lines) while `DagiMainWindow` keeps thin wrapper
  methods for backward-compat test hooks. `pyside_gui/prompt_input.py`'s
  `PromptInput` is now a `QWidget` wrapping an inner `QPlainTextEdit`, an
  `_AttachmentStrip` of 64x64 thumbnails with per-image remove (X) buttons,
  and clipboard paste handling (`canInsertFromMimeData`/`insertFromMimeData`):
  image pixels (`QMimeData.hasImage()`) take precedence, then local file URLs
  with `.png`/`.jpg`/`.jpeg` extensions (whole batch rejected on any failure),
  else default text paste. Pasted/dropped images are decoded via `QImage`,
  encoded to PNG via `QImage.save()`/`QBuffer`, and validated against the same
  limits as `AgentConfig` defaults (max 4 images/message, 8 MiB/image, 24M
  px/image) before becoming an `ImageAttachment`; violations emit
  `attachment_error` (wired to the conversation's error bubble) and leave the
  existing draft untouched. `submitted` is now `Signal(object)` carrying a
  `UserSubmission` instead of `Signal(str)`. `_on_input_submitted` routes the
  full `UserSubmission` through to `AgentLoop.run()`/`inject_and_resume()`;
  pending-ask answers and slash commands reject image attachments (restoring
  the draft via `PromptInput.restore_draft()`) since neither accepts images;
  the conversation bubble shows `"text [N images]"` via a shared
  `_display_text()` helper. Heavy paste decode/encode stays on the GUI thread
  for v1 (TODO left in `prompt_input.py` to move it off-thread for large
  batches). Covered by `pyside_gui/tests/test_dispatch_and_submission.py` (8
  tests, Qt-free) plus `pyside_gui/tests/test_pending_ask.py` updated for the
  new module layout — full suite: 50 passed (up from 39 pre-stage-4), same 7
  pre-existing failures / 32 pre-existing errors (headless-Qt environment
  issues, confirmed present on the pre-stage-4 baseline too).
  Stage 5 landed (conversation-view rendering + error hardening):
  `pyside_gui/conversation.py` gained `append_user_message_with_images(text,
  image_paths)`, JSON-encoding the path list and delegating to a new JS
  function; `pyside_gui/resources/conversation.js` gained
  `appendUserMessageWithImages()`, which builds the same message-header/body
  markup as `appendMessage()` plus an `.image-gallery` of `<img
  class="sent-image-thumb">` tags — every path goes through `_escapeHtml()`
  before being placed in the DOM, so a crafted filename/path can't inject
  markup; `pyside_gui/resources/conversation.css` gained `.image-gallery`
  (flex row, wraps) and `.sent-image-thumb` (200x150 max, rounded corners,
  border, hover accent) rules. `pyside_gui/_dispatch.py` gained
  `_append_user_with_images(win, submission)`, used by both `dispatch_agent`
  (normal submit) and the inject-and-resume path in `on_input_submitted`: it
  resolves each attachment's file path via `ImageAssetStore.resolve_path()`
  (re-hashing the same bytes `AgentLoop._submission_content()` will hash),
  converts to a `file://` URL, and calls
  `append_user_message_with_images()`; on `AssetError` it shows
  `append_error("Couldn't load image preview: ...")` and falls back to the
  old `"text [N images]"` bubble instead of losing the message. `agent_work`
  now catches `AssetError` ahead of the general `Exception` handler and
  prefixes the surfaced message with `"Image error: "` for clarity (the
  general handler + `finally` block already restored input/showed
  `error_occurred` for every other failure path, confirmed by re-reading
  `_dispatch.py`). Text-only submissions are untouched — `append_user_message`
  and `appendMessage()` still handle them exactly as before. Verified via
  `conda run -n dagi python -m pytest pyside_gui/tests/test_dispatch_and_submission.py
  pyside_gui/tests/test_conversation_reasoning.py` (17 passed) plus `node
  --check conversation.js`; full `pyside_gui` suite still 50 passed / 7
  failed / 32 errors, same pre-existing headless-Qt baseline as stage 4.
  Stage 6 landed (integration verification and documentation): extended the
  four Stage 1-4 test files with the Section 10 gaps — wire payload tests
  (`tests/test_loop_image_integration.py`: exact PNG byte round-trip through
  the outgoing data URL, MIME-type correctness for PNG/JPEG, text-part-before-
  image-part ordering, multiple distinct images in one message, image-only
  messages, and text-only messages staying a plain string); a persistence
  round-trip test (store an image, seed a fresh `AgentLoop` from the prior
  loop's messages the way GUI resume does, materialize, and get back
  byte-identical PNG data with the original `ImageAttachment`/`UserSubmission`
  out of scope — modeling "source file deleted, clipboard cleared"); asset
  store gap tests (`tests/test_image_assets.py`: concurrent identical writes
  from 8 threads never corrupt the stored file — tolerating, per the module's
  own documented deferred-concurrency guarantee, that a losing writer may see
  a transient `PermissionError` on Windows `os.replace`; a symlinked asset
  path is rejected by `load()`, skipped if the sandbox disallows creating
  symlinks); history-label gap tests
  (`tests/test_image_config_and_labels.py`: image-only/mixed labels across
  `_content_label`, `_derive_title`, `build_turn_list`, and
  `build_copyable_messages` are asserted to never contain `{`/`}` or
  `sha256` — i.e. never a stringified dict or raw reference); and GUI routing
  tests (`pyside_gui/tests/test_dispatch_and_submission.py`:
  `_append_user_with_images` with a fake `win`/`_conversation`/`_config`
  verifying it calls `ImageAssetStore.store()` and produces `file:///` URLs,
  falls back to the error bubble + `"text [N images]"` text bubble on
  `AssetError` without losing the message, and leaves the text-only path
  byte-for-byte unchanged with no `.dagi/` directory created). Full targeted
  run: `conda run -n dagi python -m pytest tests/test_image_assets.py
  tests/test_loop_image_integration.py tests/test_image_config_and_labels.py
  pyside_gui/tests/test_dispatch_and_submission.py --noconftest -v` — 81
  passed, 1 skipped (symlink test, sandbox-dependent). README.md gained an
  "Image Input (PySide GUI)" section documenting the feature and
  `.dagi/config.yaml` `image_input:` knobs.
  **Not yet done:** the opt-in live endpoint smoke test against a real
  vision-capable model (plan Section 10's last item) has not been run — it
  requires a configured vision-capable model's credentials, which are not
  available in this environment. All automated verification is complete;
  only that manual/live step remains unrun.
