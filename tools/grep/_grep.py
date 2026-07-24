import re
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_MAX_RESULTS = 200
_DEFAULT_PATH = object()  # sentinel: "no path given" → search all allowed_roots
_HIDDEN_WHITELIST = {'.dagi', '.index.md'}


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a pattern in files using regex or literal match. "
        "Returns matching lines with file:line format. "
        "Paths are relative to the project root. Uses ripgrep (rg) if available. "
        "When no path is given, searches across all configured search roots."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern (or literal string) to search for"},
            "path": {"type": "string", "description": "File or directory to search (default: all search roots)"},
            "glob": {"type": "string", "description": "Glob pattern to filter files (e.g. '*.py', '**/*.ts')"},
            "literal": {"type": "boolean", "description": "Treat pattern as a literal string, not regex (default: false)"},
        },
        "required": ["pattern"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(
        self,
        pattern: str,
        path: str | object = _DEFAULT_PATH,
        glob: str | None = None,
        literal: bool = False,
    ) -> str:
        if path is _DEFAULT_PATH:
            search_paths = list(self.allowed_roots) if self.allowed_roots is not None else [self.cwd]
        else:
            sp = Path(str(path))
            if not sp.is_absolute():
                sp = self.cwd / sp
            search_paths = [validate_path(sp, self.allowed_roots)]

        all_lines: list[str] = []
        for search_path in search_paths:
            lines = self._search_one(pattern, search_path, glob, literal)
            all_lines.extend(lines)
            if len(all_lines) >= _MAX_RESULTS:
                break

        if len(all_lines) > _MAX_RESULTS:
            all_lines = all_lines[:_MAX_RESULTS]
            all_lines.append(f"[truncated — showing first {_MAX_RESULTS} results]")
        return "\n".join(all_lines) if all_lines else "[no matches]"

    def _search_one(
        self,
        pattern: str,
        search_path: Path,
        glob: str | None,
        literal: bool,
    ) -> list[str]:
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
                return result.stdout.splitlines()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # rg not available, fall back to Python

        # ── Python fallback ────────────────────────────────────────────────
        try:
            flags = re.IGNORECASE if not literal else 0
            rx = re.compile(re.escape(pattern) if literal else pattern, flags)
        except re.error as e:
            return [f"Error: invalid regex pattern: {e}"]

        if search_path.is_file():
            files = [search_path]
        else:
            if glob:
                files = sorted(search_path.rglob(glob))
            else:
                files = sorted(
                    p for p in search_path.rglob("*")
                    if p.is_file() and (
                        p.relative_to(search_path).parts[0] == ".dagi"
                        or not any(
                            part.startswith(".") and part not in _HIDDEN_WHITELIST
                            for part in p.relative_to(search_path).parts
                        )
                    )
                )

        results: list[str] = []
        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    rel = fpath.relative_to(self.cwd) if fpath.is_relative_to(self.cwd) else fpath
                    results.append(f"{rel}:{lineno}: {line}")
        return results
