import pytest
from unittest.mock import patch

from tools.read import ReadTool
from tools.read._doc_service import DocServiceError
from tools import _hashline as H


def _anchored(all_lines, start=1, end=None):
    """Render the expected read output for lines start..end of all_lines."""
    end = len(all_lines) if end is None else end
    anchors = H.build_anchors(all_lines)
    return H.format_region(all_lines, anchors, start, end)


def _make_tool(tmp_path, service_url="http://localhost:8100"):
    return ReadTool(
        cwd=tmp_path,
        allowed_roots=[tmp_path],
        service_url=service_url,
        project_path=tmp_path,
    )


class TestTextFileReading:
    """Text file reading — unchanged behavior."""

    def test_reads_text_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\nworld", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt")

        assert result == _anchored(["hello", "world"])

    def test_offset_and_limit(self, tmp_path):
        all_lines = [f"line{i}" for i in range(1, 11)]
        text = "\n".join(all_lines)
        f = tmp_path / "notes.txt"
        f.write_text(text, encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", offset=3, limit=2)

        assert result == _anchored(all_lines, start=3, end=4)

    def test_windowed_read_anchors_match_whole_file_anchors(self, tmp_path):
        all_lines = [f"line{i}" for i in range(1, 21)]
        f = tmp_path / "notes.txt"
        f.write_text("\n".join(all_lines), encoding="utf-8")
        tool = _make_tool(tmp_path)

        windowed = tool.run(path="notes.txt", offset=15, limit=3)
        anchors = H.build_anchors(all_lines)

        assert f"#{anchors[14]}:line15" in windowed

    def test_binary_file_returns_error(self, tmp_path):
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01\x02\xff\xfe")
        tool = _make_tool(tmp_path)

        result = tool.run(path="data.bin")

        assert "binary" in result.lower() or "UTF-8" in result

    def test_blocked_extension_returns_error(self, tmp_path):
        f = tmp_path / "photo.jpg"
        f.write_bytes(b"fake jpg")
        tool = _make_tool(tmp_path)

        result = tool.run(path="photo.jpg")

        assert result.startswith("Error:")

    def test_pages_on_non_pdf_returns_error(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello", encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", pages="1-3")

        assert "only supported for PDF" in result


class TestDocumentRouting:
    """Document files are routed through the service client."""

    @patch("tools.read._read.convert_document")
    def test_docx_routed_to_service(self, mock_convert, tmp_path):
        mock_convert.return_value = "# Heading\n\nParagraph."
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        mock_convert.assert_called_once()
        assert "# Heading" in result

    @patch("tools.read._read.convert_document")
    def test_pdf_routed_to_service_with_page_header(self, mock_convert, tmp_path):
        mock_convert.return_value = (
            "<!-- Page 1 -->\n# Title\n\n"
            "<!-- Page 2 -->\n## Chapter 1\n"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert result.startswith("[PDF: report.pdf |")
        assert "# Title" in result

    @patch("tools.read._read.convert_document")
    def test_pdf_pages_parameter_filters(self, mock_convert, tmp_path):
        mock_convert.return_value = (
            "<!-- Page 1 -->\n# Title\n\n"
            "<!-- Page 2 -->\n## Chapter 1\n"
            "<!-- Page 3 -->\n## Chapter 2\n"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf", pages="2")

        assert "## Chapter 1" in result
        assert "# Title" not in result

    @patch("tools.read._read.convert_document")
    def test_service_error_returned_to_llm(self, mock_convert, tmp_path):
        mock_convert.side_effect = DocServiceError(
            "CONVERSION_FAILED", "docling crashed on page 3"
        )
        f = tmp_path / "report.pdf"
        f.write_bytes(b"fake pdf")
        tool = _make_tool(tmp_path)

        result = tool.run(path="report.pdf")

        assert "CONVERSION_FAILED" in result
        assert "docling crashed on page 3" in result

    def test_no_service_url_returns_config_error(self, tmp_path):
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx")
        tool = ReadTool(
            cwd=tmp_path, allowed_roots=[tmp_path],
            service_url=None, project_path=tmp_path,
        )

        result = tool.run(path="doc.docx")

        assert "converter service" in result.lower()


class TestAutoSummarization:
    def test_large_file_triggers_summarization(self, tmp_path):
        content = "line\n" * 100_000  # ~500k chars → ~125k tokens
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        fake_summary = "## Section 1 (lines 1-2000, ~2500 tokens)\n**Summary:** lots of lines"

        with patch(
            "tools.read._read.summarize_document", return_value=fake_summary
        ) as mock_summarize:
            result = tool.run(path="huge.txt")

        assert result == fake_summary
        mock_summarize.assert_called_once()

    def test_small_file_does_not_trigger_summarization(self, tmp_path):
        content = "short file\nonly two lines\n"
        f = tmp_path / "small.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read._read.summarize_document"
        ) as mock_summarize:
            result = tool.run(path="small.txt")

        mock_summarize.assert_not_called()
        assert "short file" in result

    def test_summarization_failure_falls_back_to_raw_text(self, tmp_path):
        content = "line\n" * 100_000
        f = tmp_path / "huge.txt"
        f.write_text(content, encoding="utf-8")
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            reserve_tokens=16_384,
            project_path=tmp_path,
        )

        with patch(
            "tools.read._read.summarize_document", return_value=None
        ):
            result = tool.run(path="huge.txt")

        # Falls back to raw text (which output_filter will later truncate)
        assert "line" in result


class TestDocumentCacheDisclosure:
    def test_pdf_header_discloses_editable_cache_path(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        tool = _make_tool(tmp_path)

        with patch(
            "tools.read._read.convert_document",
            return_value="<!-- Page 1 -->\nhello",
        ):
            result = tool.run(path="report.pdf")

        assert "editable:" in result
        assert ".dagi" in result
        assert result.splitlines()[0].endswith("]")

    def test_docx_header_discloses_editable_cache_path(self, tmp_path):
        f = tmp_path / "notes.docx"
        f.write_bytes(b"PK fake docx")
        tool = _make_tool(tmp_path)

        with patch("tools.read._read.convert_document", return_value="hello"):
            result = tool.run(path="notes.docx")

        assert result.startswith("[notes.docx | editable: ")

