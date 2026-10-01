# .dagi/subagents/read-large-file/main.py
"""read_large_file — indexed digest of a file too large for context.

Loads the file with the same loader as `read`, then hands the selection to the
reader subprocess (tools/read/_reader_controller.py), which reads it chunk by
chunk with a running summary and merges its notes into an index. Results are
cached by file content + query + model + READER_VERSION.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from agent import DAGI_ROOT
from agent.base_tool import BaseTool
from tools._hash_cache import cache_path, get_or_compute
from tools._path_guard import validate_path
from tools.read._reader_job import ReaderLaunchContext, run_reader
from tools.read._selection import make_selection
from tools.read._source import SourceError, load_source

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker
    from agent.session_log import SessionLog
    from agent.parent_context import ParentContextProvider

# Bump when the reader prompt, chunking or index format changes, so cached
# digests from the old version are not served.
READER_VERSION = 1
_CACHE_SUBDIR = "read_large_file"


class ReadLargeFileTool(BaseTool):
    name = "read_large_file"
    description = (
        "Read a whole file that is too large for context and return an index: an "
        "overview, a table of sections with line ranges, and per-section key points "
        "with verbatim excerpts and line numbers. Use it when `read` shows a "
        "truncated result and you need the whole file, then `read` with "
        "offset/limit to fetch the exact lines you need. Also works on saved tool "
        "output paths from a truncation marker. Pass `query` to focus the index on "
        "what you are looking for. Results are cached, so repeating a call is cheap."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file (relative to project root, or absolute).",
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional focus: what you need from the file. Omit for a "
                    "general index."
                ),
            },
            "offset": {
                "type": "integer",
                "description": "Optional first line to include (1-indexed).",
            },
            "limit": {
                "type": "integer",
                "description": "Optional number of lines to include.",
            },
            "pages": {
                "type": "string",
                "description": "Optional PDF page range (e.g. '1-5,8').",
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        config: "AgentConfig",
        callbacks: "AgentCallbacks | None" = None,
        tracker: "SessionTracker | None" = None,
        session_log: "SessionLog | None" = None,
        parent_context: "ParentContextProvider | None" = None,
    ) -> None:
        self._config = config
        self._callbacks = callbacks
        # Kept for the subagent-tool convention. The reader is a fixed loop that
        # never sees the parent's conversation, so neither is forwarded.
        self._session_log = session_log
        self._parent_context = parent_context

    def _reader_model(self) -> str:
        worker = getattr(self._config, "worker_config", None)
        return (worker.model if worker else None) or self._config.model

    def run(
        self,
        path: str,
        query: str = "",
        offset: int = 1,
        limit: int | None = None,
        pages: str | None = None,
    ) -> str:
        project = Path(self._config.project_path)
        roots = None if self._config.sandbox_mode else [DAGI_ROOT, project]
        p = Path(path)
        if not p.is_absolute():
            p = project / p
        p = validate_path(p, roots)

        try:
            src = load_source(
                p,
                pages=pages,
                service_url=(self._config.services or {}).get("doc_converter"),
                project_path=project,
            )
        except (SourceError, ValueError) as exc:
            return str(exc)

        total = len(src.lines)
        selection = make_selection(
            p, src.lines,
            offset=max(1, offset),
            limit=total if limit is None else max(1, limit),
            header=src.header,
            editable_path=src.editable_path,
        )
        if not selection.text.strip():
            return f"Error: '{p.name}' has no content in the selected range."

        query = (query or "").strip()
        key = json.dumps({
            "v": READER_VERSION,
            "text": hashlib.sha256(selection.text.encode("utf-8")).hexdigest(),
            "scope": selection.scope,
            "query": " ".join(query.lower().split()),
            "model": self._reader_model(),
            "reserve": self._config.reserve_tokens,
        }, sort_keys=True).encode("utf-8")

        cached, _ = cache_path(key, _CACHE_SUBDIR, "md", project)
        if cached.is_file():
            return "(cached) " + cached.read_text(encoding="utf-8")

        on_event = None
        if self._callbacks and self._callbacks.on_subagent_event_factory:
            on_event = self._callbacks.on_subagent_event_factory("read-large-file")

        outcome = run_reader(
            selection,
            query=query,
            context=ReaderLaunchContext(
                project_path=project,
                parent_reserve=self._config.reserve_tokens,
                on_event=on_event,
            ),
        )
        if not outcome.ok:
            return outcome.content

        try:
            get_or_compute(key, _CACHE_SUBDIR, "md", project, lambda: outcome.content)
        except OSError:
            pass  # caching is best-effort
        return outcome.content
