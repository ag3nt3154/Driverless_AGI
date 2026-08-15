"""Read tool — text files inline, documents via converter service."""
import re
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path
from tools.read._doc_service import cache_path_for, convert_document, DocServiceError

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_BLOCKED_EXTS = _IMAGE_EXTS.copy()
_DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}
_PAGE_MARKER_RE = re.compile(r"<!-- Page (\d+) -->")


def _parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like '1-3,5,8-10' into a set of page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError:
                raise ValueError(f"Invalid page spec: {spec!r}")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid page spec: {spec!r}")
    return pages


def _select_pages(md_text: str, page_spec: str) -> str:
    """Filter markdown to only include the specified pages."""
    wanted = _parse_page_spec(page_spec)
    sections = _PAGE_MARKER_RE.split(md_text)
    result_parts: list[str] = []
    i = 1
    while i < len(sections):
        page_num = int(sections[i])
        content = sections[i + 1] if i + 1 < len(sections) else ""
        if page_num in wanted:
            result_parts.append(f"<!-- Page {page_num} -->{content}")
        i += 2
    return "".join(result_parts)


class ReadTool(BaseTool):
    name = "read"
    description = (
        "Read the contents of a file. Supports all text files (any extension) — "
        "attempts UTF-8 decoding. Defaults to first 2000 lines. "
        ".docx, .xlsx, .pptx, and .pdf files are converted to markdown via the "
        "document converter service (must be running). "
        "Use the optional `pages` parameter to select specific PDF pages. "
        "Use offset/limit for large files. Accepts both relative paths "
        "(resolved from the project root) and absolute paths. "
        "Output uses `cat -n` style: each line is prefixed with its 1-indexed "
        "line number followed by a tab — the number is not part of the file content. "
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
                "description": "Maximum number of lines to read",
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
    ):
        self.cwd = cwd
        self.allowed_roots = allowed_roots
        self._project_path = project_path
        self._service_url = service_url

    def run(
        self,
        path: str,
        offset: int = 1,
        limit: int = 2000,
        pages: str | None = None,
    ) -> str | list:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        ext = p.suffix.lower()

        if pages is not None and ext != ".pdf":
            return "Error: 'pages' parameter is only supported for PDF files."

        if ext in _BLOCKED_EXTS:
            return (
                f"Error: Cannot read file type '{ext}'. This file type is not "
                f"currently supported by the read tool."
            )

        header = None

        if ext in _DOC_EXTS:
            if not self._service_url or not self._project_path:
                return (
                    "Error: Document reading requires the converter service. "
                    "Ensure services.doc_converter is configured in .dagi/config.yaml."
                )
            try:
                md_text = convert_document(p, self._service_url, self._project_path)
            except DocServiceError as exc:
                return f"Error from document service ({exc.code}): {exc.message}"

            editable = cache_path_for(p, self._project_path)
            try:
                editable_str = str(editable.relative_to(self._project_path))
            except ValueError:
                editable_str = str(editable)

            if ext == ".pdf":
                total_pages = md_text.count("<!-- Page ")
                if pages:
                    md_text = _select_pages(md_text, pages)
                header = f"[PDF: {p.name} | {total_pages} pages"
                if pages:
                    header += f" | showing pages {pages}"
                header += f" | editable: {editable_str}]"
            else:
                header = f"[{p.name} | editable: {editable_str}]"

            lines = md_text.splitlines()

        else:
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                return (
                    f"Error: Cannot read '{p.name}' as text. The file appears "
                    f"to be binary or uses an encoding other than UTF-8."
                )

        start = max(0, offset - 1)
        selected = lines[start : start + limit]
        numbered = "\n".join(
            f"{i:6d}\t{line}" for i, line in enumerate(selected, start + 1)
        )

        raw_result = f"{header}\n{numbered}" if header else numbered

        return raw_result
