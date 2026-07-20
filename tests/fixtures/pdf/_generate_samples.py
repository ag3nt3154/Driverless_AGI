"""Generate sample_digital.pdf and sample_scanned.pdf for manual read-tool testing.

sample_digital.pdf: real text layer + a simple table, built directly with
PyMuPDF -- exercises the docling "digital" conversion path (do_ocr=False).

sample_scanned.pdf: same content rendered to raster images and inserted
with no text layer -- exercises is_scanned_pdf() detection and the
ocrmypdf (tesseract) -> docling path.

Run once with: python tests/fixtures/pdf/_generate_samples.py
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).parent

PAGE1_TITLE = "Sample Digital Document"
PAGE1_BODY = (
    "This is a synthetic PDF used to test the DAGI read tool's digital-native "
    "PDF conversion path (docling, do_ocr=False).\n\n"
    "It contains an extractable text layer, so is_scanned_pdf() should "
    "classify it as NOT scanned."
)
TABLE_HEADERS = ["Item", "Quantity", "Price"]
TABLE_ROWS = [
    ["Widget", "12", "$4.50"],
    ["Gadget", "3", "$19.99"],
    ["Gizmo", "7", "$8.25"],
]
PAGE2_BODY = "Second page of the digital sample, to verify multi-page <!-- Page N --> markers."


def _draw_table(page: fitz.Page, origin: tuple[float, float]) -> None:
    x0, y0 = origin
    col_w = [120, 80, 80]
    row_h = 22
    rows = [TABLE_HEADERS] + TABLE_ROWS
    for r, row in enumerate(rows):
        x = x0
        y = y0 + r * row_h
        for c, cell in enumerate(row):
            rect = fitz.Rect(x, y, x + col_w[c], y + row_h)
            page.draw_rect(rect, color=(0, 0, 0), width=0.7)
            page.insert_textbox(
                rect + (4, 4, -4, -4), cell, fontsize=10,
                fontname="helv", align=0,
            )
            x += col_w[c]


def build_digital_pdf(path: Path) -> None:
    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), PAGE1_TITLE, fontsize=18, fontname="helv")
    page1.insert_textbox(
        fitz.Rect(72, 100, 520, 220), PAGE1_BODY, fontsize=11, fontname="helv",
    )
    _draw_table(page1, (72, 240))

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Page 2", fontsize=18, fontname="helv")
    page2.insert_textbox(fitz.Rect(72, 100, 520, 200), PAGE2_BODY, fontsize=11, fontname="helv")

    doc.save(str(path))
    doc.close()


def build_scanned_pdf(digital_path: Path, path: Path) -> None:
    """Rasterize the digital PDF's pages into an image-only PDF (no text layer).

    This mimics a real scanned document: pixels only, nothing extractable via
    get_text(), so is_scanned_pdf() must return True and the ocrmypdf/tesseract
    path must recover the text via OCR.
    """
    src = fitz.open(str(digital_path))
    out = fitz.open()
    zoom = 2.0  # ~144 DPI, enough for tesseract to read cleanly
    mat = fitz.Matrix(zoom, zoom)
    for src_page in src:
        pix = src_page.get_pixmap(matrix=mat)
        img_page = out.new_page(width=pix.width, height=pix.height)
        img_page.insert_image(img_page.rect, pixmap=pix)
    out.save(str(path))
    out.close()
    src.close()


def main() -> None:
    digital_path = HERE / "sample_digital.pdf"
    scanned_path = HERE / "sample_scanned.pdf"
    build_digital_pdf(digital_path)
    build_scanned_pdf(digital_path, scanned_path)
    print("wrote", digital_path)
    print("wrote", scanned_path)


if __name__ == "__main__":
    main()
