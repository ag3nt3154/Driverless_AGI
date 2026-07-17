# Session titles, Ctrl+R browser, /wd history — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give dagi sessions human-readable titled log files, a Ctrl+R browser to reopen and continue any past session, and a `/wd` picker of recently-used working directories.

**Architecture:** Title generation runs in `AgentLoop.run()` on a daemon thread behind a `session_titles` config flag, so every entry point benefits and piped subagents opt out. Session restore parsing lives in a pure `agent/session_restore.py` (unit-testable without Textual); the TUI wires it through a reusable `PickerModal`. `/wd` history is a small JSON MRU file with pure push/load helpers.

**Tech Stack:** Python 3.11, `openai` SDK, Textual 8.2.8, pytest. Conda env `dagi` (run everything as `conda run -n dagi ...`). On this machine conda lives at `C:\Users\alexr\anaconda3\Scripts\conda.exe`; if `conda` is not on PATH use the full path.

**Spec:** `docs/superpowers/specs/2026-07-17-session-ux-design.md`

---

## File Structure

**New files:**
- `agent/session_title.py` — `generate_title()`, `slugify()`, `fallback_slug()`. Title generation + filename slugging. No Textual, no tracker import.
- `agent/session_restore.py` — `SessionMeta`, `RestoredSession`, `list_sessions()`, `load_session()`. Pure JSONL parsing → browser rows + OpenAI-format message reconstruction.
- `tui/modals.py` — `PickerModal(ModalScreen[int | None])`. Generic Enter-to-select / Esc-to-cancel list picker, reused by the session browser and `/wd`.
- `tui/wd_history.py` — `push()`, `load()`. JSON MRU of working directories.
- `tests/test_session_title.py`, `tests/test_session_restore.py`, `tests/test_wd_history.py`.

**Modified files:**
- `agent/session.py` — `_io_lock`, init path uniquify, `set_title()`, `resume()` classmethod, `titled`.
- `agent/loop.py` — `AgentConfig.session_titles` field; `_maybe_generate_title()` + call site in `run()`.
- `agent/config_loader.py` — read `session_titles` from config, pass to `AgentConfig`.
- `tools/subagent_main.py` — set `session_titles = False` on the subagent config.
- `tui/app.py` — `ctrl+r` binding, `action_open_sessions`, restore flow, `_RestoredHolder`.
- `tui/commands.py` — `/sessions` dispatch, `_open_session_browser()`, `_set_wd()` extraction, `/wd` picker, `_cmd_compact` guard.
- `tui/utils.py` — `_SLASH_HELP` entries for `/sessions`.
- `hist.py` — glob `*.jsonl`, sort by mtime, capture + show title.
- `.dagi/skills/review-session/chunk_session.py` — glob `*.jsonl`.
- `.dagi/workflow/improve-yourself/run_test_task.py` — glob `*.jsonl`.
- `config.example.yaml`, `.gitignore`, `README.md`, `TODO.md`.

---

## Feature 1 — Session titles

### Task 1: Slug helpers in `agent/session_title.py`

**Files:**
- Create: `agent/session_title.py`
- Test: `tests/test_session_title.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_title.py
from agent.session_title import slugify, fallback_slug


def test_slugify_basic():
    assert slugify("Fix the auth bug") == "fix-the-auth-bug"


def test_slugify_strips_windows_invalid_chars():
    assert slugify('Add <config>: "stream" mode?') == "add-config-stream-mode"


def test_slugify_collapses_and_trims_dashes():
    assert slugify("  a   b  ") == "a-b"


def test_slugify_length_cap():
    out = slugify("word " * 40, max_len=20)
    assert len(out) <= 20
    assert not out.endswith("-")


def test_slugify_empty_is_untitled():
    assert slugify("!!!") == "untitled"
    assert slugify("") == "untitled"


def test_fallback_slug_first_words():
    msg = "Refactor the authentication module to use JWT tokens everywhere please"
    assert fallback_slug(msg) == "refactor-the-authentication-module-to-use"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.session_title'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent/session_title.py
"""Session title generation and filename slugging.

Pure helpers plus one LLM call. No Textual, no SessionTracker imports —
keeps this unit-testable and safe to import from AgentLoop.
"""
from __future__ import annotations

import re

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')      # Windows-invalid + control chars
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(title: str, max_len: int = 60) -> str:
    """Lowercase, filename-safe, dash-separated slug. Empty -> 'untitled'."""
    cleaned = _INVALID.sub(" ", title).lower()
    slug = _NON_SLUG.sub("-", cleaned).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "untitled"


def fallback_slug(first_message: str, words: int = 6) -> str:
    """Slug built from the first few words of the user's message."""
    head = " ".join(first_message.split()[:words])
    return slugify(head)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/session_title.py tests/test_session_title.py
git commit -m "feat: add slugify/fallback_slug for session titles"
```

---

### Task 2: `generate_title()` LLM call

**Files:**
- Modify: `agent/session_title.py`
- Test: `tests/test_session_title.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_session_title.py`)

```python
from agent.session_title import generate_title


class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content): self.choices = [_FakeChoice(content)]


class _FakeClient:
    def __init__(self, content): self._content = content; self.calls = []
    @property
    def chat(self): return self
    @property
    def completions(self): return self
    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletion(self._content)


def test_generate_title_returns_first_line_stripped():
    client = _FakeClient('  "Fix Auth Bug"\nextra\n')
    assert generate_title(client, "gpt-4o", "the login endpoint 500s") == "Fix Auth Bug"
    assert client.calls[0]["model"] == "gpt-4o"


def test_generate_title_empty_returns_empty_string():
    assert generate_title(_FakeClient(""), "gpt-4o", "hello") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py::test_generate_title_returns_first_line_stripped -v`
Expected: FAIL — `ImportError: cannot import name 'generate_title'`.

- [ ] **Step 3: Write minimal implementation** (append to `agent/session_title.py`)

```python
_TITLE_SYSTEM = (
    "Generate a concise 3-8 word title for this coding session, based on the "
    "user's first message. Return ONLY the title text — no quotes, no trailing "
    "punctuation, no preamble."
)


def generate_title(client, model: str, first_message: str) -> str:
    """One short LLM call. Returns a cleaned single-line title, or '' on empty."""
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _TITLE_SYSTEM},
            {"role": "user", "content": first_message[:2000]},
        ],
        max_tokens=100,
    )
    raw = (resp.choices[0].message.content or "").strip()
    if not raw:
        return ""
    first_line = raw.splitlines()[0].strip()
    return first_line.strip('"\'' ).strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/session_title.py tests/test_session_title.py
git commit -m "feat: add generate_title LLM call"
```

