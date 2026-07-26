"""HTTP client for the document converter service.

Anti-corruption layer: all HTTP details (endpoint, auth, headers, error
mapping) are encapsulated here. When the service API evolves, only this
file changes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

_DOC_CACHE_SUBDIR = "doc_convert"
_TIMEOUT = 300.0  # 5 minutes — large PDFs with OCR can be slow


def _cache_path_from_hash(content_hash: str, project_path: Path) -> Path:
    return project_path / ".dagi" / "hash_cache" / _DOC_CACHE_SUBDIR / f"{content_hash}.md"


def cache_path_for(path: Path, project_path: Path) -> Path:
    """Path of the converted-markdown cache entry for a source document."""
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return _cache_path_from_hash(content_hash, project_path)


class DocServiceError(Exception):
    """Raised when the document converter service returns an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def convert_document(
    path: Path,
    service_url: str,
    project_path: Path,
) -> str:
    """Convert a document file to markdown via the converter service.

    Checks the local hash cache first. On miss, uploads to the service
    and caches the result locally.

    Args:
        path: Absolute path to the document file.
        service_url: Base URL of the converter service (e.g. http://localhost:8100).
        project_path: Project root — local cache lives under .dagi/hash_cache/.

    Returns:
        Markdown text of the converted document.

    Raises:
        DocServiceError: on service errors (with code and message).
    """
    file_bytes = path.read_bytes()
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    cache_file = _cache_path_from_hash(content_hash, project_path)
    cache_dir = cache_file.parent
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    # Cache miss — call service
    url = f"{service_url.rstrip('/')}/convert"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.post(
                url,
                files={"file": (path.name, file_bytes)},
            )
    except httpx.ConnectError:
        raise DocServiceError(
            "CONNECTION_FAILED",
            f"Document conversion service is not running at {service_url}. "
            f"Start it with: python -m services.doc_converter",
        )
    except httpx.TimeoutException:
        raise DocServiceError(
            "TIMEOUT",
            f"Document conversion service timed out after {_TIMEOUT}s. "
            f"The document may be too large or the service may be overloaded.",
        )

    if response.status_code == 200:
        markdown = response.text
        # Store in local cache
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(markdown, encoding="utf-8", newline="\n")
        return markdown

    # Error response — parse JSON error detail
    try:
        error_body = response.json()
        code = error_body.get("code", "UNKNOWN")
        message = error_body.get("error", response.text)
    except Exception:
        code = f"HTTP_{response.status_code}"
        message = response.text

    raise DocServiceError(code, message)
