import base64
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool
from agent.registry import registry

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
        "Use offset/limit for large files."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read (relative or absolute)"},
            "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed)"},
            "limit": {"type": "integer", "description": "Maximum number of lines to read"},
        },
        "required": ["path"],
    }

    def run(self, path: str, offset: int = 1, limit: int = 2000) -> str | list:
        p = Path(path)
        ext = p.suffix.lower()
        if ext in _IMAGE_EXTS:
            b64 = base64.b64encode(p.read_bytes()).decode()
            mime = _MIME[ext]
            return [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]
        lines = p.read_text(encoding="utf-8").splitlines()
        start = max(0, offset - 1)
        return "\n".join(lines[start : start + limit])


class WriteTool(BaseTool):
    name = "write"
    description = (
        "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. "
        "Automatically creates parent directories."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write (relative or absolute)"},
            "content": {"type": "string", "description": "Content to write to the file"},
        },
        "required": ["path", "content"],
    }

    def run(self, path: str, content: str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} characters to {path}"


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file by replacing exact text. The oldText must match exactly "
        "(including whitespace). Use this for precise, surgical edits."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit (relative or absolute)"},
            "oldText": {"type": "string", "description": "Exact text to find and replace (must match exactly)"},
            "newText": {"type": "string", "description": "New text to replace the old text with"},
        },
        "required": ["path", "oldText", "newText"],
    }

    def run(self, path: str, oldText: str, newText: str) -> str:
        p = Path(path)
        content = p.read_text(encoding="utf-8")
        count = content.count(oldText)
        if count == 0:
            return f"Error: oldText not found in {path}"
        if count > 1:
            return f"Error: oldText found {count} times in {path} — must be unique"
        p.write_text(content.replace(oldText, newText, 1), encoding="utf-8")
        return f"Edited {path}"


class BashTool(BaseTool):
    name = "bash"
    description = (
        "Execute a bash command in the current working directory. "
        "Returns stdout and stderr. Optionally provide a timeout in seconds."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Bash command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (optional)"},
        },
        "required": ["command"],
    }

    def run(self, command: str, timeout: int | None = None) -> str:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
        output = result.stdout + result.stderr
        if result.returncode != 0:
            output += f"\n[exit code {result.returncode}]"
        return output or "[no output]"


for _cls in [ReadTool, WriteTool, EditTool, BashTool]:
    registry.register(_cls())
