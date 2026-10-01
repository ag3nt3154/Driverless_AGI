"""tools/read/_convert.py — document → markdown for the read tool.

Office files (.docx/.xlsx/.xls/.pptx) are converted in-process by markitdown.
PDFs go through a two-tier chain: the custom conversion API first (when
``services.doc_converter`` is configured), then markitdown. When neither
can produce text, ConversionError carries the DAGI_CANNOT_PROCESS code; the
read tool returns that as an ordinary tool result, so the agent loop goes on.

Results are cached in the shared hash cache keyed on file content. The API
and markitdown outputs live in separate subdirs so a markitdown fallback
never shadows the API's result once the service is reachable again.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tools._hash_cache import get_or_compute
from tools.read._doc_service import DocServiceError, post_for_conversion

CANNOT_PROCESS = "DAGI_CANNOT_PROCESS"

PDF_EXT = ".pdf"
OFFICE_EXTS = {".docx", ".xlsx", ".xls", ".pptx"}
DOC_EXTS = OFFICE_EXTS | {PDF_EXT}

# doc_convert/ keeps the layout the service-backed cache always used, so
# entries written before markitdown moved in-process stay valid.
_PRIMARY_SUBDIR = "doc_convert"
_PDF_FALLBACK_SUBDIR = "doc_convert_markitdown"


class ConversionError(Exception):
    """No converter could turn the document into text."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class Converted:
    markdown: str
    cache_file: Path | None
    # Why the API was skipped for a PDF it was configured for, else None.
    fallback_reason: str | None = None


def _mark_pdf_pages(text: str) -> str:
    """Turn pdfminer's form-feed page breaks into ``<!-- Page N -->`` markers.

    markitdown's form/table extraction path joins pages without a separator;
    that output is returned unmarked and page selection is unavailable.
    """
    if "\f" not in text:
        return text
    pages = text.split("\f")
    if not pages[-1].strip():
        pages.pop()
    return "".join(f"<!-- Page {i} -->\n{page.strip()}\n\n" for i, page in enumerate(pages, 1))


def _markitdown(path: Path) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise ConversionError(
            CANNOT_PROCESS,
            f"Cannot convert '{path.name}': markitdown is not installed. "
            f"Install it with: pip install \"markitdown[pdf,docx,pptx,xlsx,xls]\"",
        )
    try:
        text = MarkItDown().convert(str(path)).text_content
    except Exception as exc:
        raise ConversionError(
            CANNOT_PROCESS, f"markitdown could not convert '{path.name}': {exc}",
        )
    if path.suffix.lower() == PDF_EXT:
        text = _mark_pdf_pages(text)
    return text


def _cached(
    data: bytes, subdir: str, project_path: Path | None, compute: Callable[[], str],
) -> tuple[str, Path | None]:
    if project_path is None:
        return compute(), None
    return get_or_compute(data, subdir, "md", project_path, compute)


def convert_document(
    path: Path, *, service_url: str | None, project_path: Path | None,
) -> Converted:
    """Convert ``path`` to markdown, consulting the hash cache first.

    Without ``project_path`` nothing is cached (and there is no editable copy).
    Raises ConversionError when every applicable converter fails.
    """
    data = path.read_bytes()
    is_pdf = path.suffix.lower() == PDF_EXT

    fallback_reason = None
    if is_pdf and service_url:
        try:
            md, cache_file = _cached(
                data, _PRIMARY_SUBDIR, project_path,
                lambda: post_for_conversion(data, path.name, service_url),
            )
            return Converted(md, cache_file)
        except DocServiceError as exc:
            fallback_reason = f"conversion service {exc.code}: {exc.message}"

    subdir = _PDF_FALLBACK_SUBDIR if is_pdf else _PRIMARY_SUBDIR
    try:
        md, cache_file = _cached(data, subdir, project_path, lambda: _markitdown(path))
    except ConversionError as exc:
        if fallback_reason:
            raise ConversionError(exc.code, f"{exc.message} (after {fallback_reason})")
        raise
    return Converted(md, cache_file, fallback_reason)
