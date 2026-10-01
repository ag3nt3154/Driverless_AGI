"""Tests for the PDF conversion API client (tools/read/_doc_service.py)."""
from unittest.mock import patch, MagicMock

import httpx
import pytest

from tools.read._doc_service import post_for_conversion, DocServiceError


def _client_returning(response=None, side_effect=None):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = response
    client.post.side_effect = side_effect
    return client


@patch("tools.read._doc_service.httpx.Client")
def test_posts_file_and_returns_body(MockClient):
    response = MagicMock(status_code=200, text="# Converted\n\nContent.")
    MockClient.return_value = _client_returning(response)

    result = post_for_conversion(b"fake pdf", "doc.pdf", "http://localhost:8100/")

    assert result == "# Converted\n\nContent."
    url = MockClient.return_value.post.call_args.args[0]
    files = MockClient.return_value.post.call_args.kwargs["files"]
    assert url == "http://localhost:8100/convert"
    assert files == {"file": ("doc.pdf", b"fake pdf")}


@patch("tools.read._doc_service.httpx.Client")
def test_connection_refused_raises_doc_service_error(MockClient):
    MockClient.return_value = _client_returning(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(DocServiceError, match="CONNECTION_FAILED"):
        post_for_conversion(b"fake pdf", "doc.pdf", "http://localhost:8100")


@patch("tools.read._doc_service.httpx.Client")
def test_timeout_raises_doc_service_error(MockClient):
    MockClient.return_value = _client_returning(side_effect=httpx.ReadTimeout("slow"))

    with pytest.raises(DocServiceError, match="TIMEOUT"):
        post_for_conversion(b"fake pdf", "doc.pdf", "http://localhost:8100")


@patch("tools.read._doc_service.httpx.Client")
def test_server_error_passes_through_code_and_message(MockClient):
    response = MagicMock(status_code=500)
    response.json.return_value = {"error": "docling crashed", "code": "CONVERSION_FAILED"}
    MockClient.return_value = _client_returning(response)

    with pytest.raises(DocServiceError) as exc_info:
        post_for_conversion(b"fake pdf", "doc.pdf", "http://localhost:8100")

    assert exc_info.value.code == "CONVERSION_FAILED"
    assert "docling crashed" in exc_info.value.message
