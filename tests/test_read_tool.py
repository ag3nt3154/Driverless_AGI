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


def _make_config(project_path):
    config = MagicMock()
    config.project_path = project_path
    return config


def _make_large_file(tmp_path, num_lines=2500):
    all_lines = [f"line{i}" for i in range(1, num_lines + 1)]
    f = tmp_path / "big.txt"
    f.write_text("\n".join(all_lines), encoding="utf-8")
    return f, all_lines


def _make_ok_result(handoff_path):
    result = MagicMock()
    result.is_ok = True
    result.status = "ok"
    result.handoff_path = handoff_path
    return result


class TestLargeFileDelegation:
    """ReadTool delegates files over 2000 lines to read_large_text."""

    def test_large_file_delegates_to_read_large_text(self, tmp_path):
        _make_large_file(tmp_path)
        handoff = tmp_path / "handoff.md"
        handoff.write_text("## Summary\nBig file summary.", encoding="utf-8")
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch(
            "tools.subagent_api.run_subagent",
            return_value=_make_ok_result(handoff),
        ) as mock_run:
            result = tool.run(path="big.txt")

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["preset"] == "read-large-text"
        assert "Delegated to read_large_text" in result
        assert "Big file summary." in result

    def test_large_file_delegation_forwards_the_exact_parent_context(self, tmp_path):
        """Large-file delegation must inherit the same parent request context."""
        _make_large_file(tmp_path)
        handoff = tmp_path / "handoff.md"
        handoff.write_text("summary", encoding="utf-8")
        provider = object()
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=_make_config(tmp_path),
            parent_context=provider,
        )

        with patch(
            "tools.subagent_api.run_subagent",
            return_value=_make_ok_result(handoff),
        ) as mock_run:
            tool.run(path="big.txt")

        assert mock_run.call_args.kwargs["parent_context"] is provider

    def test_explicit_offset_skips_delegation(self, tmp_path):
        f, _ = _make_large_file(tmp_path)
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(path="big.txt", offset=5)

        mock_run.assert_not_called()
        assert "Delegated to read_large_text" not in result
        assert "line5" in result

    def test_explicit_limit_skips_delegation(self, tmp_path):
        f, _ = _make_large_file(tmp_path)
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(path="big.txt", limit=10)

        mock_run.assert_not_called()
        assert "Delegated to read_large_text" not in result
        assert f"{1:6d}\tline1" in result
        assert "line11" not in result

    def test_small_file_no_delegation(self, tmp_path):
        f = tmp_path / "small.txt"
        f.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(path="small.txt")

        mock_run.assert_not_called()
        assert "Delegated to read_large_text" not in result

    def test_no_config_no_delegation(self, tmp_path):
        _make_large_file(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=None,
        )

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(path="big.txt")

        mock_run.assert_not_called()
        assert "Delegated to read_large_text" not in result

    def test_doc_ext_over_default_limit_skips_delegation(self, tmp_path):
        """Converted doc files must not be delegated even if over the line limit —
        delegation would drop the header/pages info and hand off the raw path."""
        md_text = "\n".join(f"line{i}" for i in range(1, 2501))
        f = tmp_path / "big.docx"
        f.write_bytes(b"fake docx")
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch("tools.read._read.convert_document", return_value=md_text):
            with patch("tools.subagent_api.run_subagent") as mock_run:
                result = tool.run(path="big.docx")

        mock_run.assert_not_called()
        assert "Delegated to read_large_text" not in result
        assert result.startswith("[big.docx | editable: ")

    def test_on_event_factory_called_with_preset_name(self, tmp_path):
        _make_large_file(tmp_path)
        handoff = tmp_path / "handoff.md"
        handoff.write_text("summary", encoding="utf-8")
        config = _make_config(tmp_path)
        callbacks = MagicMock()
        factory = MagicMock(return_value="on_event_sentinel")
        callbacks.on_subagent_event_factory = factory
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=callbacks,
            config=config,
        )

        with patch(
            "tools.subagent_api.run_subagent",
            return_value=_make_ok_result(handoff),
        ) as mock_run:
            tool.run(path="big.txt")

        factory.assert_called_once_with("read-large-text")
        assert mock_run.call_args.kwargs["on_event"] == "on_event_sentinel"

    def test_ok_unverified_banner_via_delegation(self, tmp_path):
        _make_large_file(tmp_path)
        handoff = tmp_path / "handoff.md"
        handoff.write_text("## Summary\nUnverified summary.", encoding="utf-8")
        config = _make_config(tmp_path)
        result_mock = MagicMock()
        result_mock.is_ok = True
        result_mock.status = "ok_unverified"
        result_mock.handoff_path = handoff
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch(
            "tools.subagent_api.run_subagent", return_value=result_mock
        ):
            result = tool.run(path="big.txt")

        assert "UNVERIFIED" in result
        assert "Summary below." in result

    def test_failure_dispatch_via_delegation(self, tmp_path):
        _make_large_file(tmp_path)
        config = _make_config(tmp_path)
        result_mock = MagicMock()
        result_mock.is_ok = False
        result_mock.status = "timeout"
        result_mock.pid = 4321
        result_mock.escalation = None
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch(
            "tools.subagent_api.run_subagent", return_value=result_mock
        ):
            result = tool.run(path="big.txt")

        assert "timeout" in result
        assert "4321" in result
        assert "Delegation result below." in result
        assert "Summary below." not in result

    def test_query_passed_as_custom_instructions(self, tmp_path):
        _make_large_file(tmp_path)
        handoff = tmp_path / "handoff.md"
        handoff.write_text("summary", encoding="utf-8")
        config = _make_config(tmp_path)
        tool = ReadTool(
            cwd=tmp_path,
            allowed_roots=[tmp_path],
            service_url="http://localhost:8100",
            project_path=tmp_path,
            callbacks=None,
            config=config,
        )

        with patch(
            "tools.subagent_api.run_subagent",
            return_value=_make_ok_result(handoff),
        ) as mock_run:
            tool.run(path="big.txt", query="find X")

        assert mock_run.call_args.kwargs["custom_instructions"] == "find X"
