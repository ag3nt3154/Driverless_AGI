# Session titles, session browser (Ctrl+R), `/wd` history — Design

## Problem

Three UX gaps in dagi's session handling:

1. **Session logs are anonymous.** Files are named `session_{timestamp}.jsonl`; the only way to
   know what a session was about is to open it or run `/hist`. Two sessions started in the same
   second even collide into a single file (observed: doubled `session_start` records in
   `.dagi/logs/session_2026-07-16_03-38-36.jsonl`).
2. **Past sessions cannot be reopened.** `/hist` lists them read-only. There is no way to load an
   old conversation back into the TUI and continue it with full context.
3. **`/wd` has no memory.** Switching between frequently used project directories means retyping
   full paths every time.

## Goal

1. After the first user message of a session, generate a one-line title with the session's own
   model and rename the log to `{datetime}_{title-slug}.jsonl`.
2. `Ctrl+R` (or `/sessions`) opens a session browser; picking a session loads its full context
   into the agent and replays a compact rendering into the conversation pane; continuing the
   conversation appends to the *same* log file.
3. `/wd` with no argument shows the current working directory plus a picker of the last 5
   directories previously switched to via `/wd`; selecting one switches to it.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| Browser keybinding | `Ctrl+R` — `Ctrl+H` is impossible: terminals send `\x08`, which Textual's parser maps to `backspace` (`textual/_ansi_sequences.py`), so a `ctrl+h` binding never fires. `/sessions` slash command as discoverable fallback. |
| Restore rendering | Compact replay: last 30 records; tool calls as one-liners; earlier messages loaded into context but not rendered. |
| Filename scheme | `{datetime}_{title}.jsonl` exactly as specified; the three `session_*.jsonl` glob consumers are updated to `*.jsonl`. |
| Title model | The session's configured model — no new model config. |
| Resume logging | Same file: a `session_resume` marker record, then normal appends. |
| Architecture | Core-integrated: title generation in `AgentLoop` behind a `session_titles` config flag so every entry point (TUI, `main.py`, Telegram) benefits; piped subagents opt out. |
| `/wd` history contents | Targets only — record just the directories explicitly `/wd`-ed into (the departed directory is *not* pushed). |

## Feature 1 — Session titles

### Trigger (`agent/loop.py`)

In `AgentLoop.run()`, immediately after `self.tracker.record_user(task)` (loop.py:378): if

- the tracker is a root tracker (`_parent is None` and it owns a `_path`), and
- `self.tracker.titled` is `False` (new flag), and
- `self.config.session_titles` is `True` (new `AgentConfig` field, default `True`)

spawn a daemon thread that generates and applies the title. The main loop proceeds immediately —
the first turn is never delayed. `tracker.titled` is set `True` before spawning (not after) so a
second `run()` on the same tracker cannot double-fire.

`tools/subagent_main.py` sets `session_titles=False` on the config it builds — piped subagents
(explore_files, web_research, worker, review, …) never spend a call on titling. Child trackers
(in-process subagents) are excluded by the root-tracker check.

### Title generation (`agent/session_title.py`, new)

```python
def generate_title(client, model: str, first_message: str) -> str   # LLM call
def slugify(title: str, max_len: int = 60) -> str                   # filename-safe slug
def fallback_slug(first_message: str) -> str                        # first ~6 words, slugified
```

- `generate_title`: one `chat.completions.create` — system prompt: "Generate a concise 3–8 word
  title for this coding session from the user's first message. Return only the title — no quotes,
  no trailing punctuation." User content: first message truncated to ~2000 chars. `max_tokens`
  generous (≈100) to survive reasoning-model preambles; result stripped to a single line.
- `slugify`: lowercase; whitespace → `-`; strip Windows-invalid chars (`<>:"/\|?*`), control chars
  and dots; collapse repeated `-`; trim to `max_len`; empty result → `"untitled"`.
- Any exception or empty title from the LLM → `fallback_slug(first_message)` — titles work offline.
- The pre-slug title is recorded in the log as `{"type": "session_title", "title": <raw>,
  "timestamp": ...}` so UIs can show the human-readable form.

