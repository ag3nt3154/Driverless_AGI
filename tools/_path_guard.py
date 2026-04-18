"""
tools/_path_guard.py — Shared path sandboxing helper.

All file-touching tools call validate_path() before any I/O so that the agent
can only read/write within the allowed roots (dagi_root and working_dir).
BashTool is intentionally excluded — shell commands cannot be meaningfully
sandboxed via argument inspection.
"""
from pathlib import Path


class PathNotAllowedError(ValueError):
    """Raised when a resolved path escapes all allowed roots."""


def validate_path(p: Path, allowed_roots: list[Path]) -> Path:
    """Resolve *p* and verify it sits under at least one of *allowed_roots*.

    allowed_roots entries may be directories (any descendant is allowed) or
    exact file paths (only that precise file is allowed). This lets plan mode
    register write tools scoped to a single plan document.

    Returns the resolved path on success.
    Raises PathNotAllowedError with a human-readable message on failure.
    Inherits ValueError so ToolRegistry.dispatch()'s except-Exception guard
    catches it and returns the message to the model as a tool result.
    """
    resolved = p.resolve()
    for root in allowed_roots:
        root_resolved = root.resolve()
        if root_resolved.is_file():
            if resolved == root_resolved:
                return resolved
        else:
            try:
                resolved.relative_to(root_resolved)
                return resolved
            except ValueError:
                continue
    allowed_strs = ", ".join(str(r.resolve()) for r in allowed_roots)
    raise PathNotAllowedError(
        f"Path '{resolved}' is outside allowed roots: {allowed_strs}"
    )
