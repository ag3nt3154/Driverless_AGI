"""Tests for the document conversion chain (tools/read/_convert.py)."""
import hashlib
from unittest.mock import patch

import pytest

from tools.read._convert import (
    CANNOT_PROCESS, ConversionError, _mark_pdf_pages, convert_document,
)
from tools.read._doc_service import DocServiceError

URL = "http://localhost:8100"


def _doc(tmp_path, name, data=b"fake bytes"):
    f = tmp_path / name
    f.write_bytes(data)
    return f


def _cache_file(tmp_path, data, subdir):
    return tmp_path / ".dagi" / "hash_cache" / subdir / f"{hashlib.sha256(data).hexdigest()}.md"


class TestOffice:
    def test_converted_by_markitdown_not_the_service(self, tmp_path):
        f = _doc(tmp_path, "notes.docx")
        with patch("tools.read._convert._markitdown", return_value="# Notes") as md, \
             patch("tools.read._convert.post_for_conversion") as post:
            conv = convert_document(f, service_url=URL, project_path=tmp_path)
        assert conv.markdown == "# Notes"
        md.assert_called_once()
        post.assert_not_called()

    def test_result_cached_under_doc_convert(self, tmp_path):
        f = _doc(tmp_path, "sheet.xlsx")
        with patch("tools.read._convert._markitdown", return_value="| a |") as md:
            convert_document(f, service_url=None, project_path=tmp_path)
            conv = convert_document(f, service_url=None, project_path=tmp_path)
        assert md.call_count == 1
        assert conv.cache_file == _cache_file(tmp_path, b"fake bytes", "doc_convert")
        assert conv.cache_file.read_text(encoding="utf-8") == "| a |"

    def test_no_project_path_converts_uncached(self, tmp_path):
        f = _doc(tmp_path, "deck.pptx")
        with patch("tools.read._convert._markitdown", return_value="slide"):
            conv = convert_document(f, service_url=None, project_path=None)
        assert conv.markdown == "slide"
        assert conv.cache_file is None
        assert not (tmp_path / ".dagi").exists()


class TestPdfChain:
    def test_service_first_and_cached(self, tmp_path):
        f = _doc(tmp_path, "report.pdf")
        with patch("tools.read._convert.post_for_conversion", return_value="<!-- Page 1 -->\nx") as post, \
             patch("tools.read._convert._markitdown") as md:
            convert_document(f, service_url=URL, project_path=tmp_path)
            conv = convert_document(f, service_url=URL, project_path=tmp_path)
        assert post.call_count == 1
        md.assert_not_called()
        assert conv.fallback_reason is None
        assert conv.cache_file == _cache_file(tmp_path, b"fake bytes", "doc_convert")

    def test_service_failure_falls_back_to_markitdown(self, tmp_path):
        f = _doc(tmp_path, "report.pdf")
        with patch("tools.read._convert.post_for_conversion",
                   side_effect=DocServiceError("CONNECTION_FAILED", "down")), \
             patch("tools.read._convert._markitdown", return_value="text"):
            conv = convert_document(f, service_url=URL, project_path=tmp_path)
        assert conv.markdown == "text"
        assert "CONNECTION_FAILED" in conv.fallback_reason
        # Fallback output must not occupy the service's cache slot.
        assert conv.cache_file == _cache_file(tmp_path, b"fake bytes", "doc_convert_markitdown")
        assert not _cache_file(tmp_path, b"fake bytes", "doc_convert").exists()

    def test_no_service_configured_uses_markitdown(self, tmp_path):
        f = _doc(tmp_path, "report.pdf")
        with patch("tools.read._convert.post_for_conversion") as post, \
             patch("tools.read._convert._markitdown", return_value="text"):
            conv = convert_document(f, service_url=None, project_path=tmp_path)
        post.assert_not_called()
        assert conv.fallback_reason is None

    def test_both_fail_raises_cannot_process_with_both_reasons(self, tmp_path):
        f = _doc(tmp_path, "report.pdf")
        with patch("tools.read._convert.post_for_conversion",
                   side_effect=DocServiceError("TIMEOUT", "slow")), \
             patch("tools.read._convert._markitdown",
                   side_effect=ConversionError(CANNOT_PROCESS, "markitdown broke")):
            with pytest.raises(ConversionError) as exc_info:
                convert_document(f, service_url=URL, project_path=tmp_path)
        assert exc_info.value.code == CANNOT_PROCESS
        assert "markitdown broke" in exc_info.value.message
        assert "TIMEOUT" in exc_info.value.message


class TestMarkitdown:
    def test_missing_markitdown_is_cannot_process(self, tmp_path):
        f = _doc(tmp_path, "notes.docx")
        with patch.dict("sys.modules", {"markitdown": None}):
            with pytest.raises(ConversionError) as exc_info:
                convert_document(f, service_url=None, project_path=tmp_path)
        assert exc_info.value.code == CANNOT_PROCESS
        assert "not installed" in exc_info.value.message

    def test_markitdown_exception_is_cannot_process(self, tmp_path):
        pytest.importorskip("markitdown")
        f = _doc(tmp_path, "broken.docx")
        with patch("markitdown.MarkItDown.convert", side_effect=RuntimeError("bad zip")):
            with pytest.raises(ConversionError) as exc_info:
                convert_document(f, service_url=None, project_path=tmp_path)
        assert exc_info.value.code == CANNOT_PROCESS
        assert "bad zip" in exc_info.value.message

    def test_real_docx(self, tmp_path):
        pytest.importorskip("markitdown")
        docx = pytest.importorskip("docx")
        d = docx.Document()
        d.add_heading("Quarterly Report", level=1)
        d.add_paragraph("Revenue grew.")
        f = tmp_path / "r.docx"
        d.save(f)
        conv = convert_document(f, service_url=None, project_path=tmp_path)
        assert "Quarterly Report" in conv.markdown
        assert "Revenue grew." in conv.markdown

    def test_real_pdf_gets_page_markers(self, tmp_path):
        pytest.importorskip("markitdown")
        fitz = pytest.importorskip("fitz")
        pdf = fitz.open()
        for i in range(3):
            pdf.new_page().insert_text((72, 72), f"Hello page {i + 1}")
        f = tmp_path / "t.pdf"
        pdf.save(f)
        try:
            conv = convert_document(f, service_url=None, project_path=tmp_path)
        except ConversionError as exc:
            pytest.skip(f"markitdown pdf extra unavailable: {exc}")
        assert conv.markdown.count("<!-- Page ") == 3
        assert "<!-- Page 2 -->\nHello page 2" in conv.markdown


class TestPageMarkers:
    def test_form_feeds_become_markers(self):
        assert _mark_pdf_pages("a\n\fb\n\f") == "<!-- Page 1 -->\na\n\n<!-- Page 2 -->\nb\n\n"

    def test_no_form_feeds_left_unmarked(self):
        assert _mark_pdf_pages("one blob") == "one blob"