### Rename (`agent/session.py`)

`SessionTracker` changes:

- `__init__` gains `self._io_lock = threading.Lock()` and `self.titled = False`. Every `_write()`
  on a root tracker acquires the lock (child trackers delegate to root as today).
- **Collision fix (in passing):** `__init__` uniquifies the path — if `session_{ts}.jsonl` exists,
  try `session_{ts}-2.jsonl`, `-3`, … Two sessions in the same second no longer share a file.
- New `set_title(self, raw_title: str, slug: str) -> None`:
  1. Writes the `session_title` record (normal `_write`).
  2. Under `_io_lock`, renames `self._path` → `self._logs_dir / f"{ts}_{slug}.jsonl"` and updates
     `self._path`. `ts` is the timestamp string already embedded in the current filename (for a
     fresh tracker that is its start time; for a resumed legacy `session_{ts}.jsonl` it is the
     *original* session's start, so the file keeps its historical date). Target-exists → uniquify
     with `-2` suffix. Any `OSError` (e.g. file held open by another process on Windows) → keep
     the old name, no exception propagates.

The lock closes the race between a rename and an in-flight append (Windows cannot rename an open
file; writes are open-append-close, so the lock is held only for microseconds).

### Consumers of the old naming

All updated from `glob("session_*.jsonl")` to `glob("*.jsonl")`, sorted by `st_mtime` (filename
sort would order `2026-…` names before legacy `session_…` names):

- `hist.py` — `_find_logs_dir()` (line 22) and `run()` (line 90). `_parse_session()` additionally
  captures the `session_title` record; the table gains a Title column (falls back to first user
  message as today).
- `.dagi/skills/review-session/chunk_session.py` (line 80).
- `.dagi/workflow/improve-yourself/run_test_task.py` (lines 42, 51 — before/after set diff, so
  only the glob pattern changes).
- Archived UIs (`archive/app.py`, `archive/nicegui_app/history.py`) are deprecated — untouched.

### Config

- `AgentConfig.session_titles: bool = True`; `config_loader.py` reads optional top-level
  `session_titles:` from `config.yaml` / project config, same passthrough pattern as existing keys.
- Documented in `config.example.yaml`.

## Feature 2 — Session browser (Ctrl+R / `/sessions`)

### Entry points (`tui/app.py`, `tui/commands.py`)

- `BINDINGS` gains `("ctrl+r", "open_sessions", "Sessions")`. `Ctrl+R` is unbound in both
  `TextArea` (checked: 8.2.8 binds ctrl+a/e/w/x/c/v/u/k/z/y, f6, f7) and the app.
- New slash command `/sessions` → same action. Added to `_SLASH_HELP` and README.
- Guard: while the agent worker thread is alive, both show
  `⚠ Agent is running — press ESC to pause first` and return (same pattern as `/clear`).

### Parsing (`agent/session_restore.py`, new — pure, no Textual imports)

```python
@dataclass
class SessionMeta:      # one browser row
    path: Path
    started_at: str     # ISO
    model: str
    title: str          # session_title record → filename slug → first user message (truncated)
    message_count: int  # count of "message" records

@dataclass
class RestoredSession:
    meta: SessionMeta
    messages: list[dict]        # OpenAI-format, ready for AgentLoop initial_messages
    records: list[dict]         # raw "message" records, for replay rendering + tracker rebuild
    thread_id: str | None

def list_sessions(logs_dir: Path, limit: int = 50) -> list[SessionMeta]
def load_session(path: Path) -> RestoredSession        # raises ValueError if nothing restorable
```

- `list_sessions`: newest-first by `st_mtime`, capped at `limit`; per file one line-by-line scan
  collecting `session_start`, the last `session_title`, the first user message, and the
  `message_count` (counting requires reading every line — lines are cheap, and files are scanned
  once per picker open). Unparseable files are skipped, malformed lines ignored (same tolerance
  as `hist.py`).
- `load_session` context reconstruction, in priority order:
  1. **Last `session_end` record with `raw_messages`** — byte-exact context (the TUI calls
     `finish()` after every turn, so any normally-completed turn leaves one).
  2. **Fallback — rebuild from `message` records** (crashed/killed sessions): `system` → role
     system (first only; per-run wiki-context system messages are re-added by the next `run()`
     anyway); `user` → role user; `assistant` → role assistant with `content`, plus synthesized
     `tool_calls` (`id=f"call_restored_{seq}_{i}"`, function name/arguments from the
     `ToolCallRecord`) followed by matching `role=tool` messages (`tool_call_id` matching, result
     with the `"__list__:<json>"` encoding decoded back to structured content).
  3. Neither yields a non-system message → `ValueError`.

### Resuming the tracker (`agent/session.py`)

New classmethod `SessionTracker.resume(path: Path, model: str) -> SessionTracker`:

- Binds a root tracker to the existing file — **no** `session_start` record; instead writes
  `{"type": "session_resume", "timestamp": ...}`.
- `thread_id` from the file's first `session_start` (fresh uuid if absent); `_started_at` = now;
  the original filename timestamp prefix is preserved (title/datetime stay stable).
- Rebuilds `self._messages` as `MessageNode`s from the file's `message` records (they are
  `asdict()` output, so they round-trip; unknown/missing fields default) and continues `_seq`
  from the max seen — per-turn `finish()` totals remain correct across the resume.
