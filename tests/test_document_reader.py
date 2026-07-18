# tests/test_document_reader.py
from pathlib import Path
from unittest.mock import patch

from tools._document_reader import summarize_document
from tools.read import ReadTool

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


class TestEndToEnd:
    def test_read_tool_with_large_file_produces_summary_via_subagent(self, tmp_path):
        """Integration test: ReadTool → _document_reader → mock subagent → cached summary."""
        # Create a large file
        lines = [f"Line {i}: content about topic {i % 5}" for i in range(1, 10_001)]
        content = "\n".join(lines)
        f = tmp_path / "large_doc.txt"
        f.write_text(content, encoding="utf-8")

        fake_summary = (
            "[Document: large_doc.txt | 5 sections | "
            f"full text cached: {tmp_path}]\n\n"
            "## Section 1 (lines 1-2000, ~2500 tokens)\n"
            "**Summary:** Content about various topics.\n"
            "**Key excerpts:**\n"
            "- L1: \"Line 1: content about topic 1\"\n"
        )

        def fake_run_subagent(
            subagent_type, task, project_path, handoff_path, timeout, on_event
        ):
            assert subagent_type == "document-reader"
            assert "large_doc.txt" in task
            # Simulate subagent writing the summary
            import hashlib
            full_text_numbered = "\n".join(
                f"{i:6d}\t{line}" for i, line in enumerate(lines, 1)
            )
            h = hashlib.sha256(full_text_numbered.encode("utf-8")).hexdigest()
            summary_dir = project_path / ".dagi" / "hash_cache" / "document_summary"
            summary_dir.mkdir(parents=True, exist_ok=True)
            (summary_dir / f"{h}_summary.md").write_text(
                fake_summary, encoding="utf-8"
            )
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("done", encoding="utf-8")
            return {"status": "ok", "handoff": str(handoff_path)}

        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=1_000,  # Low budget to trigger summarization
            project_path=tmp_path,
        )

        with patch(
            "tools._document_reader.run_subagent", side_effect=fake_run_subagent
        ):
            result = tool.run(path="large_doc.txt")

        assert "Section 1" in result
        assert "large_doc.txt" in result

    def test_second_read_hits_cache(self, tmp_path):
        """After first summarization, second read returns cached summary without subagent."""
        lines = [f"Line {i}" for i in range(1, 10_001)]
        content = "\n".join(lines)
        f = tmp_path / "large_doc.txt"
        f.write_text(content, encoding="utf-8")

        fake_summary = "## Cached summary"

        # Pre-populate cache
        import hashlib
        full_text_numbered = "\n".join(
            f"{i:6d}\t{line}" for i, line in enumerate(lines, 1)
        )
        h = hashlib.sha256(full_text_numbered.encode("utf-8")).hexdigest()
        summary_dir = tmp_path / ".dagi" / "hash_cache" / "document_summary"
        summary_dir.mkdir(parents=True, exist_ok=True)
        (summary_dir / f"{h}_summary.md").write_text(
            fake_summary, encoding="utf-8"
        )

        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=1_000,
            project_path=tmp_path,
        )

        with patch(
            "tools._document_reader.run_subagent"
        ) as mock_run:
            result = tool.run(path="large_doc.txt")

        mock_run.assert_not_called()
        assert result == fake_summary
