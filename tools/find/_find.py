from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

# No display cap: large results go through the shared output filter (head + marker
# + tail, full text saved). This ceiling only guards memory against runaway globs.
_SAFETY_LIMIT = 100_000


class FindTool(BaseTool):
    name = "find"
    description = (
        "Find files by glob pattern. Returns matching file paths "
        "relative to the project root. Use '**/*.py' for recursive searches. "
        "Very large results show only the first and last paths, with the full "
        "list saved to a file you can read or grep."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py', 'src/*.ts', '*.md')",
            },
            "path": {
                "type": "string",
                "description": "Directory to search within",
            },
        },
        "required": ["pattern", "path"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, pattern: str, path: str) -> str:
        sp = Path(path)
        if not sp.is_absolute():
            sp = self.cwd / sp
        search_path = validate_path(sp, self.allowed_roots)

        if not search_path.exists():
            return "[no matches]"

        matches = sorted(search_path.glob(pattern))
        if not matches:
            return "[no matches]"

        lines = []
        for p in matches[:_SAFETY_LIMIT]:
            try:
                rel = p.relative_to(self.cwd)
            except ValueError:
                rel = p
            lines.append(str(rel))

        if len(matches) > _SAFETY_LIMIT:
            lines.append(
                f"[stopped at {_SAFETY_LIMIT:,} of {len(matches):,} results — "
                f"narrow the path or pattern]"
            )
        return "\n".join(lines)
