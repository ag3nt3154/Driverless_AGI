"""tools/read/_source.py — Load a file as lines for read and read_large_file.

Plain text is decoded as UTF-8; .pdf/.docx/.xlsx/.pptx go through the document
converter service and come back as markdown. Both tools share this loader so
line numbers in a truncated read match the ones read_large_file reports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.read._doc_service import cache_path_for, convert_document, DocServiceError

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
BLOCKED_EXTS = _IMAGE_EXTS.copy()
DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}
_PAGE_MARKER_RE = re.compile(r"<!-- Page (\d+) -->")


class SourceError(Exception):
    """A file could not be loaded; str(exc) is the agent-facing message."""


@dataclass(frozen=True)
class LoadedSource:
    """All lines of a file (after document conversion / page filtering)."""
    path: Path
    lines: list[str]
    header: str | None
    editable_path: Path | None
    is_pdf: bool


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


def load_source(
    p: Path,
    *,
    pages: str | None,
    service_url: str | None,
    project_path: Path | None,
) -> LoadedSource:
    """Load ``p`` (already path-validated) as lines. Raises SourceError."""
    ext = p.suffix.lower()

    if pages is not None and ext != ".pdf":
        raise SourceError("Error: 'pages' parameter is only supported for PDF files.")

    if ext in BLOCKED_EXTS:
        raise SourceError(
            f"Error: Cannot read file type '{ext}'. This file type is not "
            f"currently supported by the read tool."
        )

    if ext not in DOC_EXTS:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            raise SourceError(
                f"Error: Cannot read '{p.name}' as text. The file appears "
                f"to be binary or uses an encoding other than UTF-8."
            )
        return LoadedSource(path=p, lines=lines, header=None, editable_path=None, is_pdf=False)

    if not service_url or not project_path:
        raise SourceError(
            "Error: Document reading requires the converter service. "
            "Ensure services.doc_converter is configured in .dagi/config.yaml."
        )
    try:
        md_text = convert_document(p, service_url, project_path)
    except DocServiceError as exc:
        raise SourceError(f"Error from document service ({exc.code}): {exc.message}")

    editable_path = cache_path_for(p, project_path)
    try:
        editable_str = str(editable_path.relative_to(project_path))
    except ValueError:
        editable_str = str(editable_path)

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

    return LoadedSource(
        path=p, lines=md_text.splitlines(), header=header,
        editable_path=editable_path, is_pdf=ext == ".pdf",
    )
