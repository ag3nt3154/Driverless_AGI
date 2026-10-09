"""Content-addressed board blobs and safe display names."""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
from pathlib import Path

_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])$", re.IGNORECASE)
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f-\x9f]')
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sanitize_name(name: str) -> str:
    """Return a bounded basename usable on Windows as well as POSIX."""
    name = re.split(r"[\\/]", name)[-1]
    name = _FORBIDDEN.sub("_", name)[:128].rstrip(". ") or "file"
    if _DEVICE.fullmatch(name.split(".")[0].rstrip(" ")):
        name = "_" + name
    return name[:128].rstrip(". ")


def _image_mime(head: bytes) -> str | None:
    for signature, mime in _SIGNATURES:
        if head.startswith(signature):
            return mime
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_kind(head: bytes) -> str:
    """Classify images by magic bytes, independent of their filename."""
    return "image" if _image_mime(head) else "file"


def sniff_mime(head: bytes, name: str) -> str:
    """Use image magic first, then the filename's MIME hint."""
    return _image_mime(head) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def write_blob(blob_dir: Path, data: bytes) -> str:
    """Atomically publish immutable bytes, addressed by their SHA-256 digest."""
    digest = hashlib.sha256(data).hexdigest()
    blob_dir.mkdir(parents=True, exist_ok=True)
    target = blob_dir / digest
    if target.exists():
        return digest
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=blob_dir, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return digest
