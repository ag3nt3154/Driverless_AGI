"""HTTP client for the custom PDF conversion API.

Anti-corruption layer: all HTTP details (endpoint, error mapping) live here.
The contract is a single ``POST {service_url}/convert`` with the file as a
multipart upload; a 200 response body is the converted markdown, anything
else is a JSON ``{"error", "code"}`` body. ``services.doc_converter`` is the
reference implementation, but any server honouring that contract works.

Caching is the caller's job (tools/read/_convert.py) — this module always
performs the request.
"""
from __future__ import annotations

import httpx

_TIMEOUT = 300.0  # 5 minutes — large PDFs with OCR can be slow


class DocServiceError(Exception):
    """Raised when the conversion API is unreachable or returns an error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def post_for_conversion(file_bytes: bytes, filename: str, service_url: str) -> str:
    """POST ``file_bytes`` to the conversion API and return its markdown.

    Raises:
        DocServiceError: connection failure, timeout, or a non-200 response.
    """
    url = f"{service_url.rstrip('/')}/convert"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.post(url, files={"file": (filename, file_bytes)})
    except httpx.ConnectError:
        raise DocServiceError(
            "CONNECTION_FAILED",
            f"PDF conversion service is not running at {service_url}.",
        )
    except httpx.TimeoutException:
        raise DocServiceError(
            "TIMEOUT",
            f"PDF conversion service timed out after {_TIMEOUT}s.",
        )
    except httpx.HTTPError as exc:
        raise DocServiceError("HTTP_ERROR", str(exc))

    if response.status_code == 200:
        return response.text

    try:
        error_body = response.json()
        code = error_body.get("code", "UNKNOWN")
        message = error_body.get("error", response.text)
    except Exception:
        code = f"HTTP_{response.status_code}"
        message = response.text

    raise DocServiceError(code, message)
