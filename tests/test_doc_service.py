"""Tests for the document service HTTP client (tools/read/_doc_service.py)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tools.read._doc_service import convert_document, DocServiceError


class TestLocalCacheHit:
    def test_returns_cached_markdown_without_http(self, tmp_path):
        import hashlib
        content = b"fake pdf bytes"
        content_hash = hashlib.sha256(content).hexdigest()
        cache_dir = tmp_path / ".dagi" / "hash_cache" / "doc_convert"
        cache_dir.mkdir(parents=True)
        cache_file = cache_dir / f"{content_hash}.md"
        cache_file.write_text("# Cached Result", encoding="utf-8")

        doc = tmp_path / "report.pdf"
        doc.write_bytes(content)

        result = convert_document(doc, "http://localhost:8100", tmp_path)

        assert result == "# Cached Result"


class TestCacheMiss:
    @patch("tools.read._doc_service.httpx.Client")
    def test_uploads_file_and_caches_response(self, MockClient, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "# Converted\n\nContent."
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.docx"
        doc.write_bytes(b"fake docx bytes")

        result = convert_document(doc, "http://localhost:8100", tmp_path)

        assert result == "# Converted\n\nContent."
        mock_client_instance.post.assert_called_once()

        import hashlib
        h = hashlib.sha256(b"fake docx bytes").hexdigest()
        cache_file = tmp_path / ".dagi" / "hash_cache" / "doc_convert" / f"{h}.md"
        assert cache_file.exists()
        assert cache_file.read_text(encoding="utf-8") == "# Converted\n\nContent."


class TestServiceErrors:
    @patch("tools.read._doc_service.httpx.Client")
    def test_connection_refused_raises_doc_service_error(self, MockClient, tmp_path):
        import httpx
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.side_effect = httpx.ConnectError("refused")
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"fake pdf")

        with pytest.raises(DocServiceError, match="CONNECTION_FAILED"):
            convert_document(doc, "http://localhost:8100", tmp_path)

    @patch("tools.read._doc_service.httpx.Client")
    def test_server_error_passes_through_code_and_message(self, MockClient, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {
            "error": "docling crashed", "code": "CONVERSION_FAILED"
        }
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        MockClient.return_value = mock_client_instance

        doc = tmp_path / "doc.pdf"
        doc.write_bytes(b"fake pdf")

        with pytest.raises(DocServiceError) as exc_info:
            convert_document(doc, "http://localhost:8100", tmp_path)

        assert exc_info.value.code == "CONVERSION_FAILED"
        assert "docling crashed" in exc_info.value.message
