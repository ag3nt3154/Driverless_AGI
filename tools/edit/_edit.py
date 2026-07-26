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

_DOC_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}


@dataclass
class _Resolved:
    """An edit reduced to a splice against the pre-edit line list."""

    start: int          # 0-based, inclusive
    end: int            # 0-based, exclusive
    lines: list[str]
    index: int          # position in the caller's edits list, for messages


def _norm(text: str) -> str:
    """Normalise line endings — used by replace_text (added in a later task)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _resolve_replace(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    if not pos:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: replace requires 'pos'")
    start = H.resolve_anchor(pos, anchors)
    end_anchor = edit.get("end")
    end = H.resolve_anchor(end_anchor, anchors) if end_anchor else start
    if end < start:
        raise H.AnchorError("E_INVALID_ANCHOR", f"edit {i}: 'end' precedes 'pos'")
    return _Resolved(start, end + 1, list(edit.get("lines", [])), i)


def _resolve_append(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    at = len(lines) if not pos else H.resolve_anchor(pos, anchors) + 1
    return _Resolved(at, at, list(edit.get("lines", [])), i)


def _resolve_prepend(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    pos = edit.get("pos")
    at = 0 if not pos else H.resolve_anchor(pos, anchors)
    return _Resolved(at, at, list(edit.get("lines", [])), i)


def _resolve_replace_text(edit: dict, i: int, lines: list[str], anchors: list[str]) -> _Resolved:
    """Desugar a substring replacement into an ordinary line-range splice.

    Resolving here means the positional path is the only execution path, so
    ordering and conflict rules apply uniformly to every op.
    """
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


_RESOLVERS = {
    "replace": _resolve_replace,
    "append": _resolve_append,
    "prepend": _resolve_prepend,
    "replace_text": _resolve_replace_text,
}


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file using hash anchors from `read` or `grep`. Each anchor is a "
        "`LINE#HASH` token (e.g. `18#aB3`) that is re-verified against the file "
        "before the edit is applied, so an edit can never land on the wrong line. "
        "Pass a list of edits; they are applied together against a single "
        "pre-edit snapshot. Returns fresh anchors for the changed region. "
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
                            "enum": ["replace", "append", "prepend", "replace_text"],
                            "description": "Operation kind",
                        },
                        "pos": {
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
                        "oldText": {
                            "type": "string",
                            "description": (
                                "replace_text only: exact unique substring to replace. "
                                "Fallback for when an anchor has gone stale — prefer "
                                "`replace` with a fresh anchor."
                            ),
                        },
                        "newText": {
                            "type": "string",
                            "description": "replace_text only: replacement substring",
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

        if not edits:
            return "Error: [E_INVALID_PATCH] 'edits' must contain at least one operation."

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return f"Error: cannot read {p.name} as UTF-8 text."

        anchors = H.build_anchors(lines)
        try:
            resolved = self._resolve_all(edits, lines, anchors)
        except H.AnchorError as exc:
            return f"Error: [{exc.code}] {exc.message}"

        new_lines = self._apply(lines, resolved)
        p.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
        return f"Edited {p.name}"

    def _resolve_all(
        self,
        edits: list[dict],
        lines: list[str],
        anchors: list[str],
    ) -> list[_Resolved]:
        resolved: list[_Resolved] = []
        for i, edit in enumerate(edits):
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
