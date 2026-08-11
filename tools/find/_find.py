from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_MAX_RESULTS = 500


class FindTool(BaseTool):
    name = "find"
    description = (
        "Find files by glob pattern. Returns matching file paths "
        "relative to the project root. Use '**/*.py' for recursive searches."
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

        all_matches: list[Path] = []
        for p in sorted(search_path.glob(pattern)):
            rp = p.resolve()
            all_matches.append(p)

        if not all_matches:
            return "[no matches]"

        lines = []
        for p in all_matches[:_MAX_RESULTS]:
            try:
                rel = p.relative_to(self.cwd)
            except ValueError:
                rel = p
            lines.append(str(rel))

        if len(all_matches) > _MAX_RESULTS:
            lines.append(
                f"[truncated — showing first {_MAX_RESULTS} "
                f"of {len(all_matches)} results]"
            )
        return "\n".join(lines)
