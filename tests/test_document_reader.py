# tests/test_document_reader.py
from pathlib import Path
from unittest.mock import patch

from tools._document_reader import summarize_document

_CHARS_PER_TOKEN = 4


class TestSummarizeDocumentCacheHit:
    def test_returns_cached_summary_when_exists(self, tmp_path):
        full_text = "x" * 200_000  # ~50k tokens, well over any budget
        # Pre-populate the cache
        import hashlib
        content_hash = hashlib.sha256(full_text.encode()).hexdigest()
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "document_summary"
        cache_dir.mkdir(parents=True)
        cached_summary = "## Introduction (lines 1-100, ~500 tokens)\n**Summary:** test"
        (cache_dir / f"{content_hash}_summary.md").write_text(
            cached_summary, encoding="utf-8"
        )

        result = summarize_document(
            full_text=full_text,
            source_path=tmp_path / "big.txt",
            filename="big.txt",
            project_path=tmp_path,
        )

        assert result == cached_summary


class TestSummarizeDocumentCacheMiss:
    def test_spawns_subagent_and_returns_written_summary(self, tmp_path):
        full_text = "x" * 200_000
        import hashlib
        content_hash = hashlib.sha256(full_text.encode()).hexdigest()
        expected_summary_path = (
            tmp_path / ".dagi" / "hash_cache" / "document_summary"
            / f"{content_hash}_summary.md"
        )

        fake_summary = "## Section 1 (lines 1-50, ~200 tokens)\n**Summary:** fake"

        def fake_run_subagent(
            subagent_type, task, project_path, handoff_path, timeout, on_event
        ):
            # Simulate what the subagent does: write the summary file
            expected_summary_path.parent.mkdir(parents=True, exist_ok=True)
            expected_summary_path.write_text(fake_summary, encoding="utf-8")
            # Write handoff
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("done", encoding="utf-8")
            return {"status": "ok", "handoff": str(handoff_path)}

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = summarize_document(
                full_text=full_text,
                source_path=tmp_path / "big.txt",
                filename="big.txt",
                project_path=tmp_path,
            )

        assert result == fake_summary


class TestSummarizeDocumentFallback:
    def test_returns_none_when_subagent_fails(self, tmp_path):
        full_text = "x" * 200_000

        def fake_run_subagent(**kwargs):
            return {"status": "error", "message": "subagent crashed"}

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = summarize_document(
                full_text=full_text,
                source_path=tmp_path / "big.txt",
                filename="big.txt",
                project_path=tmp_path,
            )

        assert result is None
