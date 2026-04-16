from pathlib import Path

from agent.base_tool import BaseTool


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

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, path: str, oldText: str, newText: str) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        content = p.read_text(encoding="utf-8")
        count = content.count(oldText)
        if count == 0:
            return f"Error: oldText not found in {p}"
        if count > 1:
            return f"Error: oldText found {count} times in {p} — must be unique"
        p.write_text(content.replace(oldText, newText, 1), encoding="utf-8")
        return f"Edited {p}"
