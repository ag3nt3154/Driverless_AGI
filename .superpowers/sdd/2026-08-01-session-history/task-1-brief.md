# Task 1: Add `rename_with_slug()` to SessionTracker

## Context
This is Task 1 of 5 in the session-history feature. It adds a method to
`SessionTracker` so that after the first user message, the session log file
can be renamed to include a human-readable slug. This is a pure
`agent/session.py` change with tests only — no other files.

The worktree is at: `C:\Users\alexr\Driverless_AGI\.claude\worktrees\session-history`
All work happens there.
Run tests with: `C:/Users/alexr/miniconda3/Scripts/conda.exe run -n dagi pytest`

## Global Constraints
- Functions ≤ 100 lines, cyclomatic complexity ≤ 8, positional params ≤ 5
- Line length ≤ 100 characters, files ≤ 500 lines
- All file paths Windows-compatible (Path objects, no hardcoded `/`)
- LF line endings in all written files

## Files
- Modify: `agent/session.py` (SessionTracker class)
- Test: `tests/test_session_tracker.py`

## What to implement

### 1. In `agent/session.py`, `SessionTracker.__init__`:
Add `self._renamed: bool = False` after the line:
```python
self._logs_dir.mkdir(parents=True, exist_ok=True)
```

### 2. Add two new methods to `SessionTracker` (after the `thread_id` property):

```python
def rename_with_slug(self, slug: str) -> None:
    """Rename the session file to include a human-readable slug.

    Idempotent — silently returns if already renamed or if this is a
    child tracker (no own file).
    """
    if self._renamed or self._parent is not None:
        return
    clean = self._sanitise_slug(slug)
    if not clean:
        return
    ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
    new_name = f"{ts}_{clean}_logs.jsonl"
    new_path = self._logs_dir / new_name
    try:
        self._path.rename(new_path)
    except OSError:
        return
    self._path = new_path
    self._renamed = True

@staticmethod
def _sanitise_slug(raw: str) -> str:
    """Lowercase, strip non-alnum/underscore, collapse runs, truncate."""
    import re
    slug = raw.lower().strip()
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug[:50]
```

### 3. In `tests/test_session_tracker.py`, add this import at the top if not present:
```python
import re
```

Then add a new test class `TestRenameWithSlug`:

```python
class TestRenameWithSlug:
    def test_renames_file_and_updates_path(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        old_path = tracker._path
        assert old_path.exists()

        tracker.rename_with_slug("fix_login_bug")

        assert not old_path.exists()
        assert tracker._path.exists()
        assert tracker._path.name.endswith("_fix_login_bug_logs.jsonl")
        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", tracker._path.name)

    def test_subsequent_writes_go_to_renamed_file(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("my_session")
        tracker.record_user("hello after rename")

        records = _read_jsonl(tracker._path)
        user_msgs = [r for r in records if r.get("entity") == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0]["content"] == "hello after rename"

    def test_second_rename_is_noop(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("first_name")
        path_after_first = tracker._path
        tracker.rename_with_slug("second_name")
        assert tracker._path == path_after_first

    def test_sanitises_slug(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        tracker.rename_with_slug("Hello World! @#$ Fix 123")
        assert "hello_world_fix_123" in tracker._path.name

    def test_truncates_long_slug(self, tmp_path):
        tracker = SessionTracker(model="m", logs_dir=tmp_path)
        long_slug = "a" * 100
        tracker.rename_with_slug(long_slug)
        parts = tracker._path.stem.split("_logs")[0]
        slug_part = "_".join(parts.split("_")[3:])  # skip YYYY, MM-DD, HH-MM-SS
        assert len(slug_part) <= 50

    def test_child_tracker_rename_is_noop(self, tmp_path):
        parent = SessionTracker(model="m", logs_dir=tmp_path)
        child = parent.child_tracker("sub1")
        old_parent_path = parent._path
        child.rename_with_slug("child_slug")
        assert parent._path == old_parent_path
```

## TDD sequence
1. Add the test class first (before implementing) — verify tests fail with AttributeError
2. Implement the two methods
3. Verify all 6 new tests pass
4. Run full `tests/test_session_tracker.py` to verify no regressions (expect 31 → 37 passing)

## Commit
```
git add agent/session.py tests/test_session_tracker.py
git commit -m "feat: add rename_with_slug() to SessionTracker"
```

## Report
Write your report to:
`C:\Users\alexr\Driverless_AGI\.claude\worktrees\session-history\.superpowers\sdd\2026-08-01-session-history\task-1-report.md`

Return: status (DONE/BLOCKED/NEEDS_CONTEXT), commits made, test summary (N passed), concerns.
