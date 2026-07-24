"""Content-addressed cache for converted documents."""
from __future__ import annotations

import hashlib
from pathlib import Path

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def cache_dir() -> Path:
    """Return (and create) the server-side cache directory."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def get_cached(content_hash: str) -> str | None:
    """Return cached markdown if it exists, else None."""
    path = cache_dir() / f"{content_hash}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def store(content_hash: str, markdown: str) -> Path:
    """Write markdown to cache and return the cache file path."""
    path = cache_dir() / f"{content_hash}.md"
    path.write_text(markdown, encoding="utf-8", newline="\n")
    return path
