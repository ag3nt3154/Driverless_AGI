"""
init.py — Initialize a new gnhf session.

Usage:
    python .dagi/skills/gnhf/scripts/init.py "<objective>"

Creates a new notes_{datetime}.md file for this session and writes its
name to .dagi/gnhf/.current_session so append_note.py knows where to write.

If prior session files exist, prints the tail of the most recent one for
orientation before starting the new session.

Exits with code 1 if the current branch is not 'dagi'.
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_DAGI_BRANCH = "dagi"
_GNHF_DIR = Path(".dagi/gnhf")
_CURRENT_SESSION_FILE = _GNHF_DIR / ".current_session"
_PRIOR_TAIL_LINES = 5


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "(detached HEAD)"


def most_recent_notes(gnhf_dir: Path) -> Path | None:
    files = sorted(gnhf_dir.glob("notes_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python init.py \"<objective>\"", file=sys.stderr)
        sys.exit(1)

    objective = sys.argv[1]
    branch = current_branch()

    if branch != _DAGI_BRANCH:
        print(
            f"Error: gnhf requires the '{_DAGI_BRANCH}' branch. "
            f"Currently on '{branch}'.\n"
            f"  Switch:  git checkout {_DAGI_BRANCH}\n"
            f"  Create:  git checkout -b {_DAGI_BRANCH}",
            file=sys.stderr,
        )
        sys.exit(1)

    _GNHF_DIR.mkdir(parents=True, exist_ok=True)

    # Show tail of most recent prior session for orientation
    prior = most_recent_notes(_GNHF_DIR)
    if prior:
        lines = prior.read_text(encoding="utf-8").splitlines()
        tail = lines[-_PRIOR_TAIL_LINES:] if len(lines) >= _PRIOR_TAIL_LINES else lines
        print(f"Prior session: {prior.name}")
        print("\n".join(tail))
        print()

    # Create new session file
    now = datetime.now()
    filename = f"notes_{now.strftime('%Y%m%d_%H%M%S')}.md"
    notes_path = _GNHF_DIR / filename

    notes_path.write_text(
        f"# GNHF Notes\n"
        f"**Objective:** {objective}\n"
        f"**Started:** {now.strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )

    _CURRENT_SESSION_FILE.write_text(filename, encoding="utf-8")

    print(f"New session: {filename}")
    print(f"Objective:   {objective}")
    print(f"Branch:      {branch}")


if __name__ == "__main__":
    main()
