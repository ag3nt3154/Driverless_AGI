from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_MAX_RESULTS = 500
_DEFAULT_PATH = object()  # sentinel: "no path given" → search all allowed_roots


class FindTool(BaseTool):
    name = "find"
    description = (
        "Find files by glob pattern. Returns matching file paths relative to the project root. "
        "Use '**/*.py' for recursive searches. "
        "When no path is given, searches across all configured search roots."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match (e.g. '**/*.py', 'src/*.ts', '*.md')"},
            "path": {"type": "string", "description": "Directory to search within (default: all search roots)"},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots or [cwd]

    def run(self, pattern: str, path: str | object = _DEFAULT_PATH) -> str:
        if path is _DEFAULT_PATH:
            search_paths = list(self.allowed_roots)
        else:
            sp = Path(str(path))
            if not sp.is_absolute():
                sp = self.cwd / sp
            search_paths = [validate_path(sp, self.allowed_roots)]

        all_matches: list[Path] = []
        seen: set[Path] = set()
        for search_path in search_paths:
            if not search_path.exists():
                continue
            for p in sorted(search_path.glob(pattern)):
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    all_matches.append(p)

        if not all_matches:
            return "[no matches]"

        lines = []
        for p in all_matches[:_MAX_RESULTS]:
            try:
                rel = p.relative_to(self.cwd)
            except ValueError:
                rel = p  # outside cwd — show absolute path
            lines.append(str(rel))

        if len(all_matches) > _MAX_RESULTS:
            lines.append(f"[truncated — showing first {_MAX_RESULTS} of {len(all_matches)} results]")
        return "\n".join(lines)
