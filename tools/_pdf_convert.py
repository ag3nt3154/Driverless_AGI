"""tools/_pdf_convert.py — PDF-to-markdown conversion with caching.

Digital-native PDFs are converted via docling (TableFormer for tables).
Scanned PDFs are first OCR'd via ocrmypdf (tesseract), then converted via docling.
All four dependencies (docling, pymupdf, ocrmypdf, tesseract) are optional;
the tool degrades gracefully with friendly error messages.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from agent.config_loader import load_pdf_config
from tools._hash_cache import cache_path, get_or_compute


def parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like '1-3,5,8-10' into a set of 1-indexed page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
    return pages


_SCANNED_CHAR_THRESHOLD = 50


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 3) -> bool:
    """Probe first N pages for extractable text. Returns True if scanned."""
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open(str(pdf_path))
    pages_to_check = min(sample_pages, len(doc))
    total_chars = sum(len(doc[i].get_text()) for i in range(pages_to_check))
    doc.close()
    return total_chars < _SCANNED_CHAR_THRESHOLD


def _get_page_count(pdf_path: Path) -> int:
    """Return the page count of a PDF, or 0 if fitz is unavailable."""
    try:
        import fitz
    except ImportError:
        return 0
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def _estimate_worker_count(page_count: int) -> int:
    """Estimate a safe worker-process count from CPU count, free RAM, and page count.

    page_count caps workers 1:1 -- no point having more workers than pages to split.
    """
    cfg = load_pdf_config()
    caps = [os.cpu_count() or 1, page_count]

    try:
        import psutil
        available_bytes = psutil.virtual_memory().available
        caps.append(int(available_bytes // (cfg.worker_ram_gb * 1024**3)))
    except ImportError:
        pass

    if cfg.max_workers is not None:
        caps.append(cfg.max_workers)

    return max(1, min(caps))


def _convert_pdf_digital(pdf_path: Path) -> str:
    """Convert a digital-native PDF to markdown via docling."""
    try:
        from docling.document_converter import DocumentConverter
    except ImportError:
        raise RuntimeError(
            "docling is not installed. Install it with: pip install docling"
        )
    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    return result.document.export_to_markdown()


def _convert_pdf_scanned(pdf_path: Path, cache_dir: Path) -> str:
    """OCR a scanned PDF via ocrmypdf, then convert via docling."""
    try:
        import ocrmypdf
    except ImportError:
        return _convert_pdf_digital(pdf_path)

    searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"
    try:
        ocrmypdf.ocr(
            str(pdf_path),
            str(searchable_path),
            skip_text=True,
            force_ocr=False,
        )
        return _convert_pdf_digital(searchable_path)
    finally:
        searchable_path.unlink(missing_ok=True)


def convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    """Convert a PDF to markdown, using the shared hash cache.

    Returns (markdown_text, cache_file_path).
    """
    key = pdf_path.read_bytes()

    def compute() -> str:
        cache_dir = cache_path(key, "pdf", "md", project_root)[0].parent
        if is_scanned_pdf(pdf_path):
            return _convert_pdf_scanned(pdf_path, cache_dir)
        return _convert_pdf_digital(pdf_path)

    return get_or_compute(key, "pdf", "md", project_root, compute)


def select_pages(markdown: str, pages_spec: str) -> str:
    """Filter cached markdown by page markers (<!-- Page N -->)."""
    requested = parse_page_spec(pages_spec)
    sections = re.split(r"(<!-- Page \d+ -->)", markdown)

    result_parts: list[str] = []
    current_page = 0
    for section in sections:
        page_match = re.match(r"<!-- Page (\d+) -->", section)
        if page_match:
            current_page = int(page_match.group(1))
            if current_page in requested:
                result_parts.append(section)
        elif current_page in requested:
            result_parts.append(section)

    return "".join(result_parts)
