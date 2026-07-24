"""Convert docx/xlsx/pptx files to markdown via markitdown."""
from __future__ import annotations

from pathlib import Path


def convert_office(path: Path) -> str:
    """Convert a docx/xlsx/pptx file to markdown text."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        raise RuntimeError(
            "markitdown is not installed in the doc_converter environment."
        )
    result = MarkItDown().convert(str(path))
    return result.text_content
