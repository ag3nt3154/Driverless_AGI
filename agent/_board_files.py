"""Pure validation, containment and cache hashing for board attachments."""
from __future__ import annotations

import hashlib
import re
import stat
from pathlib import Path, PureWindowsPath

MAX_ATTACHMENT = 10 * 1024 * 1024
_ID = re.compile(r"att_[0-9a-f]{12}")
_HASH = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f-\x9f]')
_DEVICE = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", re.IGNORECASE)


def validate_attachment_id(attachment_id: str) -> None:
    if not isinstance(attachment_id, str) or not _ID.fullmatch(attachment_id):
        raise ValueError("attachment id must be att_ followed by 12 lowercase hex digits")


def validate_name(name: str) -> None:
    if not isinstance(name, str) or not 1 <= len(name) <= 128:
        raise ValueError("attachment name must be a basename of 1 through 128 characters")
    if _FORBIDDEN.search(name) or PureWindowsPath(name).drive:
        raise ValueError("attachment name contains forbidden path or control characters")
    if name in (".", "..") or name.endswith((".", " ")):
        raise ValueError("attachment name must not end with a dot or space")
    if _DEVICE.fullmatch(name.split(".")[0].rstrip(" ")):
        raise ValueError("attachment name is a reserved Windows device")


def validate_attachment(attachment_id: str, metadata: dict) -> dict:
    """Return a copy of metadata only after validating every cache-relevant field."""
    validate_attachment_id(attachment_id)
    if not isinstance(metadata, dict) or metadata.get("id") != attachment_id:
        raise ValueError("attachment metadata id does not match the requested id")
    validate_name(metadata.get("name"))
    size = metadata.get("size")
    if type(size) is not int or not 1 <= size <= MAX_ATTACHMENT:
        raise ValueError("attachment size must be an integer from 1 byte through 10 MB")
    digest = metadata.get("sha256")
    if not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ValueError("attachment sha256 must contain 64 lowercase hex digits")
    if metadata.get("kind") not in ("image", "file"):
        raise ValueError("attachment kind must be image or file")
    return dict(metadata)


def _reject_link(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(info.st_mode) or reparse:
        raise ValueError(f"attachment cache must not contain links or junctions: {path.name}")


def attachment_cache_path(project_root: Path, att: dict) -> Path:
    """Validate existing components before creating or writing any cache files."""
    validate_attachment(att.get("id"), att)
    root = Path(project_root).resolve()
    cache = root / ".dagi" / "board" / "attachments"
    destination = cache / att["id"] / att["name"]
    path = root
    for component in destination.relative_to(root).parts:
        path = path / component
        _check_component(path, destination)
    if not cache.resolve().is_relative_to(root):
        raise ValueError("attachment cache escapes the project root")
    if not destination.resolve().is_relative_to(cache.resolve()):
        raise ValueError("attachment destination escapes the cache root")
    return destination


def _check_component(path: Path, destination: Path) -> None:
    _reject_link(path)
    if not path.exists():
        return
    if path == destination:
        if not path.is_file():
            raise ValueError("attachment cache destination must be a regular file")
    elif not path.is_dir():
        raise ValueError("attachment cache parent must be a directory")


def cached_file_matches(path: Path, att: dict, check=None) -> bool:
    """Reuse bytes only after checking both their declared size and digest."""
    _reject_link(path)
    if not path.exists() or path.stat().st_size != att["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            if check is not None:
                check()
            digest.update(chunk)
    return digest.hexdigest() == att["sha256"]
