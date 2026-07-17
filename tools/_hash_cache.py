"""tools/_hash_cache.py — content-addressed cache shared across read-tool subsystems."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable

_HASH_CACHE_DIR = ".dagi/hash_cache"


def cache_path(key: bytes, subdir: str, ext: str, project_root: Path) -> tuple[Path, str]:
    """Return (file_path, hex_hash) for a cache entry. Creates the subdir if missing."""
    content_hash = hashlib.sha256(key).hexdigest()
    cache_dir = Path(project_root) / _HASH_CACHE_DIR / subdir
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{content_hash}.{ext}", content_hash


def get_or_compute(
    key: bytes,
    subdir: str,
    ext: str,
    project_root: Path,
    compute: Callable[[], str],
) -> tuple[str, Path]:
    """Return cached text for `key`, computing (and caching) on a miss.

    `compute` is only called on a cache miss -- callers with expensive derivations
    (e.g. PDF conversion) can defer that work to this closure.
    """
    path, _ = cache_path(key, subdir, ext, project_root)
    if path.exists():
        return path.read_text(encoding="utf-8"), path
    text = compute()
    path.write_text(text, encoding="utf-8", newline="\n")
    return text, path