- `titled` = `True` when the filename already carries a title (i.e. doesn't match the
  `session_{ts}` pattern); a resumed-but-untitled session may still get titled on its next turn.

### TUI restore flow (`tui/app.py` + `tui/modals.py`)

- New `PickerModal(ModalScreen[int | None])` in `tui/modals.py` — generic: takes a title string
  and a list of Rich-markup option lines, shows an `OptionList`; Enter → selected index,
  Esc → `None`. Reused by `/wd` (Feature 3).
- Browser rows: `2026-07-17 14:33 · fix-auth-bug · claude-opus-openrouter · 42 msgs`.
- On selection:
  1. `load_session(path)`; on `ValueError` → red info line, current context untouched.
  2. `conv.clear()`; reset `_stats`; `self._active_loop = _RestoredHolder(tracker=
     SessionTracker.resume(path, model), _messages=restored.messages, compact_tool=None)` —
     a tiny dataclass exposing exactly the two attributes `_agent_work` reads
     (`tui/app.py:188-190`). The next submitted message builds a real `AgentLoop` with
     `initial_messages=` and `_tracker=` as any multi-turn continuation does.
  3. `_cmd_compact` gains a `getattr(loop, "compact_tool", None) is None` → "start a task first"
     guard (currently it would crash on the holder).
  4. Sidebar: `update_stats` seeded from summed `input_tokens`/`output_tokens`/`cost` of the
     restored assistant records; `update_context(_breakdown(restored.messages))`.
  5. **Compact replay** into the conversation pane: header
     `↺ Restored: <title> — <N> messages, started <dt>, model <model> (showing last 30)`, then the
     last 30 `message` records rendered: user → cyan panel (existing style), assistant content →
     `Markdown`, each tool call → one dim line `▶ <name> <args truncated to 80>`; system records
     and empty contents skipped.
- The **active model is not changed** by a restore — context carries over to whatever model is
  currently selected, exactly like `/model` mid-session. The restored session's original model is
  visible in the browser row.

## Feature 3 — `/wd` history

### Storage (`tui/wd_history.py`, new — pure functions)

- File: `DAGI_ROOT/.dagi/wd_history.json`, shape `{"history": ["<abs path>", ...]}`, MRU order,
  max 10 entries stored (5 shown). Added to `.gitignore` (alongside the existing `.dagi/logs/*`
  entries).
- `push(path)`: insert at front; dedupe case-insensitively via `os.path.normcase` on the resolved
  path; truncate to 10; write atomically (write temp + replace).
- `load()`: missing or corrupt JSON → `[]` (rewritten on next push). Entries whose directory no
  longer exists are dropped on load and pruned on the next write.
- **Targets only**: `push` is called exactly once per successful directory change, with the *new*
  path. The departed directory is never recorded (per user decision).

