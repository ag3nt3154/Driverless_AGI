from __future__ import annotations

from pathlib import Path
from typing import Callable

from agent.base_tool import BaseTool


class ShowFileTool(BaseTool):
    name = "show_file"
    description = (
        "Open a file in the GUI file viewer for the user to see. "
        "Optionally jump to and highlight a specific line number."
    )

    def __init__(
        self,
        on_show_file: Callable[[str, int | None], None],
        project_path: Path,
    ) -> None:
        self._on_show_file = on_show_file
        self._project_path = project_path

    @property
    def _parameters(self):
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Absolute or project-relative path to the file to display."
                    ),
                },
                "line": {
                    "type": "integer",
                    "description": (
                        "Line number to jump to and highlight (1-indexed). Optional."
                    ),
                },
            },
            "required": ["path"],
        }

    def run(self, path: str, line: int | None = None) -> str:
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = self._project_path / resolved
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {resolved}")
        self._on_show_file(str(resolved), line)
        suffix = f" at line {line}" if line else ""
        return f"Opened {resolved.name}{suffix} in the file viewer."
