import re
import subprocess
import time
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path

_MAX_RESULTS = 200
_FALLBACK_TIMEOUT = 15  # seconds — wall-clock cap for the Python fallback

_EXCLUDED_DIRS = {
    '.git', '.dagi', '__pycache__', '.mypy_cache', '.pytest_cache',
    'node_modules', '.tox', '.venv', 'venv',
}
_EXCLUDED_EXTS = {'.pyc', '.pyo', '.pyd', '.so', '.dll', '.exe', '.bin', '.whl', '.egg'}


def _is_visible(parts: tuple[str, ...]) -> bool:
    """Exclude dot-dirs, __pycache__, and binary artifacts."""
    for p in parts:
        if p in _EXCLUDED_DIRS:
            return False
        if p.startswith(".") and p != '.index.md':
            return False
    return True


def _is_binary_ext(path: Path) -> bool:
    return path.suffix.lower() in _EXCLUDED_EXTS


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a pattern in files using ripgrep (rg). "
        "This is your ONLY search tool — NEVER use bash findstr/grep/rg directly. "
        "Returns matching lines with file:line format. "
        "Automatically excludes binary files (.pyc, .pyo, .bin), "
        "__pycache__, .git, .dagi, and other non-source directories. "
        "IMPORTANT: 'path' must be a specific subdirectory or file, NOT '.' — "
        "narrow searches to the relevant directory (e.g. 'src/', 'tools/') to "
        "avoid excessive output. Use 'glob' to further filter by file type."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern (or literal string) to search for"},
            "path": {
                "type": "string",
                "description": (
                    "File or directory to search. Must be a specific path — "
                    "do NOT pass '.' or the project root. Narrow to the relevant "
                    "subdirectory (e.g. 'agent/', 'tools/', 'src/')."
                ),
            },
            "glob": {"type": "string", "description": "Glob pattern to filter files (e.g. '*.py', '**/*.ts')"},
            "literal": {"type": "boolean", "description": "Treat pattern as a literal string, not regex (default: false)"},
        },
        "required": ["pattern", "path"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(
        self,
        pattern: str,
        path: str,
        glob: str | None = None,
        literal: bool = False,
    ) -> str:
        sp = Path(path)
        if not sp.is_absolute():
            sp = self.cwd / sp
        search_path = validate_path(sp, self.allowed_roots)

        lines = self._search_one(pattern, search_path, glob, literal)
        if len(lines) > _MAX_RESULTS:
            lines = lines[:_MAX_RESULTS]
            lines.append(f"[truncated — showing first {_MAX_RESULTS} results]")
        return "\n".join(lines) if lines else "[no matches]"

    @staticmethod
    def _enumerate_files(
        search_path: Path, glob_pat: str | None, deadline: float,
    ):
        """Yield files under *search_path*, aborting if *deadline* is passed."""
        source = (
            search_path.rglob(glob_pat) if glob_pat
            else search_path.rglob("*")
        )
        for p in source:
            if time.monotonic() > deadline:
                return
            if not p.is_file():
                continue
            if _is_binary_ext(p):
                continue
            parts = p.relative_to(search_path).parts
            if glob_pat:
                if _is_visible(parts):
                    yield p
                continue
            if _is_visible(parts):
                yield p

    def _search_one(
        self,
        pattern: str,
        search_path: Path,
        glob: str | None,
        literal: bool,
    ) -> list[str]:
        # ── Try ripgrep first ─────────────────────────────────────────────
        try:
            cmd = [
                "rg", "--line-number", "--no-heading", "--color=never",
                "--no-ignore",
            ]
            for d in sorted(_EXCLUDED_DIRS):
                cmd += ["--glob", f"!{d}"]
            for ext in sorted(_EXCLUDED_EXTS):
                cmd += ["--glob", f"!*{ext}"]
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
            flags = 0
            rx = re.compile(re.escape(pattern) if literal else pattern, flags)
        except re.error as e:
            return [f"Error: invalid regex pattern: {e}"]

        deadline = time.monotonic() + _FALLBACK_TIMEOUT
        if search_path.is_file():
            files = [search_path]
        else:
            files = list(self._enumerate_files(
                search_path, glob, deadline,
            ))

        results: list[str] = []
        for fpath in files:
            if time.monotonic() > deadline:
                results.append(
                    f"[timeout — Python fallback exceeded {_FALLBACK_TIMEOUT}s, "
                    "install ripgrep (rg) for faster searches]"
                )
                break
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    rel = (
                        fpath.relative_to(self.cwd)
                        if fpath.is_relative_to(self.cwd)
                        else fpath
                    )
                    results.append(f"{rel}:{lineno}: {line}")
        return results
