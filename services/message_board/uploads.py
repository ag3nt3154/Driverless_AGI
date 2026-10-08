"""Bounded multipart receipt without Starlette's eager form buffering."""
from __future__ import annotations

from io import BytesIO

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.requests import Request

from .store import MAX_ATTACHMENT, StoreError

MAX_BODY = MAX_ATTACHMENT + 64 * 1024
MAX_HEADERS = 8 * 1024
MAX_UPLOADER = 128


def invalid(message: str) -> None:
    raise StoreError("INVALID", message, 422)


def too_large(message: str) -> None:
    raise StoreError("TOO_LARGE", message, 413)


class UploadParser:
    """Callbacks retain only one bounded file and one bounded uploader field."""

    def __init__(self) -> None:
        self.data = BytesIO()
        self.file_size = 0
        self.uploader = bytearray()
        self.filename = ""
        self.seen = set()
        self.finished = False
        self.part = None
        self.headers = {}
        self.header_bytes = 0
        self.field = bytearray()
        self.value = bytearray()
        self.in_headers = False
        self.raw_offset = None
        self.raw_chunk = b""
        self.raw_prefix = b""

    def on_part_begin(self) -> None:
        self.part = None
        self.headers = {}
        self.header_bytes = 0
        self.in_headers = True
        self.raw_offset = None
        self.raw_prefix = b""

    def begin_chunk(self, chunk: bytes) -> None:
        self.raw_prefix = self.raw_chunk[-3:] if self.in_headers else b""
        self.raw_chunk = chunk
        self.raw_offset = 0 if self.in_headers else None

    def _account_headers(self, end: int, start: int = 0) -> None:
        offset = start if self.raw_offset is None else self.raw_offset
        self.header_bytes += end - offset
        self.raw_offset = end
        if self.header_bytes > MAX_HEADERS:
            too_large("multipart part headers exceed 8 KB")

    def finish_chunk(self) -> None:
        if self.in_headers and self.raw_offset is not None:
            self._account_headers(len(self.raw_chunk))
        self.raw_chunk = self.raw_chunk[-3:]

    def _header_piece(self, buffer: bytearray, data: bytes, start: int, end: int) -> None:
        self._account_headers(end, start)
        buffer.extend(data[start:end])

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_piece(self.field, data, start, end)

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_piece(self.value, data, start, end)

    def on_header_end(self) -> None:
        name = bytes(self.field).lower()
        if name in self.headers:
            invalid("duplicate multipart header")
        self.headers[name] = bytes(self.value)
        self.field.clear()
        self.value.clear()

    def on_headers_finished(self) -> None:
        prefix_size = len(self.raw_prefix)
        raw = self.raw_prefix + self.raw_chunk
        start = max(0, prefix_size + (self.raw_offset or 0) - 3)
        end = raw.find(b"\r\n\r\n", start) + 4 - prefix_size
        self._account_headers(end)
        self.in_headers = False
        disposition, options = parse_options_header(self.headers.get(b"content-disposition", b""))
        if disposition != b"form-data":
            invalid("multipart part requires form-data disposition")
        name = options.get(b"name")
        if name not in (b"file", b"uploader") or name in self.seen:
            invalid("upload requires exactly one file and one uploader")
        self.seen.add(name)
        self.part = name
        self._check_filename(options)

    def _check_filename(self, options: dict) -> None:
        filename = options.get(b"filename")
        if self.part == b"file":
            if filename is None:
                invalid("file part requires a filename")
            self.filename = filename.decode("utf-8", errors="replace")
        elif filename is not None:
            invalid("uploader must be a text field")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        piece = memoryview(data)[start:end]
        if self.part == b"file":
            if self.file_size + len(piece) > MAX_ATTACHMENT:
                too_large("multipart file exceeds 10 MB")
            self.data.write(piece)
            self.file_size += len(piece)
        else:
            if len(self.uploader) + len(piece) > MAX_UPLOADER:
                too_large("multipart uploader exceeds 128 bytes")
            self.uploader.extend(piece)

    def on_end(self) -> None:
        self.finished = True

    def result(self) -> tuple[str, str, bytes]:
        if not self.finished or self.seen != {b"file", b"uploader"}:
            invalid("incomplete upload: exactly one file and uploader required")
        try:
            uploader = self.uploader.decode("utf-8")
        except UnicodeDecodeError:
            invalid("uploader must be UTF-8")
        if not uploader:
            invalid("uploader must not be empty")
        return uploader, self.filename, self.data.getvalue()


def _boundary(request: Request) -> bytes:
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary", b"")
    if content_type != b"multipart/form-data" or not 1 <= len(boundary) <= 200:
        invalid("expected multipart/form-data with a boundary of at most 200 bytes")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            invalid("invalid Content-Length")
        if length < 0:
            invalid("invalid Content-Length")
        if length > MAX_BODY:
            too_large("upload body exceeds 10 MB plus 64 KB overhead")
    return boundary


async def receive_upload(request: Request) -> tuple[str, str, bytes]:
    """Stop receive immediately on a size violation; never persist incomplete input."""
    boundary = _boundary(request)
    state = UploadParser()
    callbacks = {name: getattr(state, name) for name in (
        "on_part_begin", "on_header_field", "on_header_value", "on_header_end",
        "on_headers_finished", "on_part_data", "on_end",
    )}
    parser = MultipartParser(boundary, callbacks, max_header_size=MAX_HEADERS,
                             max_header_count=MAX_HEADERS)
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_BODY:
                too_large("upload body exceeds 10 MB plus 64 KB overhead")
            state.begin_chunk(chunk)
            parser.write(chunk)
            state.finish_chunk()
        parser.finalize()
        return state.result()
    except MultipartParseError as error:
        if "Maximum header" in str(error):
            too_large("multipart part headers exceed their bounded limit")
        raise StoreError("INVALID", "malformed multipart upload", 422) from error
    finally:
        state.data.close()
        state.uploader.clear()

