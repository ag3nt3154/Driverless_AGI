import json
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _is_pair(item) -> bool:
    return isinstance(item, dict) and all(
        isinstance(item.get(k), str) for k in ("oldText", "newText")
    )


def _pairs_from_list(edits) -> list[tuple[str, str]] | str:
    """Validate an `edits` list into (old, new) pairs, or return an error string."""
    if not isinstance(edits, list) or not edits:
        return "Error: edits must be a non-empty list of {oldText, newText} objects"
    for i, item in enumerate(edits, 1):
        if not _is_pair(item):
            return f"Error: edit {i} of {len(edits)}: needs string oldText and newText"
    return [(item["oldText"], item["newText"]) for item in edits]


def _drop_placeholders(oldText, newText, edits) -> tuple:
    """Some providers send every advertised parameter, empty or stringified. Treat an
    empty `edits`, or empty oldText/newText next to `edits`, as absent; parse JSON text."""
    if isinstance(edits, str):
        try:
            edits = json.loads(edits)
        except ValueError:
            pass
    if edits == []:
        edits = None
    if edits is not None and not oldText and not newText:
        oldText = newText = None
    return oldText, newText, edits


def _collect_edits(oldText, newText, edits) -> list[tuple[str, str]] | str:
    """Return the (old, new) pairs to apply, or an error string for a malformed call."""
    if edits is not None:
        if oldText is not None or newText is not None:
            return "Error: pass either oldText/newText or edits, not both"
        return _pairs_from_list(edits)
    if not (isinstance(oldText, str) and isinstance(newText, str)):
        return "Error: pass oldText and newText, or an edits list"
    return [(oldText, newText)]


def _replace_once(content: str, old: str, new: str, p: Path) -> tuple[str, str | None]:
    """Replace the single occurrence of *old*; return (content, error-or-None)."""
    count = content.count(old)
    if count == 0:
        return content, f"oldText not found in {p}"
    if count > 1:
        return content, f"oldText found {count} times in {p} — must be unique"
    return content.replace(old, new, 1), None


class EditTool(BaseTool):
    name = "edit"
    description = (
        "Edit a file by replacing exact text. The oldText must match exactly "
        "(including whitespace). Use this for precise, surgical edits. "
        "Paths are relative to the project root. For several changes to one file, pass "
        "`edits` (a list of {oldText, newText}) instead of oldText/newText: they apply in "
        "order in one call, and if any fails nothing is written."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative to project root, or absolute)",
            },
            "oldText": {
                "type": "string",
                "description": "Exact text to find and replace (must match exactly)",
            },
            "newText": {"type": "string", "description": "New text to replace the old text with"},
            "edits": {
                "type": "array",
                "description": "Several replacements for this file, in order, all-or-nothing",
                "items": {
                    "type": "object",
                    "properties": {
                        "oldText": {"type": "string"},
                        "newText": {"type": "string"},
                    },
                    "required": ["oldText", "newText"],
                },
            },
        },
        "required": ["path"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def run(self, path: str, oldText: str | None = None, newText: str | None = None,
            edits: list | None = None) -> str:
        oldText, newText, edits = _drop_placeholders(oldText, newText, edits)
        pairs = _collect_edits(oldText, newText, edits)
        if isinstance(pairs, str):
            return pairs
        p = Path(path)
        if not p.is_absolute():
            p = self.cwd / p
        p = validate_path(p, self.allowed_roots)
        content = p.read_text(encoding="utf-8")
        n = len(pairs)
        for i, (old, new) in enumerate(pairs, 1):
            content, error = _replace_once(content, _normalise(old), _normalise(new), p)
            if error:
                where = f"edit {i} of {n}: " if edits is not None else ""
                return f"Error: {where}{error}"
        p.write_text(content, encoding="utf-8", newline="\n")
        if edits is None:
            return f"Edited {p}"
        return f"Edited {p} ({n} edit{'' if n == 1 else 's'})"
