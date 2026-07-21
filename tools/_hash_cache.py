"""tools/_hash_cache.py — content-addressed cache shared across read-tool subsystems."""
from __future__ import annotations

import hashlib
import os
import threading
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

    Multiple workers (processes/threads) can race to compute the same key --
    e.g. two `read` calls on the same PDF landing at once. Redundant compute()
    calls are harmless, but writing straight to the final path is not: a
    concurrent reader could observe it mid-write (truncated/partial content).
    To avoid that, each writer writes to its own uniquely-named temp file and
    then atomically renames it onto the final path, so the final path only
    ever shows the pre-existing complete file or the new complete file, never
    a partial one.
    """
    path, _ = cache_path(key, subdir, ext, project_root)
    if path.exists():
        return path.read_text(encoding="utf-8"), path
    text = compute()
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.tmp")
    tmp_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp_path, path)
    return text, path
