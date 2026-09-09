"""tests/test_reader_job.py — Reader job manifest transport and run_subagent integration.

Covers:
  - write_reader_job / load_reader_job round-trip (version, schema, digest)
  - load_reader_job error paths (bad version, missing field, digest mismatch)
  - run_subagent(..., reader_job_spec=spec) injects --reader-job into argv
  - run_subagent rejects reader_job_spec with wrong preset
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.read._reader_job import (
    ReaderJob,
    ReaderJobSpec,
    ReaderLaunchContext,
    ReaderReturnFormat,
    load_reader_job,
    write_reader_job,
)
from tools.read._selection import ReadSelection, SourceSpan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_selection(text: str = "hello\nworld") -> ReadSelection:
    return ReadSelection(
        path=Path("/fake/file.txt"),
        text=text,
        spans=(SourceSpan(start=0, end=len(text), source_start=0, line_start=1),),
        header=None,
        editable_path=None,
        scope="lines 1-2 of 2",
    )


def _make_job(tmp_path: Path, text: str = "hello\nworld") -> tuple[ReaderJob, Path]:
    sel = _make_selection(text)
    fmt = ReaderReturnFormat(
        signpost="[signpost]",
        handoff_path=tmp_path / "handoff.md",
    )
    job = ReaderJob(
        version=1,
        selection=sel,
        query="summarize",
        parent_reserve=200,
        return_format=fmt,
    )
    return job, tmp_path


# ---------------------------------------------------------------------------
# write_reader_job / load_reader_job round-trip
# ---------------------------------------------------------------------------

class TestReaderJobRoundTrip:
    def test_roundtrip_basic(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        assert path.exists()
        loaded = load_reader_job(path)
        assert loaded.version == 1
        assert loaded.query == "summarize"
        assert loaded.parent_reserve == 200
        assert loaded.selection.text == "hello\nworld"
        assert loaded.selection.scope == "lines 1-2 of 2"

    def test_roundtrip_path_preserved(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        loaded = load_reader_job(path)
        assert loaded.selection.path == Path("/fake/file.txt")

    def test_roundtrip_span_fields(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        loaded = load_reader_job(path)
        span = loaded.selection.spans[0]
        assert span.start == 0
        assert span.end == len("hello\nworld")
        assert span.source_start == 0
        assert span.line_start == 1
        assert span.page is None

    def test_roundtrip_return_format(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        loaded = load_reader_job(path)
        assert loaded.return_format.signpost == "[signpost]"
        assert loaded.return_format.handoff_path == tmp_path / "handoff.md"

    def test_json_contains_digest(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "text_digest" in raw["selection"]
        assert len(raw["selection"]["text_digest"]) == 64  # sha256 hex

    def test_roundtrip_with_page(self, tmp_path):
        sel = ReadSelection(
            path=Path("/doc.pdf"),
            text="page content",
            spans=(SourceSpan(start=0, end=12, source_start=0, line_start=1, page=3),),
            header="[PDF: doc.pdf | 5 pages]",
            editable_path=None,
            scope="page 3 of 5",
        )
        fmt = ReaderReturnFormat(signpost="[s]", handoff_path=tmp_path / "h.md")
        job = ReaderJob(version=1, selection=sel, query="", parent_reserve=100, return_format=fmt)
        path = write_reader_job(job, tmp_path)
        loaded = load_reader_job(path)
        assert loaded.selection.spans[0].page == 3
        assert loaded.selection.header == "[PDF: doc.pdf | 5 pages]"

    def test_directory_created_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, nested)
        assert path.exists()
        assert nested.is_dir()

    def test_editable_path_preserved(self, tmp_path):
        sel = ReadSelection(
            path=Path("/doc.docx"),
            text="content",
            spans=(SourceSpan(start=0, end=7, source_start=0, line_start=1),),
            header=None,
            editable_path=Path("/cache/doc.md"),
            scope="all",
        )
        fmt = ReaderReturnFormat(signpost="[s]", handoff_path=tmp_path / "h.md")
        job = ReaderJob(version=1, selection=sel, query="", parent_reserve=100, return_format=fmt)
        path = write_reader_job(job, tmp_path)
        loaded = load_reader_job(path)
        assert str(loaded.selection.editable_path) == str(Path("/cache/doc.md"))


# ---------------------------------------------------------------------------
# load_reader_job error paths
# ---------------------------------------------------------------------------

class TestLoadReaderJobErrors:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_reader_job(tmp_path / "nonexistent.json")

    def test_bad_version_raises(self, tmp_path):
        payload = {"version": 99, "selection": {}, "query": "", "parent_reserve": 1,
                   "return_format": {"signpost": "", "handoff_path": "/x"}}
        p = tmp_path / "job.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="version"):
            load_reader_job(p)

    def test_missing_selection_raises(self, tmp_path):
        payload = {"version": 1, "query": "", "parent_reserve": 1,
                   "return_format": {"signpost": "", "handoff_path": "/x"}}
        p = tmp_path / "job.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="selection"):
            load_reader_job(p)

    def test_digest_mismatch_raises(self, tmp_path):
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["selection"]["text_digest"] = "a" * 64  # wrong digest
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="digest"):
            load_reader_job(path)

    def test_missing_digest_is_tolerated(self, tmp_path):
        """An absent digest field skips validation (legacy/manual files)."""
        job, _ = _make_job(tmp_path)
        path = write_reader_job(job, tmp_path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        del raw["selection"]["text_digest"]
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_reader_job(path)  # should not raise
        assert loaded.selection.text == "hello\nworld"


# ---------------------------------------------------------------------------
# run_subagent reader_job_spec integration
# ---------------------------------------------------------------------------

class TestRunSubagentReaderJob:
    """Verify run_subagent correctly writes a job file and passes --reader-job."""

    def _fake_run_result(self, handoff_path: Path) -> dict:
        handoff_path.write_text("reader output", encoding="utf-8")
        return {
            "status": "ok",
            "handoff": str(handoff_path),
            "pid": 12345,
            "message": "",
            "exit_code": 0,
            "output_tail": "",
            "output_log_path": None,
        }

    def test_reader_job_written_and_argv_injected(self, tmp_path):
        from tools.subagent_api import run_subagent
        from tools.read._reader_job import ReaderJobSpec

        sel = _make_selection()
        spec = ReaderJobSpec(selection=sel, query="q", parent_reserve=100)

        captured_argv: list[list[str]] = []

        def fake_run(subagent_type, task, project_path, handoff_path, **kwargs):
            captured_argv.append(kwargs.get("extra_argv") or [])
            return self._fake_run_result(handoff_path)

        with patch("tools._subagent_runner.run_subagent", side_effect=fake_run):
            result = run_subagent(
                task="test task",
                preset="read-large-text",
                project_path=tmp_path,
                handoff_dir=tmp_path / "handoffs",
                reader_job_spec=spec,
            )

        assert result.is_ok
        argv = captured_argv[0]
        assert "--reader-job" in argv
        idx = argv.index("--reader-job")
        job_path = Path(argv[idx + 1])
        # The job file should still exist (subprocess hasn't cleaned it up)
        assert job_path.exists()
        # Verify it's a valid job manifest
        loaded = load_reader_job(job_path)
        assert loaded.query == "q"
        assert loaded.selection.text == sel.text

    def test_wrong_preset_raises(self, tmp_path):
        from tools.subagent_api import run_subagent
        from tools.read._reader_job import ReaderJobSpec

        sel = _make_selection()
        spec = ReaderJobSpec(selection=sel, query="q", parent_reserve=100)

        with pytest.raises(ValueError, match="read-large-text"):
            run_subagent(
                task="t",
                preset="explore",
                project_path=tmp_path,
                reader_job_spec=spec,
            )

    def test_no_reader_job_no_argv_flag(self, tmp_path):
        """Without reader_job_spec, --reader-job must not appear in argv."""
        from tools.subagent_api import run_subagent

        captured_argv: list[list[str]] = []

        def fake_run(subagent_type, task, project_path, handoff_path, **kwargs):
            captured_argv.append(kwargs.get("extra_argv") or [])
            return self._fake_run_result(handoff_path)

        with patch("tools._subagent_runner.run_subagent", side_effect=fake_run):
            with patch("tools.subagent_api._load_preset",
                       return_value=("p", ["read"], "worker", "", "custom")):
                run_subagent(
                    task="t",
                    preset="read-large-text",
                    project_path=tmp_path,
                    handoff_dir=tmp_path / "handoffs",
                )

        argv = captured_argv[0]
        assert "--reader-job" not in argv
