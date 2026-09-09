"""tools/read/_reader_job.py — Job manifest, file transport, and delegation.

ReaderJob is the parent→child invocation manifest passed to the reader
subprocess. No API credentials are stored here; the subprocess resolves its
own client from the inherited config.

File transport (write_reader_job / load_reader_job) serializes the selection
snapshot to a versioned JSON temp file. The subprocess validates schema,
offsets and source digest on load to detect stale or tampered manifests.

delegate_selection is the single public run_subagent call site for the
new reader path, used by ReadTool._delegate_to_read_large_text.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from agent.parent_context import ParentContextProvider
    from tools.read._selection import ReadSelection


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReaderReturnFormat:
    """Wrapper metadata for the final parent-facing return string."""
    signpost: str
    handoff_path: Path


@dataclass(frozen=True)
class ReaderJob:
    """Immutable invocation manifest for one reader subprocess run.

    version must be 1 for this schema.
    """
    version: int
    selection: ReadSelection
    query: str
    parent_reserve: int
    return_format: ReaderReturnFormat


@dataclass
class ReaderJobSpec:
    """Partial job specification passed to run_subagent before handoff_path is known."""
    selection: ReadSelection
    query: str
    parent_reserve: int


@dataclass
class ReaderLaunchContext:
    """Grouped dependencies for delegate_selection."""
    project_path: Path
    parent_reserve: int
    on_event: Callable[[str], None] | None = None
    parent_context: Any = None


# ---------------------------------------------------------------------------
# Pure renderer
# ---------------------------------------------------------------------------

def render_reader_return(content: str, fmt: ReaderReturnFormat) -> str:
    """Render the complete parent-facing return string from digest content."""
    return f"{fmt.signpost}\n\n{content}"


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------

def _span_to_dict(span: Any) -> dict:
    return {
        "start": span.start,
        "end": span.end,
        "source_start": span.source_start,
        "line_start": span.line_start,
        "page": span.page,
    }


def _dict_to_span(d: dict) -> Any:
    from tools.read._selection import SourceSpan
    return SourceSpan(
        start=d["start"],
        end=d["end"],
        source_start=d["source_start"],
        line_start=d["line_start"],
        page=d.get("page"),
    )


def _selection_to_dict(sel: "ReadSelection") -> dict:
    return {
        "path": str(sel.path),
        "text": sel.text,
        "spans": [_span_to_dict(s) for s in sel.spans],
        "header": sel.header,
        "editable_path": str(sel.editable_path) if sel.editable_path else None,
        "scope": sel.scope,
        "text_digest": hashlib.sha256(sel.text.encode("utf-8")).hexdigest(),
    }


def _dict_to_selection(d: dict) -> "ReadSelection":
    from tools.read._selection import ReadSelection
    return ReadSelection(
        path=Path(d["path"]),
        text=d["text"],
        spans=tuple(_dict_to_span(s) for s in d["spans"]),
        header=d.get("header"),
        editable_path=Path(d["editable_path"]) if d.get("editable_path") else None,
        scope=d["scope"],
    )


def _return_format_to_dict(fmt: ReaderReturnFormat) -> dict:
    return {"signpost": fmt.signpost, "handoff_path": str(fmt.handoff_path)}


def _dict_to_return_format(d: dict) -> ReaderReturnFormat:
    return ReaderReturnFormat(
        signpost=d["signpost"],
        handoff_path=Path(d["handoff_path"]),
    )


# ---------------------------------------------------------------------------
# File transport
# ---------------------------------------------------------------------------

def write_reader_job(job: ReaderJob, directory: Path) -> Path:
    """Serialize job to a versioned JSON temp file in directory.

    Returns the path to the written file. The caller must ensure the file
    is deleted when the subprocess reaches a terminal state.
    """
    payload = {
        "version": job.version,
        "selection": _selection_to_dict(job.selection),
        "query": job.query,
        "parent_reserve": job.parent_reserve,
        "return_format": _return_format_to_dict(job.return_format),
    }
    directory.mkdir(parents=True, exist_ok=True)
    fd, path_str = tempfile.mkstemp(suffix=".json", prefix="dagi_reader_job_", dir=directory)
    path = Path(path_str)
    try:
        os.close(fd)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def load_reader_job(path: Path) -> ReaderJob:
    """Load and validate a reader job manifest from path.

    Raises ValueError on schema violations or source-digest mismatch.
    Raises FileNotFoundError if path does not exist.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    version = raw.get("version")
    if version != 1:
        raise ValueError(f"Unsupported reader job version: {version}")

    sel_dict = raw.get("selection")
    if not isinstance(sel_dict, dict):
        raise ValueError("Missing or invalid 'selection' field in reader job")

    stored_digest = sel_dict.get("text_digest", "")
    text = sel_dict.get("text", "")
    actual_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if stored_digest and actual_digest != stored_digest:
        raise ValueError(
            f"Reader job source digest mismatch: stored={stored_digest!r} "
            f"actual={actual_digest!r}"
        )

    selection = _dict_to_selection(sel_dict)
    return_format = _dict_to_return_format(raw["return_format"])

    return ReaderJob(
        version=version,
        selection=selection,
        query=raw.get("query", ""),
        parent_reserve=int(raw["parent_reserve"]),
        return_format=return_format,
    )


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------

def delegate_selection(
    selection: "ReadSelection",
    *,
    query: str,
    context: ReaderLaunchContext,
) -> str:
    """Build a ReaderJobSpec, spawn the reader subprocess, format the return.

    The single run_subagent call site for the new reader controller path.
    Uses the 'read-large-text' preset for subprocess configuration and
    injects the reader_job_spec so subagent_main routes to the controller.
    """
    import tools.subagent_api as _subagent_api
    from tools._handoff_format import dispatch_status_result

    spec = ReaderJobSpec(
        selection=selection,
        query=query,
        parent_reserve=context.parent_reserve,
    )

    result = _subagent_api.run_subagent(
        task=f"Read the file at: {selection.path}\n{selection.scope}",
        preset="read-large-text",
        project_path=context.project_path,
        on_event=context.on_event,
        parent_context=context.parent_context,
        reader_job_spec=spec,
    )

    trailer = "Summary below." if result.is_ok else "Delegation result below."
    signpost = (
        f"[{selection.scope} too large for inline display. "
        f"Delegated to reader. {trailer}]"
    )

    if result.is_ok:
        from tools._handoff_format import format_handoff_content
        unverified = result.status == "ok_unverified"
        body = format_handoff_content(
            result.handoff_text,
            str(result.handoff_path),
            unverified=unverified,
        )
        return f"{signpost}\n\n{body}"

    return f"{signpost}\n\n{dispatch_status_result({'status': result.status, 'pid': result.pid, 'message': result.message}, 'reader')}"
