"""Document conversion dispatch — auto-detects format from filename."""
from __future__ import annotations

from pathlib import Path

_DOC_EXTS = {".docx", ".xlsx", ".pptx"}
_PDF_EXT = ".pdf"
_SUPPORTED = _DOC_EXTS | {_PDF_EXT}


def convert(path: Path) -> str:
    """Convert a document file to markdown text.

    Raises:
        ValueError: unsupported format
        RuntimeError: conversion failure
    """
    ext = path.suffix.lower()
    if ext not in _SUPPORTED:
        raise ValueError(f"Unsupported file format: {ext}")

    if ext == _PDF_EXT:
        from services.doc_converter.converter.pdf import convert_pdf
        return convert_pdf(path)

    from services.doc_converter.converter.office import convert_office
    return convert_office(path)
