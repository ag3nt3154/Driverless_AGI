"""tests/test_hash_cache.py — Unit tests for tools/_hash_cache.py."""
from __future__ import annotations

import hashlib

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
