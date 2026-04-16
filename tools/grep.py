import re
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_MAX_RESULTS = 200


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a pattern in files using regex or literal match. "
        "Returns matching lines with file:line format. "
        "Paths are relative to the project root. Uses ripgrep (rg) if available."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern (or literal string) to search for"},
            "path": {"type": "string", "description": "File or directory to search (default: project root)"},
            "glob": {"type": "string", "description": "Glob pattern to filter files (e.g. '*.py', '**/*.ts')"},
            "literal": {"type": "boolean", "description": "Treat pattern as a literal string, not regex (default: false)"},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots or [cwd]

    def run(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        literal: bool = False,
    ) -> str:
        search_path = Path(path)
        if not search_path.is_absolute():
            search_path = self.cwd / search_path
        search_path = validate_path(search_path, self.allowed_roots)

        # ── Try ripgrep first ─────────────────────────────────────────────
        try:
            cmd = ["rg", "--line-number", "--no-heading", "--color=never"]
            if literal:
                cmd.append("--fixed-strings")
            if glob:
                cmd += ["--glob", glob]
            cmd += [pattern, str(search_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode in (0, 1):  # 0 = matches, 1 = no matches
                lines = result.stdout.splitlines()
                if len(lines) > _MAX_RESULTS:
                    lines = lines[:_MAX_RESULTS]
                    lines.append(f"[truncated — showing first {_MAX_RESULTS} results]")
                return "\n".join(lines) if lines else "[no matches]"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # rg not available, fall back to Python

        # ── Python fallback ────────────────────────────────────────────────
        try:
            flags = re.IGNORECASE if not literal else 0
            rx = re.compile(re.escape(pattern) if literal else pattern, flags)
        except re.error as e:
            return f"Error: invalid regex pattern: {e}"

        results: list[str] = []
        target = search_path if search_path.is_file() else None

        if search_path.is_file():
            files = [search_path]
        else:
            if glob:
                files = sorted(search_path.rglob(glob))
            else:
                files = sorted(
                    p for p in search_path.rglob("*")
                    if p.is_file() and not any(
                        part.startswith(".") for part in p.parts
                    )
                )

        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    rel = fpath.relative_to(self.cwd) if fpath.is_relative_to(self.cwd) else fpath
                    results.append(f"{rel}:{lineno}: {line}")
                    if len(results) >= _MAX_RESULTS:
                        results.append(f"[truncated — showing first {_MAX_RESULTS} results]")
                        return "\n".join(results)

        return "\n".join(results) if results else "[no matches]"
