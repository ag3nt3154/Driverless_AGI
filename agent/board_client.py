"""The dagi-side HTTP boundary for board posts, attachments and agent cursors."""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import socket
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx

from ._board_files import (
    attachment_cache_path, cached_file_matches, validate_attachment, validate_attachment_id,
)


_CACHE_LOCK = threading.Lock()


class BoardError(Exception):
    """Actionable board failure, retaining the original exception as its cause."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def new_handle(slug: str) -> str:
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", slug):
        raise ValueError("handle slug must be 1 through 32 lowercase letters, digits or hyphens")
    return f"{slug}_{uuid.uuid4().hex[:8]}"


class _StreamLines:
    """Closable iterator lets a listener interrupt an active network response."""

    def __init__(self, response, client) -> None:
        self._response = response
        self._client = client
        self._lines = iter(response.iter_lines())
        self._closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self._closed.is_set():
            raise StopIteration
        try:
            return next(self._lines)
        except (httpx.HTTPError, httpx.StreamError) as error:
            if self._closed.is_set():
                raise StopIteration from error
            raise self._client._network_error(error) from error

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._response.is_closed:
            return
        network = self._response.extensions.get("network_stream")
        if network is not None:
            stream_socket = network.get_extra_info("socket")
            if stream_socket is not None:
                try:
                    stream_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # already-closed sockets require no further interruption
        self._response.close()


class BoardClient:
    """Synchronous HTTP client; injected TestClient/httpx clients use the same contract."""

    def __init__(self, base_url: str, token: str | None = None, http=None,
                 timeout: float = 10.0, *, download_http=None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token, self.timeout = token, timeout
        self._download_http = download_http
        self._owned = http is None
        self.http = http or httpx.Client(base_url=self.base_url, timeout=timeout, trust_env=False)

    def close(self) -> None:
        if self._owned:
            self.http.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _network_error(self, error: httpx.HTTPError) -> BoardError:
        if isinstance(error, httpx.TimeoutException):
            return BoardError("TIMEOUT", f"message board request timed out at {self.base_url}")
        return BoardError("UNREACHABLE", f"message board unreachable at {self.base_url}")

    def _check_response(self, response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            response.read()
            code, message = f"HTTP_{response.status_code}", "message board request failed"
            try:
                body = response.json()
                if isinstance(body, dict):
                    code = body.get("code") or code
                    message = body.get("error") or message
            except ValueError:
                pass  # non-JSON HTTP errors retain their status code
            raise BoardError(str(code), str(message)) from error

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self.http.request(method, path, headers=self._headers(),
                                         timeout=kwargs.pop("timeout", self.timeout),
                                         follow_redirects=False, **kwargs)
            self._check_response(response)
            return response.json()
        except httpx.HTTPError as error:
            raise self._network_error(error) from error
        except ValueError as error:
            raise BoardError("INVALID_RESPONSE", "message board returned invalid JSON") from error

    def health(self) -> dict:
        return self._request("GET", "health")

    def register(self, handle: str, kind: str, display_name: str | None = None,
                 host: str | None = None) -> dict:
        body = {"handle": handle, "kind": kind}
        if display_name is not None:
            body["display_name"] = display_name
        if host is not None:
            body["host"] = host
        return self._request("POST", "members", json=body)

    def members(self) -> list[dict]:
        return self._request("GET", "members")

    def post(self, author: str, text: str, *, meme: str | None = None,
             reply_to: int | None = None, attachments=None) -> dict:
        return self._request("POST", "posts", json={"author": author, "text": text,
                             "meme": meme, "reply_to": reply_to, "attachments": attachments or []})

    def posts(self, after: int | None = None, limit: int = 50,
              mention: str | None = None) -> list[dict]:
        params = {"limit": limit}
        if after is not None:
            params["after"] = after
        if mention is not None:
            params["mention"] = mention
        return self._request("GET", "posts", params=params)

    def upload(self, uploader: str, path: Path) -> dict:
        try:
            with Path(path).open("rb") as stream:
                return self._request("POST", "attachments", data={"uploader": uploader},
                                     files={"file": (Path(path).name, stream)}, timeout=120.0)
        except OSError as error:
            raise BoardError("FILE_ERROR", f"cannot open attachment {Path(path).name}") from error

    def attachment_meta(self, att_id: str) -> dict:
        try:
            validate_attachment_id(att_id)
        except ValueError as error:
            raise BoardError("INVALID_ATTACHMENT", str(error)) from error
        return self._request("GET", f"attachments/{att_id}/meta")

    @contextmanager
    def stream(self, after: int | None = None):
        params = {} if after is None else {"after": after}
        try:
            headers = {**self._headers(), "Connection": "close"}
            with self.http.stream("GET", "stream", params=params, headers=headers,
                                  timeout=httpx.Timeout(10.0, read=45.0),
                                  follow_redirects=False) as response:
                self._check_response(response)
                lines = _StreamLines(response, self)
                try:
                    yield lines
                finally:
                    lines.close()
        except httpx.HTTPError as error:
            raise self._network_error(error) from error

    def fetch_attachment(self, att_id: str, *, project_root: Path, cancel=None,
                         deadline_s: float = 120.0) -> tuple[dict, Path]:
        """Each fetch owns an async client/loop, enforcing a true total network deadline."""
        try:
            validate_attachment_id(att_id)
            return asyncio.run(self._fetch_cancelable(att_id, project_root, cancel, deadline_s))
        except TimeoutError as error:
            raise BoardError(
                "TIMEOUT", "attachment download exceeded its total deadline",
            ) from error
        except httpx.HTTPError as error:
            raise self._network_error(error) from error
        except ValueError as error:
            raise BoardError("INVALID_ATTACHMENT", str(error)) from error
        except OSError as error:
            raise BoardError("FILE_ERROR", "cannot write the project attachment cache") from error

    def _download_client(self):
        if self._download_http is not None:
            return self._download_http()
        return httpx.AsyncClient(base_url=self.base_url, trust_env=False)

    async def _fetch_cancelable(self, att_id: str, root: Path, cancel, deadline_s: float):
        if cancel is None:
            return await self._fetch_attachment(att_id, root, cancel, deadline_s)
        worker = asyncio.create_task(self._fetch_attachment(att_id, root, cancel, deadline_s))
        watcher = asyncio.create_task(_wait_cancel(cancel))
        try:
            done, _ = await asyncio.wait((worker, watcher), return_when=asyncio.FIRST_COMPLETED)
            if watcher in done:
                raise BoardError("CANCELLED", "attachment download cancelled")
            return await worker
        finally:
            worker.cancel()
            watcher.cancel()
            await asyncio.gather(worker, watcher, return_exceptions=True)

    async def _fetch_attachment(self, att_id: str, root: Path, cancel, deadline_s: float):
        budget = _DownloadBudget(deadline_s, cancel)
        budget.check()
        async with asyncio.timeout(deadline_s), self._download_client() as http:
            response = await http.get(f"attachments/{att_id}/meta", headers=self._headers(),
                                      timeout=budget.timeout(), follow_redirects=False)
            self._check_response(response)
            budget.check()
            metadata = validate_attachment(att_id, response.json())
            async with _cache_guard(budget):
                path = attachment_cache_path(root, metadata)
                if cached_file_matches(path, metadata, budget.check):
                    budget.check()
                    return metadata, path
                path.parent.mkdir(parents=True, exist_ok=True)
                attachment_cache_path(root, metadata)
            await self._download(http, metadata, path, root, budget=budget)
            return metadata, path

    async def _download(self, http, metadata: dict, path: Path, root: Path, *, budget) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=path.parent, prefix=".download-", delete=False,
            ) as file:
                temporary = Path(file.name)
                await self._receive_file(http, metadata, file, budget)
            budget.check()
            async with _cache_guard(budget):
                attachment_cache_path(root, metadata)
                if not cached_file_matches(path, metadata, budget.check):
                    os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    async def _receive_file(self, http, metadata: dict, file, budget) -> None:
        digest, size = hashlib.sha256(), 0
        async with http.stream("GET", f"attachments/{metadata['id']}", headers=self._headers(),
                               timeout=budget.timeout(), follow_redirects=False) as response:
            if response.is_error or response.is_redirect:
                await response.aread()
            self._check_response(response)
            encoding = response.headers.get("content-encoding", "identity").strip().lower()
            if encoding != "identity":
                raise BoardError(
                    "INVALID_ATTACHMENT", "attachment response must use identity encoding",
                )
            async for chunk in response.aiter_bytes():
                budget.check()
                size += len(chunk)
                if size > metadata["size"]:
                    raise BoardError("INVALID_ATTACHMENT", "download exceeds declared size")
                self._write_chunk(file, digest, chunk, budget)
            budget.check()
        if size != metadata["size"] or digest.hexdigest() != metadata["sha256"]:
            raise BoardError(
                "INVALID_ATTACHMENT", "download size or sha256 does not match metadata",
            )


    def _write_chunk(self, file, digest, chunk: bytes, budget) -> None:
        view = memoryview(chunk)
        for start in range(0, len(view), 64 * 1024):
            budget.check()
            piece = view[start:start + 64 * 1024]
            file.write(piece)
            digest.update(piece)


async def _wait_cancel(cancel) -> None:
    while not cancel.is_set():
        await asyncio.sleep(0.02)


@asynccontextmanager
async def _cache_guard(budget):
    budget.check()
    while not _CACHE_LOCK.acquire(blocking=False):
        await asyncio.sleep(0.01)
        budget.check()
    try:
        budget.check()
        yield
    finally:
        _CACHE_LOCK.release()


class _DownloadBudget:
    def __init__(self, deadline_s: float, cancel) -> None:
        self.deadline = time.monotonic() + deadline_s
        self.cancel = cancel

    def check(self) -> None:
        cancelled = self.cancel is not None and self.cancel.is_set()
        if cancelled:
            raise BoardError("CANCELLED", "attachment download cancelled")
        if time.monotonic() >= self.deadline:
            raise BoardError("TIMEOUT", "attachment download exceeded its total deadline")

    def timeout(self) -> httpx.Timeout:
        self.check()
        remaining = max(0.001, self.deadline - time.monotonic())
        return httpx.Timeout(min(10.0, remaining), read=min(1.0, remaining))


class BoardSession:
    """One agent identity and independent serialized all-post/mention read cursors."""

    def __init__(self, client: BoardClient, handle: str) -> None:
        self.client, self.handle = client, handle
        self._lock = threading.Lock()
        self._cursors = {False: None, True: None}

    def read(self, limit: int = 20, mentions_only: bool = False) -> list[dict]:
        with self._lock:
            posts = self.client.posts(after=self._cursors[mentions_only], limit=limit,
                                      mention=self.handle if mentions_only else None)
            if posts:
                self._cursors[mentions_only] = max(post["id"] for post in posts)
            elif self._cursors[mentions_only] is None:
                self._cursors[mentions_only] = 0
            return posts

    def post(self, text: str, meme: str | None = None, reply_to: int | None = None,
             files=()) -> dict:
        attachments = [self.client.upload(self.handle, Path(path))["id"] for path in files]
        return self.client.post(self.handle, text, meme=meme, reply_to=reply_to,
                                attachments=attachments)

    def fetch(self, att_id: str, project_root: Path) -> tuple[dict, Path]:
        return self.client.fetch_attachment(att_id, project_root=project_root)