---

### Task 3: `SessionTracker` — lock, path uniquify, `set_title`

**Files:**
- Modify: `agent/session.py`
- Test: `tests/test_session_restore.py` (created here; reused in Task 8-9)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_session_restore.py
import json
import threading
from pathlib import Path

from agent.session import SessionTracker


def _read_records(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_same_second_collision_uniquifies(tmp_path, monkeypatch):
    # Force a fixed timestamp so two trackers would collide.
    import agent.session as sess

    class _FixedDT(sess.datetime):
        @classmethod
        def now(cls, tz=None): return sess.datetime(2026, 7, 17, 9, 0, 0, tzinfo=tz)

    monkeypatch.setattr(sess, "datetime", _FixedDT)
    a = SessionTracker(model="m", logs_dir=tmp_path)
    b = SessionTracker(model="m", logs_dir=tmp_path)
    assert a._path != b._path
    assert a._path.exists() and b._path.exists()


def test_set_title_renames_and_records(tmp_path):
    t = SessionTracker(model="m", logs_dir=tmp_path)
    old = t._path
    t.set_title("Fix Auth Bug", "fix-auth-bug")
    assert not old.exists()
    assert t._path.name.endswith("_fix-auth-bug.jsonl")
    assert t.titled is False  # set_title does not flip titled; the loop owns that flag
    recs = _read_records(t._path)
    assert any(r["type"] == "session_title" and r["title"] == "Fix Auth Bug" for r in recs)


def test_set_title_target_collision_suffixes(tmp_path):
    t = SessionTracker(model="m", logs_dir=tmp_path)
    ts = t._ts
    (tmp_path / f"{ts}_dup.jsonl").write_text("", encoding="utf-8")
    t.set_title("dup", "dup")
    assert t._path.name == f"{ts}_dup-2.jsonl"


def test_set_title_rename_failure_keeps_name(tmp_path, monkeypatch):
    t = SessionTracker(model="m", logs_dir=tmp_path)
    old = t._path
    monkeypatch.setattr(Path, "rename", lambda self, tgt: (_ for _ in ()).throw(OSError("locked")))
    t.set_title("x", "x")  # must not raise
    assert t._path == old
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py -v`
Expected: FAIL — `AttributeError: 'SessionTracker' object has no attribute 'set_title'` (and `titled`/`_ts`).

- [ ] **Step 3: Write minimal implementation**

In `agent/session.py`, add `import threading` at the top (alongside the existing `import json`).

Change `SessionTracker.__init__` (the block at lines 44-66). Replace:

```python
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
        self._path = self._logs_dir / f"session_{ts}.jsonl"

        self._write({
```

with:

```python
        self._io_lock = threading.Lock()
        self.titled = False

        self._logs_dir.mkdir(parents=True, exist_ok=True)
        ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
        self._ts = ts
        path = self._logs_dir / f"session_{ts}.jsonl"
        n = 2
        while path.exists():
            path = self._logs_dir / f"session_{ts}-{n}.jsonl"
            n += 1
        self._path = path

        self._write({
```

In `child_tracker` (lines 70-84), add these two attributes to the constructed child so attribute access is always safe:

```python
        child._path = None
        child._logs_dir = None
        child._io_lock = threading.Lock()   # unused (children delegate to root) but keeps attr safe
        child.titled = True                  # children never title
        child._ts = None
        return child
```

Wrap the root branch of `_write` (lines 236-241) in the lock:

```python
    def _write(self, record: dict) -> None:
        if self._parent is not None:
            self._parent._write(record)
        else:
            with self._io_lock:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```

Add `set_title` as a new method (place it after `finish`, before `_tag`):

```python
    def set_title(self, raw_title: str, slug: str) -> None:
        """Write a session_title record and rename the log to {ts}_{slug}.jsonl.

        Never raises: a rename failure (e.g. Windows file lock) leaves the old
        name in place. Does NOT flip self.titled — the AgentLoop owns that flag.
        """
        if self._parent is not None or self._path is None:
            return
        self._write({"type": "session_title", "title": raw_title, "timestamp": _now()})
        target = self._logs_dir / f"{self._ts}_{slug}.jsonl"
        n = 2
        while target.exists():
            target = self._logs_dir / f"{self._ts}_{slug}-{n}.jsonl"
            n += 1
        with self._io_lock:
            try:
                self._path.rename(target)
                self._path = target
            except OSError:
                pass  # keep old name; non-fatal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add agent/session.py tests/test_session_restore.py
git commit -m "feat: SessionTracker set_title + same-second collision fix"
```

---

### Task 4: `session_titles` config field + passthrough

**Files:**
- Modify: `agent/loop.py:178` (end of `AgentConfig`)
- Modify: `agent/config_loader.py:125` and the `AgentConfig(...)` construction (lines 136-156)
- Modify: `config.example.yaml`

- [ ] **Step 1: Add the field.** In `agent/loop.py`, after the `ask_user_timeout` field (line 178), add:

```python
    # Session titles: generate a one-line title after the first user message and
    # rename the log to {datetime}_{title}.jsonl. Piped subagents set this False.
    session_titles: bool = True
```

- [ ] **Step 2: Read it in `config_loader.py`.** After line 125 (`stream = bool(...)`), add:

```python
    session_titles = bool(entry.get("session_titles", raw.get("session_titles", True)))
```

Then in the `AgentConfig(...)` call (after `stream=stream,` at line 150), add:

```python
        session_titles=session_titles,
```

- [ ] **Step 3: Document it.** In `config.example.yaml`, near the `stream:` / `cache_prompt:` top-level keys, add:

```yaml
session_titles: true   # after the first message, generate a 1-line title and
                       # rename the session log to {datetime}_{title}.jsonl
```

- [ ] **Step 4: Verify config still loads**

Run: `conda run -n dagi python -c "from agent.config_loader import resolve_model_config; c = resolve_model_config(); print('session_titles =', c.session_titles)"`
Expected: prints `session_titles = True` (no traceback).

- [ ] **Step 5: Commit**

```bash
git add agent/loop.py agent/config_loader.py config.example.yaml
git commit -m "feat: add session_titles config flag"
```

---

### Task 5: Trigger title generation in `AgentLoop.run()` + subagent opt-out

**Files:**
- Modify: `agent/loop.py` (`run()` at line 378; new `_maybe_generate_title`)
- Modify: `tools/subagent_main.py:171`
- Test: `tests/test_session_title.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_session_title.py`)

```python
import time
from dataclasses import dataclass


@dataclass
class _StubTracker:
    _parent = None
    _path = "x.jsonl"
    titled = False
    applied = None
    def set_title(self, raw, slug): self.applied = (raw, slug)


def test_maybe_generate_title_applies(monkeypatch, tmp_path):
    from agent.loop import AgentLoop
    loop = AgentLoop.__new__(AgentLoop)          # bypass __init__
    loop.tracker = _StubTracker()

    class _Cfg: session_titles = True; model = "m"
    loop.config = _Cfg()
    loop.client = _FakeClient("My Title")

    loop._maybe_generate_title("do a thing")
    assert loop.tracker.titled is True           # flipped synchronously before thread
    for _ in range(50):
        if loop.tracker.applied: break
        time.sleep(0.02)
    assert loop.tracker.applied == ("My Title", "my-title")


def test_maybe_generate_title_skips_when_disabled():
    from agent.loop import AgentLoop
    loop = AgentLoop.__new__(AgentLoop)
    loop.tracker = _StubTracker()
    class _Cfg: session_titles = False; model = "m"
    loop.config = _Cfg()
    loop.client = _FakeClient("x")
    loop._maybe_generate_title("t")
    assert loop.tracker.titled is False
    assert loop.tracker.applied is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py::test_maybe_generate_title_applies -v`
Expected: FAIL — `AttributeError: 'AgentLoop' object has no attribute '_maybe_generate_title'`.

- [ ] **Step 3: Implement.** In `agent/loop.py`, add the method to `AgentLoop` (place it just before `def run` at line 366):

```python
    def _maybe_generate_title(self, first_message: str) -> None:
        """Fire-and-forget: title the session log from its first user message.

        Root trackers only, once per session, gated on config.session_titles.
        Runs on a daemon thread so the agent's first turn is never delayed.
        """
        if not getattr(self.config, "session_titles", True):
            return
        tracker = self.tracker
        if getattr(tracker, "_parent", None) is not None or getattr(tracker, "_path", None) is None:
            return
        if tracker.titled:
            return
        tracker.titled = True  # set before spawning so a second run() can't double-fire

        def _work() -> None:
            from agent.session_title import generate_title, slugify, fallback_slug
            try:
                raw = generate_title(self.client, self.config.model, first_message)
                if raw:
                    slug = slugify(raw)
                else:
                    raw = fallback_slug(first_message)
                    slug = raw
            except Exception:
                raw = fallback_slug(first_message)
                slug = raw
            try:
                tracker.set_title(raw, slug)
            except Exception:
                pass  # titling is best-effort, never fatal to the session

        threading.Thread(target=_work, daemon=True).start()
```

Then in `run()`, right after `self.tracker.record_user(task)` (line 378), add:

```python
        self._maybe_generate_title(task)
```

- [ ] **Step 4: Subagent opt-out.** In `tools/subagent_main.py`, after `typed_config.project_path = project_path` (line 171), add:

```python
    typed_config.session_titles = False   # piped subagents never spend a call on titling
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py -v`
Expected: PASS (12 passed).

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tools/subagent_main.py tests/test_session_title.py
git commit -m "feat: trigger session title generation on first message"
```

---

### Task 6: Update glob consumers to `*.jsonl` + title column in hist

**Files:**
- Modify: `hist.py` (lines 22, 49-52, 68-74, 90, 109-131)
- Modify: `.dagi/skills/review-session/chunk_session.py:80`
- Modify: `.dagi/workflow/improve-yourself/run_test_task.py:42,51`

- [ ] **Step 1: `hist.py` glob + mtime sort.** Line 22, replace:

```python
    if primary.exists() and any(primary.glob("session_*.jsonl")):
```
with:
```python
    if primary.exists() and any(primary.glob("*.jsonl")):
```

Line 90, replace:
```python
    files = sorted(logs_dir.glob("session_*.jsonl"), reverse=True)
```
with:
```python
    files = sorted(logs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
```

- [ ] **Step 2: `hist.py` capture the title record.** In `_parse_session`, add a `title` variable. Replace the parse loop body (lines 44-54) so it also reads `session_title`:

```python
    started_at: str | None = None
    model: str | None = None
    first_user_msg: str | None = None
    title: str | None = None

    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                t = record.get("type")
                if t == "session_start":
                    started_at = record.get("started_at")
                    model = record.get("model")
                elif t == "session_title":
                    title = (record.get("title") or "").strip() or None
                elif t == "message" and record.get("entity") == "user" and first_user_msg is None:
                    content = record.get("content") or ""
                    first_user_msg = content.replace("\n", " ").strip()
    except OSError:
        return None
```

(Note: the early `break` on "got everything" is removed — we now scan for the optional title too; files are small.)

Add `title` to the returned dict (lines 68-74):

```python
    return {
        "path": path,
        "started_at": started_at,
        "dt_str": dt_str,
        "model": model or "unknown",
        "title": title or "",
        "first_msg": first_user_msg or "(no user message)",
    }
```

- [ ] **Step 3: `hist.py` render the title column.** In `run()`, replace the column setup + rows (lines 109-131) with:

```python
    model_w = max(len(s["model"]) for s in sessions) if sessions else 7
    model_w = max(model_w, 5)
    title_w = 28
    msg_w = 40

    print(f"  {' # '}  {'Started (UTC)       '}  {'Model'.ljust(model_w)}  {'Title'.ljust(title_w)}  {'First message'}")
    print(f"  {'-'*3}  {'-'*20}  {'-'*model_w}  {'-'*title_w}  {'-'*msg_w}")

    for i, s in enumerate(sessions, 1):
        idx   = str(i).rjust(3)
        dt    = s["dt_str"].ljust(20)
        model = _truncate(s["model"], model_w).ljust(model_w)
        title = _truncate(s["title"] or "—", title_w).ljust(title_w)
        msg   = _truncate(s["first_msg"], msg_w)
        print(f"  {idx}  {dt}  {model}  {title}  {msg}")

    print()
```

- [ ] **Step 4: review-session + workflow globs.** In `.dagi/skills/review-session/chunk_session.py` line 80, replace `glob("session_*.jsonl")` with `glob("*.jsonl")`. In `.dagi/workflow/improve-yourself/run_test_task.py` lines 42 and 51, replace both `glob("session_*.jsonl")` with `glob("*.jsonl")`.

- [ ] **Step 5: Manual verification of hist**

Run: `conda run -n dagi python hist.py --n 5`
Expected: a table with a new **Title** column; existing untitled `session_*.jsonl` files show `—`; no traceback; newest sessions first.

- [ ] **Step 6: Commit**

```bash
git add hist.py .dagi/skills/review-session/chunk_session.py .dagi/workflow/improve-yourself/run_test_task.py
git commit -m "feat: hist title column; glob *.jsonl for renamed logs"
```

---

## Feature 2 — Session browser (Ctrl+R / /sessions)

### Task 7: `list_sessions()` in `agent/session_restore.py`

**Files:**
- Create: `agent/session_restore.py`
- Test: `tests/test_session_restore.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_session_restore.py`)

```python
from agent.session_restore import list_sessions, SessionMeta


def _write_session(path: Path, *, started="2026-07-17T09:00:00+00:00", model="m",
                   title=None, users=1):
    lines = [{"type": "session_start", "started_at": started, "model": model, "thread_id": "t1"}]
    if title:
        lines.append({"type": "session_title", "title": title})
    for i in range(users):
        lines.append({"type": "message", "entity": "user", "seq": i, "content": f"msg {i}"})
    path.write_text("\n".join(json.dumps(l) for l in lines) + "\n", encoding="utf-8")


def test_list_sessions_orders_newest_first(tmp_path):
    a = tmp_path / "2026-07-17_09-00-00_alpha.jsonl"; _write_session(a, title="alpha")
    b = tmp_path / "2026-07-17_10-00-00_beta.jsonl";  _write_session(b, title="beta")
    import os, time
    now = time.time()
    os.utime(a, (now - 100, now - 100)); os.utime(b, (now, now))
    metas = list_sessions(tmp_path)
    assert [m.title for m in metas] == ["beta", "alpha"]
    assert isinstance(metas[0], SessionMeta)


def test_list_sessions_title_precedence(tmp_path):
    # No title record -> falls back to filename slug, then first user message.
    p = tmp_path / "2026-07-17_09-00-00_from-name.jsonl"; _write_session(p, users=1)
    (meta,) = list_sessions(tmp_path)
    assert meta.title == "from-name"
    assert meta.message_count == 1
    assert meta.model == "m"


def test_list_sessions_cap(tmp_path):
    for i in range(5):
        _write_session(tmp_path / f"s{i}.jsonl", title=f"t{i}")
    assert len(list_sessions(tmp_path, limit=3)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py::test_list_sessions_orders_newest_first -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent.session_restore'`.

- [ ] **Step 3: Write minimal implementation**

```python
# agent/session_restore.py
"""Read session JSONL logs into browser rows and restorable message lists.

Pure parsing — no Textual, no LLM. Tolerant of malformed lines (skips them),
mirroring hist.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionMeta:
    path: Path
    started_at: str
    model: str
    title: str
    message_count: int


def _iter_records(path: Path):
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _title_from_filename(path: Path) -> str:
    """'2026-07-17_09-00-00_fix-bug.jsonl' -> 'fix-bug'; legacy names -> ''."""
    stem = path.stem
    if stem.startswith("session_"):
        return ""
    # ts prefix is 19 chars: YYYY-MM-DD_HH-MM-SS
    return stem[20:] if len(stem) > 20 and stem[19] == "_" else ""


def _meta_for(path: Path) -> SessionMeta | None:
    started = model = title_rec = first_user = None
    count = 0
    for rec in _iter_records(path):
        t = rec.get("type")
        if t == "session_start":
            started = rec.get("started_at"); model = rec.get("model")
        elif t == "session_title":
            title_rec = (rec.get("title") or "").strip() or None
        elif t == "message":
            count += 1
            if rec.get("entity") == "user" and first_user is None:
                first_user = (rec.get("content") or "").replace("\n", " ").strip()
    if started is None:
        return None
    title = title_rec or _title_from_filename(path) or (first_user or "(no message)")[:40]
    return SessionMeta(path=path, started_at=started, model=model or "unknown",
                       title=title, message_count=count)


def list_sessions(logs_dir: Path, limit: int = 50) -> list[SessionMeta]:
    logs_dir = Path(logs_dir)
    if not logs_dir.exists():
        return []
    files = sorted(logs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[SessionMeta] = []
    for f in files:
        m = _meta_for(f)
        if m is not None:
            out.append(m)
        if len(out) >= limit:
            break
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py -v`
Expected: PASS (all list_sessions + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add agent/session_restore.py tests/test_session_restore.py
git commit -m "feat: list_sessions for the session browser"
```

---

### Task 8: `load_session()` — raw + reconstruction

**Files:**
- Modify: `agent/session_restore.py`
- Test: `tests/test_session_restore.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from agent.session_restore import load_session, RestoredSession


def test_load_session_prefers_raw_messages(tmp_path):
    raw = [{"role": "system", "content": "s"},
           {"role": "user", "content": "hi"},
           {"role": "assistant", "content": "yo"}]
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"type": "session_start", "started_at": "2026-07-17T09:00:00+00:00", "model": "m", "thread_id": "t"},
        {"type": "message", "entity": "user", "seq": 0, "content": "hi"},
        {"type": "session_end", "raw_messages": raw},
    ]) + "\n", encoding="utf-8")
    r = load_session(p)
    assert isinstance(r, RestoredSession)
    assert r.messages == raw
    assert r.thread_id == "t"


def test_load_session_reconstructs_tool_calls(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"type": "session_start", "started_at": "2026-07-17T09:00:00+00:00", "model": "m", "thread_id": "t"},
        {"type": "message", "entity": "system", "seq": 0, "content": "SYS"},
        {"type": "message", "entity": "user", "seq": 1, "content": "read a file"},
        {"type": "message", "entity": "assistant", "seq": 2, "content": "ok",
         "input_tokens": 10, "output_tokens": 5, "cost": 0.001,
         "tool_calls": [{"name": "read", "description": "", "input": "{\"path\": \"x\"}", "result": "file contents"}]},
    ]) + "\n", encoding="utf-8")
    r = load_session(p)
    roles = [m["role"] for m in r.messages]
    assert roles == ["system", "user", "assistant", "tool"]
    asst = r.messages[2]
    tcid = asst["tool_calls"][0]["id"]
    assert r.messages[3]["tool_call_id"] == tcid
    assert r.messages[3]["content"] == "file contents"
    assert r.total_input == 10 and r.total_output == 5