### UX (`tui/commands.py`)

- The path-changing body of `_cmd_wd` (commands.py:129-151) is extracted to `_set_wd(new: Path)`;
  `_cmd_wd(arg)` validates/resolves then delegates; on success calls `wd_history.push(new)`.
- `/wd` (no arg): print `Working directory: <cwd>` (unchanged), then load history, drop the
  current cwd, take 5. Non-empty → `PickerModal("Recent working directories", entries)`;
  selection → `_set_wd(Path(entry))`; Esc → nothing. Empty history → info line only, no modal.
- `/wd <path>`: unchanged behavior + history push.

## Files touched

**New:** `agent/session_title.py` · `agent/session_restore.py` · `tui/modals.py` ·
`tui/wd_history.py` · `tests/test_session_title.py` · `tests/test_session_restore.py` ·
`tests/test_wd_history.py`

**Modified:** `agent/session.py` · `agent/loop.py` · `agent/config_loader.py` ·
`tools/subagent_main.py` · `tui/app.py` · `tui/commands.py` · `tui/utils.py` (`_SLASH_HELP`) ·
`hist.py` · `.dagi/skills/review-session/chunk_session.py` ·
`.dagi/workflow/improve-yourself/run_test_task.py` · `config.example.yaml` · `.gitignore` ·
`README.md` · `TODO.md`

## Error handling

| Failure | Behavior |
|---|---|
| Title LLM call fails / empty / offline | `fallback_slug(first_message)` — session still titled |
| Rename fails (file locked, permissions) | Keep `session_{ts}.jsonl` name; no exception; session unaffected |
| Restore: malformed JSONL lines | Skipped (matches `hist.py` tolerance) |
| Restore: no restorable messages | Red info line; current context untouched |
| `/compact` right after restore, before first turn | "start a task first" info line (holder has no `compact_tool`) |
| `wd_history.json` corrupt | Treated as empty, rewritten on next push |
| History entry's directory deleted | Dropped from picker; pruned on next write |
| Ctrl+R / `/sessions` / restore while agent running | Warning line, no action (same as `/clear`) |

## Out of scope

- Restoring plan-mode state, pause state, or the active model from a log.
- Cross-project session browsing (the browser lists the *current* project's `.dagi/logs` only;
  switch with `/wd` first to browse another project's sessions).
- Deleting/archiving sessions from the browser.
- Kitty-keyboard-protocol work to make literal `Ctrl+H` detectable.

## Testing

Pure-logic unit tests (pytest, no Textual):

- `test_session_title.py`: slugify edge cases (Windows-invalid chars, length, empty → untitled);
  fallback_slug; `set_title` renames + updates `_path` + writes `session_title` record;
  rename-target collision → `-2`; rename failure swallowed; init-path uniquify (same-second
  collision); concurrent `_write`/`set_title` under the lock.
- `test_session_restore.py`: `load_session` prefers last `raw_messages`; reconstruction fallback
  (synthesized tool_call ids match tool messages; `__list__:` decoding); `list_sessions` ordering,
  cap, title precedence (record → filename → first message); `SessionTracker.resume` — no new
  `session_start`, `session_resume` marker present, `_seq` continues, `finish()` totals include
  pre-resume nodes.
- `test_wd_history.py`: push/dedupe (case-insensitive)/truncate; corrupt file → empty;
  dead-directory pruning; atomic write leaves valid JSON.

TUI wiring (modal interaction, ctrl+r binding, replay rendering, sidebar seeding) is verified
manually in the running TUI — consistent with how existing TUI features are validated in this
repo. `AgentLoop` title-trigger gating (root-only, once-only, flag-off) gets a unit test with a
stubbed client.

## Interaction with concurrent work

`docs/superpowers/specs/2026-07-17-dagi-streaming-design.md` (same-day spec) changes only the
API-call internals in `agent/loop.py` (`_call_api` streaming) and leaves tool dispatch,
`tracker.record_*`, keybindings, and slash commands untouched — no structural conflict with this
design. If both land, the `loop.py` merge is textual, not semantic.
