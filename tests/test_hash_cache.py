"""tests/test_hash_cache.py — Unit tests for tools/_hash_cache.py."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from tools._hash_cache import cache_path, get_or_compute


class TestCachePath:
    def test_returns_path_under_hash_cache_subdir(self, tmp_path):
        path, _ = cache_path(b"hello", "pdf", "md", tmp_path)
        assert path.parent == tmp_path / ".dagi" / "hash_cache" / "pdf"

    def test_filename_is_sha256_hex_plus_ext(self, tmp_path):
        path, content_hash = cache_path(b"hello", "pdf", "md", tmp_path)
        assert content_hash == hashlib.sha256(b"hello").hexdigest()
        assert path.name == f"{content_hash}.md"

    def test_creates_subdir(self, tmp_path):
        cache_path(b"hello", "tool_output", "txt", tmp_path)
        assert (tmp_path / ".dagi" / "hash_cache" / "tool_output").is_dir()

    def test_different_keys_different_paths(self, tmp_path):
        path1, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        path2, _ = cache_path(b"bbb", "pdf", "md", tmp_path)
        assert path1 != path2

    def test_same_key_same_path(self, tmp_path):
        path1, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        path2, _ = cache_path(b"aaa", "pdf", "md", tmp_path)
        assert path1 == path2


class TestGetOrCompute:
    def test_cache_miss_calls_compute_and_writes(self, tmp_path):
        calls = []

        def compute():
            calls.append(1)
            return "computed text"

        text, path = get_or_compute(b"key1", "pdf", "md", tmp_path, compute)

        assert text == "computed text"
        assert len(calls) == 1
        assert path.read_text(encoding="utf-8") == "computed text"

    def test_cache_hit_skips_compute(self, tmp_path):
        calls = []

        def compute():
            calls.append(1)
            return "computed text"

        get_or_compute(b"key2", "pdf", "md", tmp_path, compute)  # populates cache
        text, path = get_or_compute(b"key2", "pdf", "md", tmp_path, compute)  # hit

        assert text == "computed text"
        assert len(calls) == 1  # compute only called once, on the miss

    def test_returns_cache_path(self, tmp_path):
        text, path = get_or_compute(b"key3", "tool_output", "txt", tmp_path, lambda: "x")
        expected_path, _ = cache_path(b"key3", "tool_output", "txt", tmp_path)
        assert path == expected_path

    def test_writes_lf_only(self, tmp_path):
        text, path = get_or_compute(b"key4", "pdf", "md", tmp_path, lambda: "line1\nline2")
        raw = path.read_bytes()
        assert b"\r\n" not in raw


class TestGetOrComputeAtomicity:
    def test_final_path_never_observed_partially_written(self, tmp_path, monkeypatch):
        """Two workers computing the same cache key concurrently must never let a
        reader see the final cache path mid-write (truncated/partial content).

        Simulates a slow write by splitting whatever write_text() call the
        implementation performs into two chunks with a pause between them —
        this widens the race window deterministically regardless of real disk
        speed. A reader thread polls the *final* cache path throughout; the
        pre-fix implementation writes directly to that path, so the reader
        catches it half-written. The fix must write to a differently-named
        temp file and only expose the final path via an atomic rename.
        """
        full_text = "chunk-one-content " * 500 + "chunk-two-content " * 500
        original_write_text = Path.write_text
        write_started = threading.Event()
        resume_write = threading.Event()

        def slow_write_text(self, data, *args, **kwargs):
            if data != full_text:
                return original_write_text(self, data, *args, **kwargs)
            encoding = kwargs.get("encoding", "utf-8")
            newline = kwargs.get("newline")
            mid = len(data) // 2
            with open(self, "w", encoding=encoding, newline=newline) as f:
                f.write(data[:mid])
                f.flush()
                write_started.set()
                resume_write.wait(timeout=2)
                time.sleep(0.05)
                f.write(data[mid:])
            return len(data)

        monkeypatch.setattr(Path, "write_text", slow_write_text)

        final_path, _ = cache_path(b"race-key", "pdf", "md", tmp_path)
        observed: list[str] = []

        def writer():
            get_or_compute(b"race-key", "pdf", "md", tmp_path, lambda: full_text)

        def reader():
            # Read exactly once, deterministically inside the window where the
            # writer is blocked mid-write (after flushing the first half, before
            # writing the second) -- not a timing-dependent poll.
            write_started.wait(timeout=2)
            if final_path.exists():
                try:
                    observed.append(final_path.read_text(encoding="utf-8"))
                except OSError:
                    pass
            resume_write.set()

        t_writer = threading.Thread(target=writer)
        t_reader = threading.Thread(target=reader)
        t_writer.start()
        t_reader.start()
        t_writer.join()
        t_reader.join()

        assert write_started.is_set(), "test setup broken: slow_write_text never ran"
        for content in observed:
            assert content == full_text, (
                "reader observed the final cache path in a partially-written "
                "state — get_or_compute must write via a temp file + atomic "
                "rename, not directly to the final path"
            )
