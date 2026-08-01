 agent/session.py              | 32 ++++++++++++++++++++++++++
 tests/test_session_tracker.py | 52 +++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 84 insertions(+)
c93bc93 feat: add rename_with_slug() to SessionTracker
---
diff --git a/agent/session.py b/agent/session.py
index e40bb99..39ab21e 100644
--- a/agent/session.py
+++ b/agent/session.py
@@ -48,20 +48,21 @@ class SessionTracker:
         self._seq = 0
         self._started_at = datetime.now(timezone.utc)
 
         # Root-only attributes
         self._parent: SessionTracker | None = None
         self._subagent_id: str | None = None
         self._depth: int = 0
         self._subagent_stats: list[dict] = []
 
         self._logs_dir.mkdir(parents=True, exist_ok=True)
+        self._renamed: bool = False
         ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
         self._path = self._logs_dir / f"session_{ts}.jsonl"
 
         self._write({
             "type": "session_start",
             "thread_id": self._thread_id,
             "model": self._model,
             "started_at": self._started_at.isoformat(),
         })
 
@@ -74,26 +75,57 @@ class SessionTracker:
         child._thread_id = self._thread_id
         child._messages = []
         child._seq = 0
         child._started_at = datetime.now(timezone.utc)
         child._parent = self
         child._subagent_id = subagent_id
         child._depth = self._depth + 1
         child._subagent_stats = []  # unused for children but keeps attr access safe
         child._path = None
         child._logs_dir = None
+        child._renamed = False
         return child
 
     @property
     def thread_id(self) -> str:
         return self._thread_id
 
+    def rename_with_slug(self, slug: str) -> None:
+        """Rename the session file to include a human-readable slug.
+
+        Idempotent — silently returns if already renamed or if this is a
+        child tracker (no own file).
+        """
+        if self._renamed or self._parent is not None:
+            return
+        clean = self._sanitise_slug(slug)
+        if not clean:
+            return
+        ts = self._started_at.strftime("%Y-%m-%d_%H-%M-%S")
+        new_name = f"{ts}_{clean}_logs.jsonl"
+        new_path = self._logs_dir / new_name
+        try:
+            self._path.rename(new_path)
+        except OSError:
+            return
+        self._path = new_path
+        self._renamed = True
+
+    @staticmethod
+    def _sanitise_slug(raw: str) -> str:
+        """Lowercase, strip non-alnum/underscore, collapse runs, truncate."""
+        import re
+        slug = raw.lower().strip()
+        slug = re.sub(r"[^a-z0-9_]+", "_", slug)
+        slug = re.sub(r"_+", "_", slug).strip("_")
+        return slug[:50]
+
     # ------------------------------------------------------------------ events
 
     def record_system(self, content: str) -> None:
         node = self._add(entity="system", content=content)
         self._write(self._tag({"type": "message", **asdict(node)}))
 
     def record_user(self, content: str) -> None:
         node = self._add(entity="user", content=content)
         self._write(self._tag({"type": "message", **asdict(node)}))
 
diff --git a/tests/test_session_tracker.py b/tests/test_session_tracker.py
index ffc25c4..1450fe0 100644
--- a/tests/test_session_tracker.py
+++ b/tests/test_session_tracker.py
@@ -1,14 +1,15 @@
 """tests/test_session_tracker.py — Unit tests for SessionTracker."""
 from __future__ import annotations
 
 import json
+import re
 from types import SimpleNamespace
 
 from agent.session import SessionTracker
 
 
 def _read_jsonl(path):
     with open(path, encoding="utf-8") as fh:
         return [json.loads(line) for line in fh if line.strip()]
 
 
@@ -160,10 +161,61 @@ class TestFinish:
         usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3, cost=None)
         child.record_assistant("child result", usage, tool_calls=[])
         child.finish()
 
         parent.finish()
 
         records = _read_jsonl(parent._path)
         end = [r for r in records if r["type"] == "session_end"][0]
         assert end["total_input_tokens"] == 7
         assert end["total_output_tokens"] == 3
+
+
+class TestRenameWithSlug:
+    def test_renames_file_and_updates_path(self, tmp_path):
+        tracker = SessionTracker(model="m", logs_dir=tmp_path)
+        old_path = tracker._path
+        assert old_path.exists()
+
+        tracker.rename_with_slug("fix_login_bug")
+
+        assert not old_path.exists()
+        assert tracker._path.exists()
+        assert tracker._path.name.endswith("_fix_login_bug_logs.jsonl")
+        assert re.match(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_", tracker._path.name)
+
+    def test_subsequent_writes_go_to_renamed_file(self, tmp_path):
+        tracker = SessionTracker(model="m", logs_dir=tmp_path)
+        tracker.rename_with_slug("my_session")
+        tracker.record_user("hello after rename")
+
+        records = _read_jsonl(tracker._path)
+        user_msgs = [r for r in records if r.get("entity") == "user"]
+        assert len(user_msgs) == 1
+        assert user_msgs[0]["content"] == "hello after rename"
+
+    def test_second_rename_is_noop(self, tmp_path):
+        tracker = SessionTracker(model="m", logs_dir=tmp_path)
+        tracker.rename_with_slug("first_name")
+        path_after_first = tracker._path
+        tracker.rename_with_slug("second_name")
+        assert tracker._path == path_after_first
+
+    def test_sanitises_slug(self, tmp_path):
+        tracker = SessionTracker(model="m", logs_dir=tmp_path)
+        tracker.rename_with_slug("Hello World! @#$ Fix 123")
+        assert "hello_world_fix_123" in tracker._path.name
+
+    def test_truncates_long_slug(self, tmp_path):
+        tracker = SessionTracker(model="m", logs_dir=tmp_path)
+        long_slug = "a" * 100
+        tracker.rename_with_slug(long_slug)
+        parts = tracker._path.stem.split("_logs")[0]
+        slug_part = "_".join(parts.split("_")[3:])  # skip YYYY, MM-DD, HH-MM-SS
+        assert len(slug_part) <= 50
+
+    def test_child_tracker_rename_is_noop(self, tmp_path):
+        parent = SessionTracker(model="m", logs_dir=tmp_path)
+        child = parent.child_tracker("sub1")
+        old_parent_path = parent._path
+        child.rename_with_slug("child_slug")
+        assert parent._path == old_parent_path
