import shutil
from pathlib import Path

from agent.base_tool import BaseTool
from tools._path_guard import validate_path


def _unique_dst(dst: Path) -> Path:
    """Return dst if it doesn't exist, otherwise append ` (N)` until a free name is found."""
    if not dst.exists():
        return dst
    stem = dst.stem
    suffix = dst.suffix
    parent = dst.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


class CopyTool(BaseTool):
    name = "copy"
    description = (
        "Copy (or move) a file or directory to a new location. "
        "Both source and destination must be within the project's allowed paths. "
        "If the destination already exists it is auto-renamed (e.g. 'file (1).txt'). "
        "Set move=true to delete the source after a successful copy."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "src": {
                "type": "string",
                "description": "Source path (file or directory) to copy from.",
            },
            "dst": {
                "type": "string",
                "description": (
                    "Destination path. If this is an existing directory the "
                    "source is placed inside it; otherwise it is the full target path."
                ),
            },
            "move": {
                "type": "boolean",
                "description": "When true, remove the source after a successful copy. Defaults to false.",
            },
        },
        "required": ["src", "dst"],
    }

    def __init__(self, cwd: Path = Path("."), allowed_roots: list[Path] | None = None):
        self.cwd = cwd
        self.allowed_roots = allowed_roots

    def _resolve(self, raw: str) -> Path:
        p = Path(raw)
        return p if p.is_absolute() else self.cwd / p

    def run(self, src: str, dst: str, move: bool = False) -> str:
        src_path = self._resolve(src)
        dst_path = self._resolve(dst)

        src_path = validate_path(src_path, self.allowed_roots)
        if not src_path.exists():
            return f"Error: source path does not exist: {src_path}"

        # If dst is an existing directory, place src inside it
        if dst_path.exists() and dst_path.is_dir() and not src_path.is_dir():
            dst_path = dst_path / src_path.name

        dst_path = validate_path(dst_path, self.allowed_roots)

        if src_path == dst_path:
            return f"Error: source and destination are the same path: {src_path}"

        # Guard: dst inside src would cause infinite copy
        try:
            dst_path.relative_to(src_path)
            return f"Error: destination '{dst_path}' is inside source '{src_path}'"
        except ValueError:
            pass

        final_dst = _unique_dst(dst_path)
        final_dst.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(src_path, final_dst)
        else:
            shutil.copy2(src_path, final_dst)

        if move:
            if src_path.is_dir():
                shutil.rmtree(src_path)
            else:
                src_path.unlink()
            verb = "Moved"
        else:
            verb = "Copied"

        note = (
            f" (renamed from '{dst_path.name}' to avoid collision)"
            if final_dst != dst_path else ""
        )
        return f"{verb} '{src_path}' -> '{final_dst}'{note}"
