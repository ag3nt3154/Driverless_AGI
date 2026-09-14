"""Content-addressed store for image attachments.

Persists image bytes under ``<project>/.dagi/attachments/<sha256>.<ext>`` and
converts between the durable ``dagi_image`` content-part representation (stored
in the session event log / history) and the OpenAI ``image_url`` data-URL
representation (used when building a provider request).

Concurrent-write safety (multiple processes writing the same project's asset
store at once) is deferred until multi-process access is actually needed;
today writes are atomic per-process via tempfile + os.replace only.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .user_input import ImageAttachment

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MIME_TO_EXT = {"image/png": ".png", "image/jpeg": ".jpg"}
_SUPPORTED_VERSION = 1


class AssetError(Exception):
    """Raised for any image-asset failure: missing, corrupt, or path traversal."""


@dataclass(frozen=True, slots=True)
class ImageRef:
    """A persisted reference to an image, as stored in a ``dagi_image`` content part."""
    sha256: str
    mime_type: str
    byte_size: int
    width: int
    height: int
    name: str
    version: int = 1
    detail: str | None = None

    def to_content_part(self) -> dict:
        part = {
            "type": "dagi_image",
            "version": self.version,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "byte_size": self.byte_size,
            "width": self.width,
            "height": self.height,
            "name": self.name,
        }
        if self.detail is not None:
            part["detail"] = self.detail
        return part

    @classmethod
    def from_content_part(cls, part: dict) -> ImageRef:
        if part.get("type") != "dagi_image":
            raise ValueError(f"not a dagi_image content part: {part.get('type')!r}")
        version = part.get("version")
        if version != _SUPPORTED_VERSION:
            raise ValueError(f"unsupported dagi_image version: {version!r}")
        required = ("sha256", "mime_type", "byte_size", "width", "height", "name")
        missing = [key for key in required if key not in part]
        if missing:
            raise ValueError(f"dagi_image content part missing fields: {missing}")
        return cls(
            sha256=part["sha256"],
            mime_type=part["mime_type"],
            byte_size=part["byte_size"],
            width=part["width"],
            height=part["height"],
            name=part["name"],
            version=version,
            detail=part.get("detail"),
        )


class ImageAssetStore:
    """Durable, content-addressed store for image bytes under a project's .dagi dir."""

    def __init__(self, project_path: Path) -> None:
        self._root = Path(project_path) / ".dagi" / "attachments"

    def _ext_for(self, mime_type: str) -> str:
        ext = _MIME_TO_EXT.get(mime_type)
        if ext is None:
            raise AssetError(f"unsupported mime_type: {mime_type!r}")
        return ext

    def resolve_path(self, ref: ImageRef) -> Path:
        # sha256 is validated as exactly 64 lowercase hex chars before it ever touches a
        # path, so this alone rules out "..", separators, absolute paths, etc.
        if not _SHA256_RE.match(ref.sha256):
            raise AssetError(f"invalid sha256: {ref.sha256!r}")
        ext = self._ext_for(ref.mime_type)
        path = self._root / f"{ref.sha256}{ext}"
        # Belt-and-braces: confirm the resolved path still lands inside the store root.
        root_resolved = self._root.resolve()
        if root_resolved not in path.resolve().parents:
            raise AssetError(f"path traversal rejected: {path}")
        return path

    def exists(self, ref: ImageRef) -> bool:
        try:
            path = self.resolve_path(ref)
        except AssetError:
            return False
        return path.is_file()

    def store(self, attachment: ImageAttachment) -> ImageRef:
        self._root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(attachment.data).hexdigest()
        ref = ImageRef(
            sha256=digest,
            mime_type=attachment.mime_type,
            byte_size=len(attachment.data),
            width=attachment.width,
            height=attachment.height,
            name=attachment.name,
        )
        path = self.resolve_path(ref)
        if path.exists():
            return ref
        fd, tmp_name = tempfile.mkstemp(dir=self._root, prefix=f".{digest}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(attachment.data)
            os.replace(tmp_name, path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return ref

    def load(self, ref: ImageRef) -> bytes:
        path = self.resolve_path(ref)
        if path.is_symlink():
            raise AssetError(f"refusing symlinked asset: {path}")
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise AssetError(f"asset not found: {path}") from exc
        except OSError as exc:
            raise AssetError(f"asset unreadable: {path} ({exc})") from exc
        if len(data) != ref.byte_size:
            raise AssetError(
                f"asset byte_size mismatch for {ref.sha256}: expected {ref.byte_size}, got {len(data)}"
            )
        digest = hashlib.sha256(data).hexdigest()
        if digest != ref.sha256:
            raise AssetError(f"asset sha256 mismatch: expected {ref.sha256}, got {digest}")
        return data

    def materialize_data_url(self, ref: ImageRef) -> str:
        data = self.load(ref)
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{ref.mime_type};base64,{encoded}"


def _materialize_part(part: dict, store: ImageAssetStore) -> dict:
    if not isinstance(part, dict) or part.get("type") != "dagi_image":
        return part
    try:
        ref = ImageRef.from_content_part(part)
    except ValueError as exc:
        raise AssetError(f"invalid dagi_image content part: {exc}") from exc
    url = store.materialize_data_url(ref)
    image_url: dict = {"url": url}
    if ref.detail is not None:
        image_url["detail"] = ref.detail
    return {"type": "image_url", "image_url": image_url}


def materialize_messages(messages: list[dict], store: ImageAssetStore) -> list[dict]:
    """Return a deep copy of `messages` with dagi_image parts resolved to image_url data URLs.

    All other fields (assistant tool_calls, reasoning, message order, etc.) are preserved
    unchanged. Raises AssetError if a dagi_image part references an unsupported version or
    a missing/corrupt asset.
    """
    result: list[dict] = []
    for message in messages:
        new_message = copy.deepcopy(message)
        content = new_message.get("content")
        if isinstance(content, list):
            new_message["content"] = [_materialize_part(part, store) for part in content]
        result.append(new_message)
    return result
