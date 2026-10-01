"""tools/read/_source.py — Load a file as lines for read and read_large_file.

Plain text is decoded as UTF-8; .pdf/.docx/.xlsx/.xls/.pptx are converted to
markdown (tools/read/_convert.py). Images are not text: the read tool attaches
them for the model instead (tools/read/_image.py). Both tools share this loader so
line numbers in a truncated read match the ones read_large_file reports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.read._convert import CANNOT_PROCESS, DOC_EXTS, ConversionError, convert_document
from tools.read._image import IMAGE_EXTS
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

    if ext in IMAGE_EXTS:
        raise SourceError(
            f"Error ({CANNOT_PROCESS}): '{p.name}' is an image, not text. "
            f"Use the read tool to view it with a multimodal model."
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

    try:
        conv = convert_document(p, service_url=service_url, project_path=project_path)
    except ConversionError as exc:
        raise SourceError(f"Error ({exc.code}): {exc.message}")

    md_text = conv.markdown
    fields = [p.name]
    if ext == ".pdf":
        total_pages = md_text.count("<!-- Page ")
        if pages:
            if not total_pages:
                raise SourceError(
                    f"Error: '{p.name}' was converted without page markers, so "
                    f"'pages' cannot select from it. Use offset/limit instead."
                )
            md_text = _select_pages(md_text, pages)
        fields = [f"PDF: {p.name}"]
        if total_pages:
            fields.append(f"{total_pages} pages")
        if pages:
            fields.append(f"showing pages {pages}")
        if conv.fallback_reason:
            fields.append(f"converted by markitdown ({conv.fallback_reason})")
    if conv.cache_file is not None:
        try:
            editable_str = str(conv.cache_file.relative_to(project_path))
        except ValueError:
            editable_str = str(conv.cache_file)
        fields.append(f"editable: {editable_str}")
    header = "[" + " | ".join(fields) + "]"

    return LoadedSource(
        path=p, lines=md_text.splitlines(), header=header,
        editable_path=conv.cache_file, is_pdf=ext == ".pdf",
    )
