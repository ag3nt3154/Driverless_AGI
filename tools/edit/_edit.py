"""Hash-anchored edit tool.

Edits target LINE#HASH anchors from `read` or `grep`. Validation is stateless:
the anchor table is rebuilt from disk on every call, so a changed file produces
a loud E_STALE_ANCHOR rather than a silent wrong-line edit.
"""
from dataclasses import dataclass
from pathlib import Path

from agent.base_tool import BaseTool
from tools import _hashline as H
from tools._path_guard import validate_path
from tools.read._doc_service import cache_path_for

_DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}


@dataclass
class _Resolved:
    """An edit reduced to a splice against the pre-edit line list."""

    start: int          # 0-based, inclusive
    end: int            # 0-based, exclusive
    lines: list[str]
    index: int          # position in the caller's edits list, for messages


def _doc_guard(p: Path) -> str | None:
    """Redirect document edits to the converted-markdown cache entry."""
    ext = p.suffix.lower()
    if ext not in _DOC_EXTS:
        return None
    try:
        target = cache_path_for(p, p.parent)
        hint = f".dagi/hash_cache/doc_convert/{target.name}"
    except OSError:
        hint = ".dagi/hash_cache/doc_convert/<sha256>.md"
    return (
        f"Error: cannot edit {ext} directly — edit the converted markdown at "
        f"{hint} (read the document first to have it converted)."
    )


def _resolve_replace(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    start_anchor = edit.get("start")
    if not start_anchor:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: replace requires 'start'")
    start = H.resolve_anchor(start_anchor, anchors)
    end_anchor = edit.get("end")
    end = H.resolve_anchor(end_anchor, anchors) if end_anchor else start
    if end < start:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: 'end' precedes 'start'")
    return _Resolved(start, end + 1, list(edit.get("lines", [])), i)


def _resolve_append(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    start_anchor = edit.get("start")
    at = len(lines) if not start_anchor else H.resolve_anchor(start_anchor, anchors) + 1
    return _Resolved(at, at, list(edit.get("lines", [])), i)


def _resolve_prepend(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    start_anchor = edit.get("start")
    at = 0 if not start_anchor else H.resolve_anchor(start_anchor, anchors)
    return _Resolved(at, at, list(edit.get("lines", [])), i)


def _check_conflicts(resolved: list[_Resolved]) -> None:
    ordered = sorted(resolved, key=lambda r: (r.start, r.end))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise H.AnchorError(
                "E_CONFLICT",
                f"edits {prev.index} and {nxt.index} target overlapping line ranges",
            )


def _changed_span(resolved: list[_Resolved]) -> tuple[int | None, int | None]:
    """First and last changed line in POST-edit 1-indexed coordinates."""
    offset = 0
    first: int | None = None
    last: int | None = None
    for e in sorted(resolved, key=lambda r: (r.start, r.index)):
        post_start = e.start + offset
        candidate_last = post_start + len(e.lines) if e.lines else post_start
        first = post_start + 1 if first is None else min(first, post_start + 1)
        last = candidate_last if last is None else max(last, candidate_last)
        offset += len(e.lines) - (e.end - e.start)
    return first, last


def _render_anchors(new_lines: list[str], resolved: list[_Resolved]) -> str:
    first, last = _changed_span(resolved)
    span = H.compute_affected_range(first, last, len(new_lines))
    if span is None:
        return H.ANCHORS_OMITTED_TEXT
    start, end = span
    anchors = H.build_anchors(new_lines)
    block = (
        f"--- Anchors {start}-{end} ---\n"
        + H.format_region(new_lines, anchors, start, end)
    )
    if len(block.encode("utf-8")) > H.ANCHOR_TEXT_BUDGET_BYTES:
        return H.ANCHORS_OMITTED_TEXT
    return block


_RESOLVERS = {
    "replace": _resolve_replace,
    "append": _resolve_append,
    "prepend": _resolve_prepend,
}


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file using hash anchors from `read` or `grep`. Each anchor is a "
        "`LINE#HASH` token (e.g. `18#aB3`) that is re-verified against the file "
        "before the edit is applied, so an edit can never land on the wrong line. "
        "Supported ops: "
        "replace — swap lines from `start` to `end` (inclusive) with `lines`; omit `end` for single-line replace. "
        "append — insert `lines` after `start`; omit `start` to append at end of file. "
        "prepend — insert `lines` before `start`; omit `start` to prepend at start of file. "
        "All edits in a call are applied against a single pre-edit snapshot with overlap conflict detection. "
        "Returns fresh anchors for the changed region. "
        "Paths are relative to the project root."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative to project root, or absolute)",
            },
            "edits": {
                "type": "array",
                "description": "Edit operations applied against one pre-edit snapshot",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {
                            "type": "string",
                            "enum": ["replace", "append", "prepend"],
                            "description": "Operation kind",
                        },
                        "start": {
                            "type": "string",
                            "description": (
                                "Anchor of the target line, e.g. '18#aB3'. For append, "
                                "omit to insert at end of file; for prepend, omit to "
                                "insert at start of file."
                            ),
                        },
                        "end": {
                            "type": "string",
                            "description": "Optional end anchor for an inclusive range replace",
                        },
                        "lines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Replacement lines, without any LINE#HASH prefix",
                        },
                    },
                    "required": ["op"],
                },
            },
        },
        "required": ["path", "edits"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, edits: list[dict]) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)

        doc_error = _doc_guard(p)
        if doc_error:
            return doc_error

        if not edits:
            return "Error: [E_INVALID_PATCH] 'edits' must contain at least one operation."

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"Error: cannot read {p.name} as UTF-8 text."

        anchors = H.build_anchors(lines)
        try:
            resolved = self._resolve_all(edits, lines, anchors)
            _check_conflicts(resolved)
        except H.AnchorError as exc:
            return f"Error: [{exc.code}] {exc.message}"

        new_lines = self._apply(lines, resolved)
        if new_lines == lines:
            return f"No changes made to {p.name}\nClassification: noop"

        p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
        return _render_anchors(new_lines, resolved)

    def _resolve_all(
        self,
        edits: list[dict],
        lines: list[str],
        anchors: list[str],
    ) -> list[_Resolved]:
        resolved: list[_Resolved] = []
        for i, edit in enumerate(edits):
            offending = H.contains_display_prefix(edit.get("lines") or [])
            if offending:
                raise H.AnchorError(
                    "E_INVALID_PATCH",
                    f"edit {i}: content line looks like tool display output "
                    f"({offending!r}); supply file content without LINE#HASH prefixes",
                )
            op = edit.get("op")
            resolver = _RESOLVERS.get(op)
            if resolver is None:
                raise H.AnchorError(
                    "E_INVALID_PATCH",
                    f"edit {i}: unknown op {op!r}; expected one of {sorted(_RESOLVERS)}",
                )
            resolved.append(resolver(edit, i, lines, anchors))
        return resolved

    @staticmethod
    def _apply(lines: list[str], resolved: list[_Resolved]) -> list[str]:
        """Splice bottom-up so unapplied indices stay valid."""
        out = list(lines)
        for e in sorted(resolved, key=lambda r: (r.start, r.index), reverse=True):
            out[e.start:e.end] = e.lines
        return out
