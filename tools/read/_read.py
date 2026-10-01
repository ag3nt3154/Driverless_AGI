"""Read tool — text files inline, documents via converter service.

Results too large for context are cut to head + marker + tail; the marker
points the agent at read(offset/limit), grep, or read_large_file.
"""
from __future__ import annotations

from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path
from tools._truncate import DEFAULT_EDGE_CHARS, effective_edge_chars, truncate_middle
from tools.output_filter import estimate_tool_output
from tools.read._source import SourceError, load_source


def _render_numbered(selected: list[str], start_idx: int, header: str | None) -> str:
    """Render lines in cat-n format with optional document header."""
    numbered = "\n".join(
        f"{i:6d}\t{line}" for i, line in enumerate(selected, start_idx + 1)
    )
    return f"{header}\n{numbered}" if header else numbered


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Reads the whole file unless offset/limit are given. "
        ".docx, .xlsx, .pptx, and .pdf files are converted to markdown via the "
        "document converter service (must be running). "
        "Use the optional `pages` parameter to select specific PDF pages. "
        "Accepts both relative paths (resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
        "If the result is too large for context, only the start and end are shown "
        "with a marker giving the omitted line range; then read a range with "
        "offset/limit, grep for what you need, or call read_large_file for an "
        "indexed digest of the whole file. "
        "For large-scale codebase exploration, prefer `explore_files`."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read (relative to project root, or absolute)",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (default: to end of file)",
            },
            "pages": {
                "type": "string",
                "description": (
                    "Page range for PDF files (e.g. '1-5', '3', '10-12,15'). "
                    "Only applicable to PDFs. Selects which pages of the converted "
                    "markdown to return. Omit to return all pages."
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        cwd: Path = Path("."),
        allowed_roots: list[Path] | None = None,
        project_path: Path | None = None,
        service_url: str | None = None,
        reserve_tokens: int = 0,
        edge_chars: int = DEFAULT_EDGE_CHARS,
    ):
        self.cwd = cwd
        self.allowed_roots = allowed_roots
        self._project_path = project_path
        self._service_url = service_url
        self._reserve_tokens = reserve_tokens
        self._edge_chars = edge_chars

    def run(
        self,
        path: str,
        offset: int = 1,
        limit: int | None = None,
        pages: str | None = None,
    ) -> str | list:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        try:
            src = load_source(
                p, pages=pages, service_url=self._service_url,
                project_path=self._project_path,
            )
        except (SourceError, ValueError) as exc:
            return str(exc)

        start = max(0, offset - 1)
        end = len(src.lines) if limit is None else start + max(0, limit)
        selected = src.lines[start:end]
        raw_result = _render_numbered(selected, start, src.header)

        P = self._reserve_tokens
        if P <= 0 or estimate_tool_output(raw_result) < P:
            return raw_result

        hint = "For PDFs, `pages` narrows the selection." if src.is_pdf else ""
        return truncate_middle(
            selected,
            source=str(p),
            edge_chars=effective_edge_chars(self._edge_chars, P),
            line_offset=start + 1,
            total_lines=len(src.lines),
            numbered=True,
            header=src.header,
            hint=hint,
        )
