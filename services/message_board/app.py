"""HTTP endpoints, board notifications and resumable server-sent events."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from starlette.exceptions import HTTPException

from .lifecycle import is_loopback_host
from .store import MAX_ID, BoardStore, StoreError
from .uploads import receive_upload

PING_SECONDS = 15.0


class PostHub:
    """Loop-local condition with a version counter closing the list/wait race."""

    def __init__(self) -> None:
        self.version = 0
        self._cond = None

    def _condition(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    async def notify(self) -> None:
        async with self._condition():
            self.version += 1
            self._condition().notify_all()

    async def wait_past(self, version: int, timeout: float) -> bool:
        async with self._condition():
            try:
                await asyncio.wait_for(
                    self._condition().wait_for(lambda: self.version > version), timeout,
                )
            except TimeoutError:
                return False
            return True


async def post_events(store: BoardStore, hub: PostHub, after: int | None):
    cursor = await asyncio.to_thread(store.latest_id) if after is None else after
    while True:
        seen = hub.version
        posts = await asyncio.to_thread(store.list_posts, after=cursor, limit=200)
        for post in posts:
            cursor = post["id"]
            yield f"id: {cursor}\nevent: post\ndata: {json.dumps(post)}\n\n"
        if posts:
            continue
        if not await hub.wait_past(seen, PING_SECONDS):
            yield ": ping\n\n"


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str
    kind: str
    display_name: str | None = None
    host: str = ""


class PostInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    author: str
    text: str
    meme: str | None = None
    reply_to: StrictInt | None = Field(default=None, ge=1, le=MAX_ID)
    attachments: list[str] = Field(default_factory=list)


class ShutdownInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance_id: str


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message, "code": code}, status_code=status)


def _shutdown_check(request: Request, shutdown, instance_id: str) -> None:
    if shutdown is None:
        raise StoreError("STOP_UNAVAILABLE", "this board has no shutdown capability", 503)
    peer = request.client.host if request.client else ""
    if not is_loopback_host(peer, allow_localhost=False):
        raise StoreError("FORBIDDEN", "shutdown requires a direct loopback peer", 403)
    supplied = request.headers.get("x-dagi-stop-token", "")
    if not hmac.compare_digest(supplied.encode(), shutdown.capability.encode()):
        raise StoreError("FORBIDDEN", "invalid local shutdown capability", 403)
    if instance_id != shutdown.instance_id:
        raise StoreError("STALE_INSTANCE", "shutdown instance does not match", 409)


def create_app(store: BoardStore, token: str | None = None, *, shutdown=None) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hub = PostHub()
    app.state.hub = hub
    instance_id = shutdown.instance_id if shutdown else uuid.uuid4().hex

    @app.middleware("http")
    async def headers_and_auth(request: Request, call_next):
        public = request.method == "GET" and request.url.path in ("/", "/health")
        supplied = request.headers.get("authorization", "")
        if token and not public and not hmac.compare_digest(
            supplied.encode(), f"Bearer {token}".encode(),
        ):
            response = _error("UNAUTHORIZED", "a valid bearer token is required", 401)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, error):
        return _error(error.code, error.message, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return _error("INVALID", "invalid request fields or query parameters", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return _error("INVALID", str(error.detail), error.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logging.getLogger(__name__).error("message board request failed", exc_info=error)
        response = _error("INTERNAL_ERROR", "message board storage failed; check service logs", 500)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    _read_routes(app, store, hub, instance_id)
    _write_routes(app, store, hub, shutdown)
    return app


def _read_routes(app: FastAPI, store: BoardStore, hub: PostHub, instance_id: str) -> None:
    @app.get("/")
    def viewer():
        path = Path(__file__).parent / "static" / "index.html"
        if path.exists():
            return FileResponse(path, media_type="text/html")
        return HTMLResponse("<!doctype html><title>Message board</title><p>Message board</p>")

    @app.get("/health")
    def health():
        return dict(status="ok", version=1, pid=os.getpid(), instance_id=instance_id)

    @app.get("/members")
    def members():
        return store.list_members()

    @app.get("/posts")
    def posts(after: int | None = Query(default=None, ge=0, le=MAX_ID),
              limit: int = Query(default=50, ge=1, le=200), mention: str | None = None):
        return store.list_posts(after=after, limit=limit, mention=mention)

    @app.get("/attachments/{attachment_id}/meta")
    def attachment_meta(attachment_id: str):
        return store.get_attachment(attachment_id)[0]

    @app.get("/attachments/{attachment_id}")
    def attachment(attachment_id: str):
        meta, path = store.get_attachment(attachment_id)
        return FileResponse(path, media_type=meta["mime"], filename=meta["name"])

    @app.get("/stream")
    def stream(after: int | None = Query(default=None, ge=0, le=MAX_ID)):
        return StreamingResponse(post_events(store, hub, after), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})


def _write_routes(app: FastAPI, store: BoardStore, hub: PostHub, shutdown) -> None:
    @app.post("/members")
    def member(body: MemberInput):
        record, created = store.register_member(**body.model_dump())
        return JSONResponse(record, status_code=201 if created else 200)

    @app.post("/posts", status_code=201)
    async def post(body: PostInput):
        record = await asyncio.to_thread(store.create_post, **body.model_dump())
        await hub.notify()
        return record

    @app.post("/attachments", status_code=201)
    async def upload(request: Request):
        uploader, name, data = await receive_upload(request)
        return await asyncio.to_thread(store.add_attachment, uploader, name, data)

    @app.post("/shutdown", status_code=202)
    def stop(body: ShutdownInput, request: Request, background: BackgroundTasks):
        _shutdown_check(request, shutdown, body.instance_id)
        background.add_task(shutdown.callback)
        return {"status": "stopping"}
