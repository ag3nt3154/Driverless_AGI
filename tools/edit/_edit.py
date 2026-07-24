from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file by replacing exact text. The oldText must match exactly "
        "(including whitespace). Use this for precise, surgical edits. "
        "Paths are relative to the project root."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit (relative to project root, or absolute)"},
            "oldText": {"type": "string", "description": "Exact text to find and replace (must match exactly)"},
            "newText": {"type": "string", "description": "New text to replace the old text with"},
        },
        "required": ["path", "oldText", "newText"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, oldText: str, newText: str) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        content = p.read_text(encoding="utf-8")
        # read_text() uses universal newlines (CRLF/CR → LF).  Normalise
        # oldText/newText the same way so that LLM-generated CRLF (e.g. copied
        # from bash/grep output on Windows) doesn't silently fail to match.
        old_norm = oldText.replace("\r\n", "\n").replace("\r", "\n")
        new_norm = newText.replace("\r\n", "\n").replace("\r", "\n")
        count = content.count(old_norm)
        if count == 0:
            return f"Error: oldText not found in {p}"
        if count > 1:
            return f"Error: oldText found {count} times in {p} — must be unique"
        # newline="\n" prevents Windows text-mode from converting \n → \r\n,
        # which would double any \r already present and corrupt the file.
        p.write_text(content.replace(old_norm, new_norm, 1), encoding="utf-8", newline="\n")
        return f"Edited {p}"
