import base64
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a file. Supports text files and images (jpg, png, gif, webp). "
        "Images are sent as attachments. For text files, defaults to first 2000 lines. "
        "Use offset/limit for large files. Accepts both relative paths (resolved from the project root) and absolute paths."
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
        self.allowed_roots = allowed_roots or [cwd]

    def run(self, path: str, offset: int = 1, limit: int = 2000) -> str | list:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            b64 = base64.b64encode(p.read_bytes()).decode()
            mime = _MIME[ext]
            return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
        lines = p.read_text(encoding="utf-8").splitlines()
        start = max(0, offset - 1)
        return "\n".join(lines[start : start + limit])
