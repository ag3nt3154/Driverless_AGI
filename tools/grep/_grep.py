import json
import re
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool
from tools import _hashline as H
from tools._path_guard import validate_path

_MAX_RESULTS = 200
_DEFAULT_PATH = object()  # sentinel: "no path given" → search all allowed_roots
_HIDDEN_WHITELIST = {'.dagi', '.index.md'}


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search for a pattern in files using regex or literal match. "
        "Returns matches as `path:LINE#HASH:content`, where LINE#HASH is a "
        "verified anchor that can be passed straight to `edit` without reading "
        "the file first. A match rendered as `path:LINE: content` (no #) means "
        "the file could not be decoded as UTF-8 — read it before editing. "
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

        matches: list[tuple[Path, int, str]] = []
        for search_path in search_paths:
            matches.extend(self._search_one(pattern, search_path, glob, literal))
            if len(matches) >= _MAX_RESULTS:
                break

        truncated = len(matches) > _MAX_RESULTS
        rendered = self._render(matches[:_MAX_RESULTS])
        if truncated:
            rendered.append(f"[truncated — showing first {_MAX_RESULTS} results]")
        return "\n".join(rendered) if rendered else "[no matches]"

    def _search_one(
        self,
        pattern: str,
        search_path: Path,
        glob: str | None,
        literal: bool,
    ) -> list[tuple[Path, int, str]]:
        # ── Try ripgrep first ─────────────────────────────────────────────
        try:
            cmd = ["rg", "--json"]
            if literal:
                cmd.append("--fixed-strings")
            if glob:
                cmd += ["--glob", glob]
            cmd += [pattern, str(search_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode in (0, 1):  # 0 = matches, 1 = no matches
                return _parse_rg_json(result.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # rg not available, fall back to Python

        # ── Python fallback ────────────────────────────────────────────────
        try:
            flags = re.IGNORECASE if not literal else 0
            rx = re.compile(re.escape(pattern) if literal else pattern, flags)
        except re.error as e:
            return [(search_path, 0, f"Error: invalid regex pattern: {e}")]

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

        results: list[tuple[Path, int, str]] = []
        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    results.append((fpath, lineno, line))
        return results

    def _render(self, matches: list[tuple[Path, int, str]]) -> list[str]:
        """Group by file so each file is read and hashed exactly once."""
        by_file: dict[Path, list[tuple[int, str]]] = {}
        for fpath, lineno, content in matches:
            by_file.setdefault(fpath, []).append((lineno, content))

        out: list[str] = []
        for fpath, hits in by_file.items():
            anchors = _anchors_for(fpath)
            try:
                rel = fpath.relative_to(self.cwd)
            except ValueError:
                rel = fpath
            for lineno, content in hits:
                if anchors is not None and 1 <= lineno <= len(anchors):
                    out.append(f"{rel}:{lineno}#{anchors[lineno - 1]}:{content}")
                else:
                    out.append(f"{rel}:{lineno}: {content}")
        return out


def _parse_rg_json(stdout: str) -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for raw in stdout.splitlines():
        try:
            obj = json.loads(raw)
        except ValueError:
            continue
        if obj.get("type") != "match":
            continue
        data = obj["data"]
        text = data.get("path", {}).get("text")
        if text is None:
            continue
        out.append((Path(text), data["line_number"], data["lines"]["text"].rstrip("\n")))
    return out


def _anchors_for(fpath: Path) -> list[str] | None:
    """Anchors for a file, or None if it is not strictly UTF-8 decodable.

    Anchors must only ever come from a strict UTF-8 read: hashing lossily
    decoded text would produce anchors that can never match edit's table.
    """
    try:
        return H.build_anchors(fpath.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return None
