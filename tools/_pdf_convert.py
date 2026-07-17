"""tools/_pdf_convert.py — PDF-to-markdown conversion with caching.

Digital-native PDFs are converted via docling (TableFormer for tables).
Scanned PDFs are first OCR'd via ocrmypdf (tesseract), then converted via docling.
All four dependencies (docling, pymupdf, ocrmypdf, tesseract) are optional;
the tool degrades gracefully with friendly error messages.
"""
from __future__ import annotations

import re
from pathlib import Path


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
