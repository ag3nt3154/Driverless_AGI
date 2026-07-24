"""FastAPI document converter service."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import PlainTextResponse, JSONResponse

from services.doc_converter.converter import convert, _SUPPORTED
from services.doc_converter.converter.cache import hash_bytes, get_cached, store

app = FastAPI(title="DAGI Document Converter")


@app.post("/convert")
async def convert_document(file: UploadFile = File(...)) -> PlainTextResponse:
    """Convert an uploaded document to markdown text."""
    content = await file.read()

    if len(content) == 0:
        return JSONResponse(
            status_code=400,
            content={"error": "Uploaded file is empty.", "code": "FILE_EMPTY"},
        )

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED:
        return JSONResponse(
            status_code=422,
            content={
                "error": f"Unsupported file format: {ext}",
                "code": "UNSUPPORTED_FORMAT",
            },
        )

    content_hash = hash_bytes(content)
    cached = get_cached(content_hash)
    if cached is not None:
        return PlainTextResponse(cached, media_type="text/markdown")

    # Write to temp file for conversion
    suffix = Path(filename).suffix
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, dir=tempfile.gettempdir()
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        markdown = convert(tmp_path)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": str(exc), "code": "UNSUPPORTED_FORMAT"},
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "code": "CONVERSION_FAILED"},
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    store(content_hash, markdown)
    return PlainTextResponse(markdown, media_type="text/markdown")