def test_load_session_decodes_list_result(tmp_path):
    p = tmp_path / "s.jsonl"
    blocks = [{"type": "text", "text": "hello"}]
    p.write_text("\n".join(json.dumps(x) for x in [
        {"type": "session_start", "started_at": "2026-07-17T09:00:00+00:00", "model": "m", "thread_id": "t"},
        {"type": "message", "entity": "user", "seq": 0, "content": "go"},
        {"type": "message", "entity": "assistant", "seq": 1, "content": None,
         "tool_calls": [{"name": "read", "description": "", "input": "{}",
                         "result": "__list__:" + json.dumps(blocks)}]},
    ]) + "\n", encoding="utf-8")
    r = load_session(p)
    assert r.messages[-1]["content"] == blocks


def test_load_session_no_messages_raises(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps({"type": "session_start", "started_at": "x", "model": "m"}) + "\n",
                 encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load_session(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py::test_load_session_prefers_raw_messages -v`
Expected: FAIL — `ImportError: cannot import name 'load_session'`.

- [ ] **Step 3: Write minimal implementation** (append to `agent/session_restore.py`)

```python
@dataclass
class RestoredSession:
    meta: SessionMeta
    messages: list[dict]          # OpenAI-format, ready for AgentLoop initial_messages
    records: list[dict]           # raw "message" records, for replay rendering
    thread_id: str | None
    total_input: int = 0
    total_output: int = 0
    total_cost: float = 0.0


def _decode_result(result: str):
    """Undo the tracker's list encoding: '__list__:<json>' -> list; else str."""
    if isinstance(result, str) and result.startswith("__list__:"):
        try:
            return json.loads(result[len("__list__:"):])
        except json.JSONDecodeError:
            return result
    return result


def _reconstruct(message_records: list[dict]) -> list[dict]:
    """Rebuild OpenAI-format messages from tracker 'message' records."""
    msgs: list[dict] = []
    system_seen = False
    for rec in message_records:
        entity = rec.get("entity")
        content = rec.get("content")
        if entity == "system":
            if not system_seen:
                msgs.append({"role": "system", "content": content or ""})
                system_seen = True
        elif entity == "user":
            msgs.append({"role": "user", "content": content or ""})
        elif entity == "assistant":
            tool_calls = rec.get("tool_calls") or []
            if tool_calls:
                seq = rec.get("seq", len(msgs))
                calls, tools = [], []
                for i, tc in enumerate(tool_calls):
                    tcid = f"call_restored_{seq}_{i}"
                    calls.append({"id": tcid, "type": "function",
                                  "function": {"name": tc.get("name", ""),
                                               "arguments": tc.get("input", "{}")}})
                    tools.append({"role": "tool", "tool_call_id": tcid,
                                  "content": _decode_result(tc.get("result", ""))})
                msgs.append({"role": "assistant", "content": content, "tool_calls": calls})
                msgs.extend(tools)
            else:
                msgs.append({"role": "assistant", "content": content or ""})
    return msgs


def load_session(path: Path) -> RestoredSession:
    """Load a session log into a RestoredSession. Raises ValueError if nothing restorable."""
    path = Path(path)
    records = list(_iter_records(path))
    if not records:
        raise ValueError(f"No records in {path}")

    thread_id = None
    message_records: list[dict] = []
    raw_messages: list[dict] | None = None
    total_in = total_out = 0
    total_cost = 0.0
    for rec in records:
        t = rec.get("type")
        if t == "session_start":
            thread_id = rec.get("thread_id", thread_id)
        elif t == "message":
            message_records.append(rec)
            if rec.get("entity") == "assistant":
                total_in += rec.get("input_tokens") or 0
                total_out += rec.get("output_tokens") or 0
                total_cost += rec.get("cost") or 0.0
        elif t == "session_end" and rec.get("raw_messages"):
            raw_messages = rec["raw_messages"]

    messages = raw_messages if raw_messages is not None else _reconstruct(message_records)
    if not any(m.get("role") in ("user", "assistant") for m in messages):
        raise ValueError(f"No restorable conversation in {path}")

    meta = _meta_for(path) or SessionMeta(path, "", "unknown", path.stem, len(message_records))
    return RestoredSession(meta=meta, messages=messages, records=message_records,
                           thread_id=thread_id, total_input=total_in,
                           total_output=total_out, total_cost=total_cost)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/session_restore.py tests/test_session_restore.py
git commit -m "feat: load_session with raw + reconstructed message restore"
```

---

### Task 9: `SessionTracker.resume()`

**Files:**
- Modify: `agent/session.py`
- Test: `tests/test_session_restore.py`

- [ ] **Step 1: Write the failing test** (append)

```python
def test_resume_no_new_start_and_marker(tmp_path):
    t = SessionTracker(model="m", logs_dir=tmp_path)
    t.record_user("first")
    t.record_assistant("reply", None, [])
    path = t._path

    r = SessionTracker.resume(path, model="m")
    recs = _read_records(path)
    assert sum(1 for x in recs if x["type"] == "session_start") == 1
    assert any(x["type"] == "session_resume" for x in recs)
    # seq continues past the pre-resume max (0=user, 1=assistant -> next is 2)
    r.record_user("second")
    recs2 = _read_records(path)
    seqs = [x["seq"] for x in recs2 if x.get("type") == "message"]
    assert max(seqs) >= 2


def test_resume_titled_flag_from_filename(tmp_path):
    titled = tmp_path / "2026-07-17_09-00-00_already.jsonl"
    _write_session(titled, title="already")
    r = SessionTracker.resume(titled, model="m")
    assert r.titled is True

    legacy = tmp_path / "session_2026-07-17_09-00-00.jsonl"
    _write_session(legacy)
    r2 = SessionTracker.resume(legacy, model="m")
    assert r2.titled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py::test_resume_no_new_start_and_marker -v`
Expected: FAIL — `AttributeError: type object 'SessionTracker' has no attribute 'resume'`.

- [ ] **Step 3: Implement.** Add this classmethod to `SessionTracker` (place it after `child_tracker`, before the `thread_id` property). It reuses `MessageNode` and `_now`, both already in the module:

```python
    @classmethod
    def resume(cls, path: str | Path, model: str) -> "SessionTracker":
        """Bind a root tracker to an existing log file and continue appending.

        Writes a `session_resume` marker (not a new `session_start`), rebuilds
        in-memory message nodes so per-turn `finish()` totals stay correct, and
        continues `seq` from the file's max.
        """
        path = Path(path)
        self = object.__new__(cls)
        self._model = model
        self._logs_dir = path.parent
        self._path = path
        self._messages = []
        self._seq = 0
        self._started_at = datetime.now(timezone.utc)
        self._parent = None
        self._subagent_id = None
        self._depth = 0
        self._subagent_stats = []
        self._io_lock = threading.Lock()

        # Derive the timestamp prefix for any later rename, and the titled flag.
        stem = path.stem
        if stem.startswith("session_"):
            self._ts = stem[len("session_"):][:19]
            self.titled = False
        else:
            self._ts = stem[:19]
            self.titled = True

        thread_id = None
        max_seq = -1
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") == "session_start":
                thread_id = rec.get("thread_id", thread_id)
            elif rec.get("type") == "message":
                max_seq = max(max_seq, rec.get("seq", max_seq))
                self._messages.append(MessageNode(
                    id=rec.get("id", ""),
                    seq=rec.get("seq", 0),
                    entity=rec.get("entity", ""),
                    content=rec.get("content"),
                    model=rec.get("model"),
                    input_tokens=rec.get("input_tokens"),
                    output_tokens=rec.get("output_tokens"),
                    cost=rec.get("cost"),
                    tool_calls=[],   # not needed for finish() token/cost totals
                    timestamp=rec.get("timestamp", _now()),
                ))
        self._thread_id = thread_id or uuid4().hex
        self._seq = max_seq + 1
        self._write({"type": "session_resume", "timestamp": _now()})
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n dagi python -m pytest tests/test_session_restore.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/session.py tests/test_session_restore.py
git commit -m "feat: SessionTracker.resume for reopening sessions"
```

---

### Task 10: `PickerModal` in `tui/modals.py`

**Files:**
- Create: `tui/modals.py`

- [ ] **Step 1: Write the modal.**

```python
# tui/modals.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


class PickerModal(ModalScreen[int | None]):
    """Generic list picker. Dismisses with the selected index, or None on cancel."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    PickerModal { align: center middle; }
    PickerModal > Vertical {
        width: 90%; max-width: 120; height: auto; max-height: 80%;
        border: round $accent; background: $surface; padding: 1 2;
    }
    PickerModal .picker-title { text-style: bold; color: $accent; padding-bottom: 1; }
    PickerModal OptionList { height: auto; max-height: 20; }
    """

    def __init__(self, title: str, lines: list[str]) -> None:
        super().__init__()
        self._title = title
        self._lines = lines

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._title, classes="picker-title")
            yield OptionList(*[Option(line, id=str(i)) for i, line in enumerate(self._lines)])

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(int(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)
```

- [ ] **Step 2: Smoke-test the import**

Run: `conda run -n dagi python -c "from tui.modals import PickerModal; print(PickerModal)"`
Expected: prints the class, no traceback.

- [ ] **Step 3: Commit**

```bash
git add tui/modals.py
git commit -m "feat: reusable PickerModal for TUI list selection"
```

---

### Task 11: Wire the session browser into the TUI

**Files:**
- Modify: `tui/app.py` (BINDINGS at line 35-39; new `action_open_sessions`, `_open_session_browser`, `_restore_session`, `_RestoredHolder`)
- Modify: `tui/commands.py` (`_handle_slash` dispatch; `_cmd_compact` guard at line 155)
- Modify: `tui/utils.py` (`_SLASH_HELP`)

- [ ] **Step 1: Add the binding + help entry.** In `tui/app.py` `BINDINGS` (line 35), add:

```python
        ("ctrl+r", "open_sessions", "Sessions"),
```

In `tui/utils.py` `_SLASH_HELP`, add:

```python
    "/sessions": "Browse & reopen past sessions  (Ctrl+R)",
```

- [ ] **Step 2: Dispatch `/sessions`.** In `tui/commands.py` `_handle_slash`, add a branch next to `/hist` (line 72):

```python
        elif cmd == "/sessions":
            self.action_open_sessions()
```

- [ ] **Step 3: Add the holder + actions to `tui/app.py`.** Add this small class at module level (after the imports, before `class DagiApp`):

```python
class _RestoredHolder:
    """Stand-in for _active_loop after a restore: exposes only what _agent_work
    and _cmd_compact read (tracker, _messages, compact_tool)."""
    def __init__(self, tracker, messages):
        self.tracker = tracker
        self._messages = messages
        self.compact_tool = None
```

Add these methods to `DagiApp` (e.g. after `action_toggle_compose`):

```python
    def action_open_sessions(self) -> None:
        if self._worker and self._worker.is_alive():
            self.query_one(ConversationPane).append_info(
                "[yellow]⚠ Agent is running — press ESC to pause first, then Ctrl+R[/yellow]"
            )
            return
        from agent.session_restore import list_sessions
        logs_dir = self._project_path / ".dagi" / "logs"
        metas = list_sessions(logs_dir)
        if not metas:
            self.query_one(ConversationPane).append_info("[dim]No past sessions in this project.[/dim]")
            return
        lines = []
        for m in metas:
            dt = (m.started_at or "")[:16].replace("T", " ")
            lines.append(f"{dt} · {m.title} · {m.model} · {m.message_count} msgs")

        from .modals import PickerModal

        def _picked(idx: int | None) -> None:
            if idx is not None:
                self._restore_session(metas[idx].path)

        self.push_screen(PickerModal("Reopen a session", lines), _picked)

    def _restore_session(self, path) -> None:
        from agent.session_restore import load_session
        from agent.session import SessionTracker
        from .conversation import ConversationPane
        from .sidebar import Sidebar
        from .utils import _Stats, _breakdown
        conv = self.query_one(ConversationPane)
        try:
            restored = load_session(path)
        except ValueError as exc:
            conv.append_error(f"Cannot restore session: {exc}")
            return

        conv.clear()
        self._stats = _Stats()
        self._stats.input_tok = restored.total_input
        self._stats.output_tok = restored.total_output
        self._stats.cost = restored.total_cost or None

        tracker = SessionTracker.resume(path, model=self._config.model)
        self._active_loop = _RestoredHolder(tracker, list(restored.messages))
        self._current_loop_ref = []

        sidebar = self.query_one(Sidebar)
        sidebar.update_stats(self._stats.input_tok, self._stats.output_tok,
                             self._stats.cost, self._stats.thinking_tok)
        sidebar.update_context(_breakdown(restored.messages))

        m = restored.meta
        dt = (m.started_at or "")[:16].replace("T", " ")
        conv.append_info(
            f"[bold green]↺ Restored:[/bold green] {m.title} — {m.message_count} messages, "
            f"started {dt}, model {m.model} [dim](showing last 30)[/dim]"
        )
        self._replay_records(restored.records[-30:])

    def _replay_records(self, records: list) -> None:
        from rich.panel import Panel
        from rich.markdown import Markdown
        conv = self.query_one(ConversationPane)
        for rec in records:
            entity = rec.get("entity")
            content = rec.get("content") or ""
            if entity == "user":
                conv.write(Panel(content, title="[bold cyan]You[/bold cyan]",
                                 title_align="left", border_style="cyan", padding=(0, 1)))
            elif entity == "assistant":
                if content.strip():
                    conv.write(Markdown(content))
                for tc in rec.get("tool_calls") or []:
                    args = (tc.get("input") or "")[:80]
                    conv.append_info(f"  [dim cyan]▶ {tc.get('name', '?')}[/dim cyan] [dim]{args}[/dim]")
```

- [ ] **Step 4: Guard `_cmd_compact`.** In `tui/commands.py` `_cmd_compact` (line 155), change the guard:

```python
    def _cmd_compact(self) -> None:
        conv = self.query_one(ConversationPane)
        if self._active_loop is None or getattr(self._active_loop, "compact_tool", None) is None:
            conv.append_info("[dim]Nothing to compact — start a task first.[/dim]")
            return
```

- [ ] **Step 5: Import Panel/Markdown check.** `tui/app.py` already imports `Panel` and `Text` (line 6-7). Confirm `from rich.panel import Panel` is present at the top; the `_replay_records` local imports cover Markdown regardless.

- [ ] **Step 6: Manual verification in the running TUI**

Run: `conda run --no-capture-output -n dagi python tui.py`
Then:
1. Send a message (e.g. "say hi and stop"); wait for the turn to complete. The log should get titled (check `.dagi/logs/` for a `{datetime}_{slug}.jsonl` file).
2. Press `Ctrl+R` (and separately test `/sessions`). Expected: a modal lists sessions newest-first with date · title · model · msg count.
3. Select the session you just ran. Expected: pane clears, shows `↺ Restored: …`, replays the last messages (You panel + assistant markdown), sidebar shows non-zero tokens.
4. Type a follow-up message. Expected: agent continues with full context; new turns append to the **same** file (verify no new `session_start`, presence of a `session_resume` line: open the file).
5. Press `Ctrl+R` while the agent is running. Expected: the yellow "Agent is running — press ESC first" line, no modal.

- [ ] **Step 7: Commit**

```bash
git add tui/app.py tui/commands.py tui/utils.py
git commit -m "feat: Ctrl+R / /sessions browser to reopen past sessions"
```

---

## Feature 3 — /wd history

### Task 12: `tui/wd_history.py`

**Files:**
- Create: `tui/wd_history.py`
- Test: `tests/test_wd_history.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wd_history.py
import json
from pathlib import Path

from tui import wd_history


def test_push_prepends_and_dedupes(tmp_path):
    f = tmp_path / "wd.json"
    a = tmp_path / "a"; b = tmp_path / "b"
    a.mkdir(); b.mkdir()
    wd_history.push(a, f)
    wd_history.push(b, f)
    wd_history.push(a, f)   # move a to front
    assert wd_history.load(f) == [str(a), str(b)]


def test_push_case_insensitive_dedupe(tmp_path):
    f = tmp_path / "wd.json"
    d = tmp_path / "Dir"; d.mkdir()
    wd_history.push(d, f)
    wd_history.push(Path(str(d).upper()), f)   # same path, different case
    assert len(wd_history.load(f)) == 1


def test_push_truncates_to_max(tmp_path):
    f = tmp_path / "wd.json"
    for i in range(15):
        d = tmp_path / f"d{i}"; d.mkdir()
        wd_history.push(d, f)
    assert len(wd_history.load(f)) == 10


def test_load_corrupt_returns_empty(tmp_path):
    f = tmp_path / "wd.json"; f.write_text("{not json", encoding="utf-8")
    assert wd_history.load(f) == []


def test_load_prunes_dead_dirs(tmp_path):
    f = tmp_path / "wd.json"
    alive = tmp_path / "alive"; alive.mkdir()
    dead = tmp_path / "dead"
    f.write_text(json.dumps({"history": [str(dead), str(alive)]}), encoding="utf-8")
    assert wd_history.load(f) == [str(alive)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi python -m pytest tests/test_wd_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tui.wd_history'`.

- [ ] **Step 3: Write minimal implementation**

```python
# tui/wd_history.py
"""Persisted MRU list of working directories switched to via /wd.

Stored at DAGI_ROOT/.dagi/wd_history.json as {"history": ["<abs path>", ...]},
most-recent first. Pure functions; the TUI supplies the file path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent import DAGI_ROOT

MAX_ENTRIES = 10
DEFAULT_PATH = DAGI_ROOT / ".dagi" / "wd_history.json"


def _norm(p: str | Path) -> str:
    return os.path.normcase(str(Path(p).resolve()))


def load(path: Path = DEFAULT_PATH) -> list[str]:
    """Return the MRU list, dropping entries whose directory no longer exists."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        history = data.get("history", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return []
    return [h for h in history if Path(h).is_dir()]


def push(directory: str | Path, path: Path = DEFAULT_PATH) -> None:
    """Insert directory at the front (case-insensitive dedupe), cap, write atomically."""
    directory = str(Path(directory).resolve())
    existing = load(path)
    target = _norm(directory)
    deduped = [h for h in existing if _norm(h) != target]
    history = [directory] + deduped
    history = history[:MAX_ENTRIES]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"history": history}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi python -m pytest tests/test_wd_history.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add tui/wd_history.py tests/test_wd_history.py
git commit -m "feat: wd_history MRU storage for /wd"
```

---

### Task 13: `/wd` picker + history push

**Files:**
- Modify: `tui/commands.py` (`_cmd_wd` at lines 124-151)
- Modify: `.gitignore`

- [ ] **Step 1: Add `.dagi/wd_history.json` to `.gitignore`.** After the `.dagi/logs/*` line (line 191), add:

```
.dagi/wd_history.json
```

- [ ] **Step 2: Refactor `_cmd_wd` into show/set/picker.** Replace the whole `_cmd_wd` method (lines 124-151) with:

```python
    def _cmd_wd(self, arg: str | None) -> None:
        conv = self.query_one(ConversationPane)
        if arg:
            new = Path(arg).expanduser()
            if not new.is_absolute():
                new = self._project_path / new
            new = new.resolve()
            if not new.is_dir():
                conv.append_info(f"[red]Not a directory:[/red] {new}")
                return
            self._set_wd(new)
            return

        # No arg: show cwd, then offer a picker of recent directories.
        conv.append_info(f"[bold cyan]Working directory:[/bold cyan] {self._project_path}")
        from tui import wd_history
        current = str(self._project_path)
        entries = [h for h in wd_history.load() if Path(h).resolve() != self._project_path][:5]
        if not entries:
            return
        from .modals import PickerModal

        def _picked(idx: int | None) -> None:
            if idx is not None:
                self._set_wd(Path(entries[idx]))

        self.push_screen(PickerModal("Recent working directories", entries), _picked)

    def _set_wd(self, new: Path) -> None:
        conv = self.query_one(ConversationPane)
        self._project_path = new
        from agent.config_loader import get_model_display_name, resolve_model_config
        self._config = resolve_model_config(self._model_id, project_path=new)
        resolved_id = getattr(self._config, 'model_id', '') or self._model_id or ''
        if resolved_id and resolved_id != self._model_id:
            self._model_id = resolved_id
            self._model_name = get_model_display_name(resolved_id)
        sidebar = self.query_one(Sidebar)
        sidebar.update_model(self._model_name)
        sidebar._context_window = self._config.context_window
        sidebar._reserve_tokens = self._config.reserve_tokens
        self._active_loop = None
        self._load_maps()
        sidebar.set_project_path(new)
        from tui import wd_history
        wd_history.push(new)
        conv.append_info(f"[green]✓ Working directory →[/green] {new}")
```

- [ ] **Step 3: Manual verification in the running TUI**

Run: `conda run --no-capture-output -n dagi python tui.py`
Then:
1. `/wd C:\Users\alexr\Driverless_AGI` then `/wd C:\Users\alexr` (two real dirs). Each prints `✓ Working directory →`.
2. `/wd` with no arg. Expected: prints the current dir, then a modal listing the *other* recent dir(s) — current dir excluded. Select one → switches, prints `✓`.
3. Confirm `.dagi/wd_history.json` exists at the dagi root and holds absolute paths, newest first.
4. `/wd` with empty history (fresh checkout / delete the json first): prints only the current dir line, no modal.

- [ ] **Step 4: Commit**

```bash
git add tui/commands.py .gitignore
git commit -m "feat: /wd recent-directory picker"
```

---

## Task 14: Docs — README + TODO

**Files:**
- Modify: `README.md`
- Modify: `TODO.md`

- [ ] **Step 1: README slash-command table.** In the Slash Command Reference table (around line 302), update `/wd` and add `/sessions`:

```markdown
| `/wd [path]` | Show cwd + a picker of recent directories, or change to `path` |
| `/sessions` | Browse and reopen past sessions (also `Ctrl+R`) |
```

Also add `/sessions` to the inline slash-command list (line 127) and the keyboard-shortcuts list (add `Ctrl+R — open the session browser`).

- [ ] **Step 2: README Session Logs section.** In the "Session Logs" section (around line 639), replace the naming sentence:

```markdown
Every run is logged to `.dagi/logs/{datetime}_{title}.jsonl`. After the first
message, dagi generates a one-line title with the session's own model and renames
the file (set `session_titles: false` in `config.yaml` to keep plain
`session_{timestamp}.jsonl` names). Reopen any past session with `Ctrl+R` or
`/sessions` — its full context loads back into the agent and continuing the
conversation appends to the same file.
```

- [ ] **Step 3: TODO.md.** Mark these three features done (or add a "Done" entry if that's the file's convention — match the existing format in `TODO.md`):

```markdown
- [x] Session log titles: {datetime}_{title}.jsonl generated after first message
- [x] Ctrl+R / /sessions browser to reopen past sessions
- [x] /wd recent-directory picker
```

- [ ] **Step 4: Full test sweep**

Run: `conda run -n dagi python -m pytest tests/test_session_title.py tests/test_session_restore.py tests/test_wd_history.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add README.md TODO.md
git commit -m "docs: session titles, Ctrl+R browser, /wd picker"
```

---

## Self-Review Notes (for the implementer)

- **Reconstruction uses full (untruncated) tool results** from the tracker (`full_str`), not the possibly-truncated in-context version. For a resumed crashed session this can re-inflate context slightly; the normal path (`session_end.raw_messages`) is byte-exact and is preferred whenever present. This is intentional per the spec.
- **`titled` semantics:** `set_title` does NOT flip `titled` — `AgentLoop._maybe_generate_title` sets it before spawning the thread (prevents double-fire). `resume()` sets it from the filename. Keep these three in sync if you change the flag's meaning.
- **Ctrl+R capture risk:** if a terminal/Textual build swallows `ctrl+r` inside the focused `PromptInput`, `/sessions` is the always-working fallback. Verify the binding fires in Step 6 of Task 11; if it doesn't, that's a keybinding note, not a logic bug.
- **Model on restore:** restoring does NOT change the active model (matches `/model` mid-session semantics). The restored session's original model is shown in the browser row only.
