"""
append_note.py — Append a per-commit entry to the active gnhf session file.

Usage:
    python .dagi/skills/gnhf/scripts/append_note.py "<commit_hash>" "<note>"

Reads .dagi/gnhf/.current_session to find the active notes file.
Use "FAILED" as commit_hash for failure entries.

Exits with code 1 if .current_session is missing (run init.py first).
"""
import sys
from datetime import datetime
from pathlib import Path

_GNHF_DIR = Path(".dagi/gnhf")
_CURRENT_SESSION_FILE = _GNHF_DIR / ".current_session"


def main() -> None:
    if len(sys.argv) < 3:
        print(
            'Usage: python append_note.py "<commit_hash>" "<note>"',
            file=sys.stderr,
        )
        sys.exit(1)

    commit_hash = sys.argv[1]
    note = sys.argv[2]

    if not _CURRENT_SESSION_FILE.exists():
        print(
            f"Error: {_CURRENT_SESSION_FILE} not found. Run init.py first.",
            file=sys.stderr,
        )
        sys.exit(1)

    filename = _CURRENT_SESSION_FILE.read_text(encoding="utf-8").strip()
    notes_path = _GNHF_DIR / filename

    if not notes_path.exists():
        print(
            f"Error: session file '{notes_path}' not found. "
            f".current_session may be stale — run init.py to start a new session.",
            file=sys.stderr,
        )
        sys.exit(1)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {commit_hash} — {now}\n{note}\n"

    with notes_path.open("a", encoding="utf-8") as f:
        f.write(entry)

    print(f"Appended to {filename}.")


if __name__ == "__main__":
    main()
