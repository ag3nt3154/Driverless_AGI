from pathlib import Path

from agent.base_tool import BaseTool

_MAX_RESULTS = 500


class FindTool(BaseTool):
    name = "find"
    description = (
        "Find files by glob pattern. Returns matching file paths relative to the project root. "
        "Use '**/*.py' for recursive searches. Paths are relative to the project root."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match (e.g. '**/*.py', 'src/*.ts', '*.md')"},
            "path": {"type": "string", "description": "Directory to search within (default: project root)"},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: Path = Path(".")):
        self.cwd = cwd

    def run(self, pattern: str, path: str = ".") -> str:
        search_path = Path(path)
        if not search_path.is_absolute():
            search_path = self.cwd / search_path

        if not search_path.exists():
            return f"Error: path does not exist: {search_path}"

        matches = sorted(search_path.glob(pattern))
        if not matches:
            return "[no matches]"

        lines = []
        for p in matches[:_MAX_RESULTS]:
            try:
                rel = p.relative_to(self.cwd)
            except ValueError:
                rel = p
            lines.append(str(rel))

        if len(matches) > _MAX_RESULTS:
            lines.append(f"[truncated — showing first {_MAX_RESULTS} of {len(matches)} results]")

        return "\n".join(lines)
