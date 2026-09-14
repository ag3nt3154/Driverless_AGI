"""Qt-free value objects for a user's chat submission (text + image attachments).

Pure data: no image decoding/encoding, no Qt imports, no filesystem access.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageAttachment:
    """A single image the user attached to a submission.

    `data` holds already-encoded PNG/JPEG bytes (not raw pixels); `width`/`height`
    are the decoded pixel dimensions used for display and provider limits.
    """
    data: bytes
    mime_type: str
    width: int
    height: int
    name: str

    def __post_init__(self) -> None:
        if self.mime_type not in ("image/png", "image/jpeg"):
            raise ValueError(f"unsupported mime_type: {self.mime_type!r}")
        if not self.data:
            raise ValueError("ImageAttachment.data must not be empty")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("ImageAttachment width/height must be positive")
        if not self.name:
            raise ValueError("ImageAttachment.name must not be empty")


@dataclass(frozen=True, slots=True)
class UserSubmission:
    """A user's chat turn: free text plus zero or more image attachments."""
    text: str
    images: tuple[ImageAttachment, ...] = ()

    def __post_init__(self) -> None:
        if not self.text and not self.images:
            raise ValueError("UserSubmission requires non-empty text or at least one image")

    @property
    def is_valid(self) -> bool:
        return bool(self.text) or bool(self.images)
