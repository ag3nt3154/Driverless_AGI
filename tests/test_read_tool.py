import pytest
from unittest.mock import MagicMock, patch

from tools.read import ReadTool
from tools.read._doc_service import DocServiceError


def _numbered(all_lines, start=1, end=None):
    """Render the expected cat -n style output for lines start..end."""
    end = len(all_lines) if end is None else end
    selected = all_lines[start - 1 : end]
    return "\n".join(
        f"{i:6d}\t{line}" for i, line in enumerate(selected, start)
    )


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

        assert result == _numbered(["hello", "world"])

    def test_offset_and_limit(self, tmp_path):
        all_lines = [f"line{i}" for i in range(1, 11)]
        text = "\n".join(all_lines)
        f = tmp_path / "notes.txt"
        f.write_text(text, encoding="utf-8")
        tool = _make_tool(tmp_path)

        result = tool.run(path="notes.txt", offset=3, limit=2)

        assert result == _numbered(all_lines, start=3, end=4)

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

    @patch("tools.read._source.convert_document")
    def test_docx_routed_to_service(self, mock_convert, tmp_path):
        mock_convert.return_value = "# Heading\n\nParagraph."
        f = tmp_path / "doc.docx"
        f.write_bytes(b"fake docx")
        tool = _make_tool(tmp_path)

        result = tool.run(path="doc.docx")

        mock_convert.assert_called_once()
        assert "# Heading" in result

    @patch("tools.read._source.convert_document")
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

    @patch("tools.read._source.convert_document")
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

    @patch("tools.read._source.convert_document")
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


class TestDocumentCacheDisclosure:
    def test_pdf_header_discloses_editable_cache_path(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        tool = _make_tool(tmp_path)

        with patch(
            "tools.read._source.convert_document",
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

        with patch("tools.read._source.convert_document", return_value="hello"):
            result = tool.run(path="notes.docx")

        assert result.startswith("[notes.docx | editable: ")


def _make_large_file(tmp_path, num_lines=2500):
    all_lines = [f"line{i}" for i in range(1, num_lines + 1)]
    f = tmp_path / "big.txt"
    f.write_text("\n".join(all_lines), encoding="utf-8")
    return f, all_lines


def _truncating_tool(tmp_path, reserve_tokens=1000, edge_chars=4000):
    return ReadTool(
        cwd=tmp_path, allowed_roots=[tmp_path], project_path=tmp_path,
        service_url="http://localhost:8100",
        reserve_tokens=reserve_tokens, edge_chars=edge_chars,
    )


class TestLargeResultTruncation:
    """Oversized results come back as head + marker + tail; never delegated."""

    def test_no_default_line_limit(self, tmp_path):
        _, all_lines = _make_large_file(tmp_path, num_lines=2500)
        tool = _truncating_tool(tmp_path, reserve_tokens=0)  # truncation off
        result = tool.run(path="big.txt")
        assert result == _numbered(all_lines)

    def test_small_result_inline(self, tmp_path):
        _, all_lines = _make_large_file(tmp_path, num_lines=50)
        result = _truncating_tool(tmp_path).run(path="big.txt")
        assert result == _numbered(all_lines)

    def test_large_result_truncated_with_line_numbers(self, tmp_path):
        f, _ = _make_large_file(tmp_path, num_lines=2500)
        result = _truncating_tool(tmp_path, reserve_tokens=1000, edge_chars=4000).run(
            path="big.txt"
        )
        # edge clamped to reserve (1000 chars per end)
        assert len(result) < 3000
        assert result.startswith("     1\tline1\n")
        assert result.endswith("  2500\tline2500")
        assert "of 2,500 omitted" in result
        assert f"Full text: {f}" in result
        assert "read_large_file" in result

    def test_marker_offset_points_at_first_omitted_line(self, tmp_path):
        _make_large_file(tmp_path, num_lines=2500)
        result = _truncating_tool(tmp_path).run(path="big.txt")
        head = result.split("\n[", 1)[0].split("\n")
        last_shown = int(head[-1].split("\t")[0])
        assert f"offset={last_shown + 1}" in result
        assert f"lines {last_shown + 1:,}–" in result

    def test_offset_limit_also_truncated(self, tmp_path):
        _make_large_file(tmp_path, num_lines=2500)
        result = _truncating_tool(tmp_path).run(path="big.txt", offset=1001, limit=1000)
        assert result.startswith("  1001\tline1001")
        assert result.endswith("  2000\tline2000")
        assert "of 2,500 omitted" in result

    def test_exact_threshold_boundary(self, tmp_path):
        # Below reserve_tokens → inline; at/above → truncated.
        f = tmp_path / "edge.txt"
        f.write_text("x" * 3990, encoding="utf-8")  # rendered ~3997 chars → 999 tokens
        assert "omitted" not in _truncating_tool(tmp_path).run(path="edge.txt")
        f.write_text("x" * 4100, encoding="utf-8")
        assert "omitted" in _truncating_tool(tmp_path).run(path="edge.txt")

    def test_large_pdf_keeps_header_and_hint(self, tmp_path):
        f = tmp_path / "report.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        md = "\n".join(f"<!-- Page {i} -->\n" + "text " * 40 for i in range(1, 200))
        with patch("tools.read._source.convert_document", return_value=md):
            result = _truncating_tool(tmp_path).run(path="report.pdf")
        assert result.startswith("[PDF: report.pdf | 199 pages")
        assert "omitted" in result
        assert "`pages`" in result
