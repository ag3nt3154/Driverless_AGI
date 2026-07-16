import base64
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

# Image extensions — currently blocked until the endpoint supports image tool results.
# TODO: remove _IMAGE_EXTS from _BLOCKED_EXTS and re-enable the image path below.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# File types that the read tool explicitly cannot handle.
# Everything else is attempted as UTF-8 text.
# Add future unsupported formats here (pdf, docx, etc.) until they gain read support.
_BLOCKED_EXTS = _IMAGE_EXTS.copy()


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read (relative to project root, or absolute)"},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        "required": ["path"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, offset: int = 1, limit: int = 2000) -> str | list:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        ext = p.suffix.lower()

        # ── Blocked file type gate ────────────────────────────────────────
        if ext in _BLOCKED_EXTS:
            return (
                f"Error: Cannot read file type '{ext}'. This file type is not currently "
                f"supported by the read tool. If this file type should be supported, "
                f"update _BLOCKED_EXTS in tools/read.py."
            )
        # ──────────────────────────────────────────────────────────────────

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return (
                f"Error: Cannot read '{p.name}' as text. The file appears to be binary "
                f"or uses an encoding other than UTF-8."
            )

        start = max(0, offset - 1)
        selected = lines[start : start + limit]
        return "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(selected, start + 1))