"""Text-based edit tool — replaces exact substrings without hash anchors.

Use `edit` (hash-anchored) when possible; this tool is a fallback for cases
where anchors have gone stale and re-reading is not practical.
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
    start: int   # 0-based, inclusive
    end: int     # 0-based, exclusive
    lines: list[str]
    index: int


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _doc_guard(p: Path) -> str | None:
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


def _resolve_replace_text(edit: dict, i: int, lines: list[str]) -> _Resolved:
    """Desugar a substring replacement into an ordinary line-range splice."""
    old = _norm(edit.get("oldText", ""))
    new = _norm(edit.get("newText", ""))
    if not old:
        raise H.AnchorError("E_INVALID_PATCH", f"edit {i}: replace_text requires 'oldText'")

    content = "\n".join(lines)
    count = content.count(old)
    if count == 0:
        raise H.AnchorError("E_TEXT_NOT_FOUND", f"edit {i}: oldText not found in file")
    if count > 1:
        raise H.AnchorError(
            "E_TEXT_AMBIGUOUS",
            f"edit {i}: oldText found {count} times; use a hash anchor instead",
        )

    offset = content.index(old)
    start = content.count("\n", 0, offset)
    end = content.count("\n", 0, offset + len(old))
    span = "\n".join(lines[start:end + 1])
    return _Resolved(start, end + 1, span.replace(old, new, 1).split("\n"), i)


def _check_conflicts(resolved: list[_Resolved]) -> None:
    ordered = sorted(resolved, key=lambda r: (r.start, r.end))
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.start < prev.end:
            raise H.AnchorError(
                "E_CONFLICT",
                f"edits {prev.index} and {nxt.index} target overlapping line ranges",
            )


def _changed_span(resolved: list[_Resolved]) -> tuple[int | None, int | None]:
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


class EditTextTool(BaseTool):
    name = "edit_text"
    description = (
        "Edit a file by replacing exact unique substrings — no hash anchors required. "
        "Use as a fallback when anchors from `read` are stale and re-reading is not practical. "
        "Supported operation (implicit, no `op` field needed): "
        "replace_text — replace one unique occurrence of `oldText` with `newText`. "
        "The substring must appear exactly once in the file; if it appears 0 or 2+ times "
        "the edit is rejected. Omit `newText` (or pass an empty string) to delete the text. "
        "Multiple replacements are applied against a single pre-edit snapshot with "
        "overlap conflict detection. Returns fresh anchors for the changed region. "
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
                "description": "Text replacements applied against one pre-edit snapshot",
                "items": {
                    "type": "object",
                    "properties": {
                        "oldText": {
                            "type": "string",
                            "description": (
                                "Exact unique substring to replace. Must appear exactly "
                                "once in the file; use `edit` with a hash anchor for "
                                "ambiguous text."
                            ),
                        },
                        "newText": {
                            "type": "string",
                            "description": "Replacement substring",
                        },
                    },
                    "required": ["oldText"],
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

        try:
            resolved = self._resolve_all(edits, lines)
            _check_conflicts(resolved)
        except H.AnchorError as exc:
            return f"Error: [{exc.code}] {exc.message}"

        new_lines = self._apply(lines, resolved)
        if new_lines == lines:
            return f"No changes made to {p.name}\nClassification: noop"

        p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
        return _render_anchors(new_lines, resolved)

    def _resolve_all(self, edits: list[dict], lines: list[str]) -> list[_Resolved]:
        resolved: list[_Resolved] = []
        for i, edit in enumerate(edits):
            resolved.append(_resolve_replace_text(edit, i, lines))
        return resolved

    @staticmethod
    def _apply(lines: list[str], resolved: list[_Resolved]) -> list[str]:
        out = list(lines)
        for e in sorted(resolved, key=lambda r: (r.start, r.index), reverse=True):
            out[e.start:e.end] = e.lines
        return out
