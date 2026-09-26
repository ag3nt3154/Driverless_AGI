"""Create a portable project wiki without replacing any existing file."""

import argparse
from datetime import date
from pathlib import Path
import stat
import sys


PAGES = {
    "architecture.md": ("Architecture", "Current components and their relationships."),
    "workflows.md": ("Workflows", "Current development and execution flows."),
    "business-context.md": ("Business Context", "Project purpose, users, and constraints."),
    "decisions/index.md": ("Decisions", "Recorded choices and their rationale."),
    "errors/index.md": ("Errors", "Observed issues and verified fixes."),
    "notes/index.md": ("Notes", "Useful findings and open questions."),
}


def _scaffold() -> dict[str, str]:
    updated = f"> Last updated: {date.today().isoformat()}\n"
    index = "# Project Wiki\n\nProject knowledge and navigation.\n\n" + updated + "\n"
    files = {}
    for relative, (title, summary) in PAGES.items():
        index += f"- [{title}]({relative}): {summary}\n"
        backlink = "../index.md" if "/" in relative else "index.md"
        files[f"wiki/{relative}"] = (
            f"# {title}\n\n{summary}\n\n{updated}\n"
            f"No entries recorded yet.\n\n[Project wiki]({backlink})\n"
        )
    return {"wiki/index.md": index, **files}


def _contained(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise OSError(f"Path escapes project root: {path} -> {resolved}")
    return resolved


def _existing_mode(root: Path, path: Path) -> int | None:
    """Only a missing directory entry means absence; preserve permission errors."""
    _contained(root, path)
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    # Strict resolution rejects broken links, including broken Windows junctions.
    resolved = path.resolve(strict=True)
    _contained(root, resolved)
    return path.stat().st_mode


def _check_target(root: Path, target: Path) -> bool:
    relative = target.relative_to(root)
    parent = root
    for part in relative.parts[:-1]:
        parent /= part
        mode = _existing_mode(root, parent)
        if mode is not None and not stat.S_ISDIR(mode):
            raise NotADirectoryError(f"Expected a directory: {parent}")
    mode = _existing_mode(root, target)
    if mode is None:
        return False
    if not stat.S_ISREG(mode):
        raise OSError(f"Expected a regular file: {target}")
    return True


def _create_file(root: Path, target: Path, content: str) -> bool:
    if _check_target(root, target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    _check_target(root, target)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    except FileExistsError:
        # A competing initializer is safe only if it created a contained regular file.
        if not _check_target(root, target):
            raise OSError(f"Target disappeared during initialization: {target}")
        return False
    return True


def initialize_wiki(project_root: Path) -> list[str]:
    """Return created relative paths; preserve completed files on any later failure."""
    root = Path(project_root).resolve(strict=True)
    if not stat.S_ISDIR(root.stat().st_mode):
        raise NotADirectoryError(f"Project root must be an existing directory: {root}")
    files = _scaffold()
    # Validate all seven targets before creating any directories or files.
    for relative in files:
        _check_target(root, root / relative)
    created = []
    for relative, content in files.items():
        target = root / relative
        try:
            if _create_file(root, target, content):
                created.append(relative)
        except OSError as exc:
            raise OSError(f"Could not initialize {target}: {exc}") from exc
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        created = initialize_wiki(args.project_root)
    except (OSError, RuntimeError) as exc:
        print(f"Wiki initialization failed for {args.project_root}: {exc}", file=sys.stderr)
        return 1
    for relative in _scaffold():
        status = "Created" if relative in created else "Preserved"
        print(f"{status}: {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
