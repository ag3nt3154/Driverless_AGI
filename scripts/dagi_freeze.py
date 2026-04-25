#!/usr/bin/env python3
"""
scripts/dagi_freeze.py — Snapshot and restore the DAGI core for safe patch testing.

Creates file-system snapshots of the agent, tools, skills, and config so you can
freeze a known-good state, test a patch, and do a true revert if something breaks.
Snapshots are stored in snapshots/ at the project root (gitignored).

Usage:
    conda run -n dagi python scripts/dagi_freeze.py freeze [--label LABEL] [--dry-run]
    conda run -n dagi python scripts/dagi_freeze.py list
    conda run -n dagi python scripts/dagi_freeze.py restore <snapshot-id> [--no-backup]
    conda run -n dagi python scripts/dagi_freeze.py diff    <snapshot-id>
    conda run -n dagi python scripts/dagi_freeze.py delete  <snapshot-id> [--force]

Examples:
    # Save state before a patch
    python scripts/dagi_freeze.py freeze --label before-tool-refactor

    # Check what changed
    python scripts/dagi_freeze.py diff 20260425_143021_before-tool-refactor

    # Roll back completely (auto-saves a pre-restore backup first)
    python scripts/dagi_freeze.py restore 20260425_143021_before-tool-refactor
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows so Unicode characters in print() don't crash.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

try:
    from rich.console import Console
    _RICH = True
    _console = Console()
except ImportError:
    _RICH = False
    _console = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

SNAPSHOT_PATHS = [
    "agent",
    "tools",
    ".dagi/skills",
    "cli.py",
    "main.py",
    "hist.py",
    "_probe.py",
    "SOUL.md",
    "AGENTS.md",
    "CLAUDE.local.md",
    "pyproject.toml",
    "config.yaml",
]

# Any path component matching one of these will be pruned during directory walk.
SKIP_PARTS: set[str] = {
    "__pycache__",
    ".git",
}

# Any path (relative, posix) whose prefix matches one of these is skipped.
SKIP_PREFIXES: tuple[str, ...] = (
    ".dagi/logs",
    ".dagi/plans",
    ".dagi/memory",
    ".dagi/snapshots",
    "archive",
    "snapshots",
)

SNAPSHOTS_DIR = "snapshots"
METADATA_FILE = "SNAPSHOT.json"
LARGE_FILE_WARN_BYTES = 50 * 1024 * 1024  # 50 MB


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    if _RICH:
        _console.print(f"[green][OK][/green] {msg}")
    else:
        print(f"[OK] {msg}")


def _warn(msg: str) -> None:
    if _RICH:
        _console.print(f"[yellow][!][/yellow]  {msg}")
    else:
        print(f"[!]  {msg}", file=sys.stderr)


def _err(msg: str) -> None:
    if _RICH:
        _console.print(f"[red][ERR][/red] {msg}")
    else:
        print(f"[ERR] {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    if _RICH:
        _console.print(f"[cyan]-->[/cyan] {msg}")
    else:
        print(f"    {msg}")


def _format_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# SnapshotManager
# ---------------------------------------------------------------------------

class SnapshotManager:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def snapshots_root(self) -> Path:
        return self.root / SNAPSHOTS_DIR

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _snapshot_dir(self, snapshot_id: str) -> Path:
        return self.snapshots_root / snapshot_id

    def _resolve_id(self, snapshot_id: str) -> str:
        """Resolve a prefix to a unique full snapshot ID, or return as-is."""
        if not self.snapshots_root.exists():
            return snapshot_id
        matches = [
            d.name for d in self.snapshots_root.iterdir()
            if d.is_dir() and d.name.startswith(snapshot_id)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            _err(f"Ambiguous snapshot prefix '{snapshot_id}': {', '.join(sorted(matches))}")
            sys.exit(1)
        return snapshot_id  # not found, will fail later with a clear message

    def _git_info(self) -> tuple[str | None, str | None, bool]:
        """Return (full_hash, branch, is_dirty). All None/False on failure."""
        try:
            h = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root, capture_output=True, text=True, timeout=5,
            )
            b = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.root, capture_output=True, text=True, timeout=5,
            )
            d = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.root, capture_output=True, text=True, timeout=5,
            )
            git_hash = h.stdout.strip() if h.returncode == 0 else None
            branch = b.stdout.strip() if b.returncode == 0 else None
            dirty = bool(d.stdout.strip()) if d.returncode == 0 else False
            return git_hash, branch, dirty
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None, None, False

    def _dagi_version(self) -> str | None:
        pyproject = self.root / "pyproject.toml"
        if not pyproject.exists():
            return None
        try:
            for line in pyproject.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
        return None

    def _should_skip(self, rel: Path) -> bool:
        posix = rel.as_posix()
        if any(posix.startswith(p) for p in SKIP_PREFIXES):
            return True
        return any(part in SKIP_PARTS for part in rel.parts)

    def _collect_files(self) -> tuple[list[Path], list[str]]:
        """Return (relative_file_paths, skipped_missing_entries)."""
        files: list[Path] = []
        missing: list[str] = []

        for entry in SNAPSHOT_PATHS:
            abs_path = self.root / entry
            if not abs_path.exists():
                missing.append(entry)
                continue
            if abs_path.is_file():
                files.append(Path(entry))
            else:
                for dirpath, dirnames, filenames in os.walk(abs_path):
                    dirpath_p = Path(dirpath)
                    rel_dir = dirpath_p.relative_to(self.root)
                    # Prune skipped directories in-place so os.walk skips them.
                    dirnames[:] = [
                        d for d in dirnames
                        if not self._should_skip(rel_dir / d)
                    ]
                    for fname in filenames:
                        rel_file = rel_dir / fname
                        if not self._should_skip(rel_file):
                            files.append(rel_file)

        return files, missing

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def freeze(self, label: str | None = None, dry_run: bool = False) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_id = f"{ts}_{label}" if label else ts
        snapshot_id = base_id
        # Handle timestamp collision.
        counter = 1
        snap_dir = self._snapshot_dir(snapshot_id)
        while snap_dir.exists():
            snapshot_id = f"{base_id}_{counter}"
            snap_dir = self._snapshot_dir(snapshot_id)
            counter += 1

        files, missing = self._collect_files()
        git_hash, branch, dirty = self._git_info()

        total_size = 0
        file_records: list[dict] = []
        for rel in files:
            abs_f = self.root / rel
            stat = abs_f.stat()
            size = stat.st_size
            total_size += size
            if size > LARGE_FILE_WARN_BYTES:
                _warn(f"Large file ({_format_size(size)}): {rel.as_posix()}")
            file_records.append({
                "path": rel.as_posix(),
                "size": size,
                "mtime": stat.st_mtime,
            })

        if dry_run:
            _info(f"[dry-run] Would create snapshot: {snapshot_id}")
            _info(f"[dry-run] Files: {len(files)}  Total: {_format_size(total_size)}")
            for rec in file_records:
                print(f"  {rec['path']}")
            if missing:
                _warn(f"Missing (would skip): {', '.join(missing)}")
            return snapshot_id

        snap_dir.mkdir(parents=True, exist_ok=True)
        for rel in files:
            dest = snap_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / rel, dest)

        metadata = {
            "id": snapshot_id,
            "label": label,
            "created_at": datetime.now().isoformat(),
            "git_hash": git_hash,
            "git_branch": branch,
            "git_dirty": dirty,
            "files": file_records,
            "total_files": len(files),
            "total_size": total_size,
            "skipped_missing": missing,
            "dagi_version": self._dagi_version(),
        }
        (snap_dir / METADATA_FILE).write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        _ok(f"Snapshot saved: {snapshot_id}")
        _info(f"Files: {len(files)}  Size: {_format_size(total_size)}")
        if missing:
            _warn(f"Not found (skipped): {', '.join(missing)}")
        if any(r["path"] == "config.yaml" for r in file_records):
            _warn("config.yaml captured - it may contain API key env var names.")
        return snapshot_id

    def list_snapshots(self) -> list[dict]:
        if not self.snapshots_root.exists():
            return []
        results = []
        for meta_path in sorted(self.snapshots_root.glob(f"*/{METADATA_FILE}")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                results.append(data)
            except Exception:
                pass
        results.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return results

    def restore(self, snapshot_id: str, auto_backup: bool = True) -> None:
        snapshot_id = self._resolve_id(snapshot_id)
        snap_dir = self._snapshot_dir(snapshot_id)
        meta_path = snap_dir / METADATA_FILE

        if not snap_dir.exists():
            _err(f"Snapshot not found: {snapshot_id}")
            sys.exit(1)
        if not meta_path.exists():
            _err(f"Snapshot {snapshot_id} has no {METADATA_FILE} — may be corrupt.")
            sys.exit(1)

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        snapshot_files: set[str] = {r["path"] for r in metadata["files"]}

        _, _, dirty = self._git_info()
        if dirty:
            _warn("Working tree has uncommitted changes. Auto-backup will capture them.")

        if auto_backup:
            backup_id = self.freeze(label="pre-restore")
            _info(f"Safety backup created: {backup_id}")

        # Restore files from snapshot.
        restored = 0
        for posix_path in snapshot_files:
            src = snap_dir / posix_path
            dest = self.root / posix_path
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                restored += 1

        # Delete orphan files (true revert).
        orphans: list[Path] = []
        current_files, _ = self._collect_files()
        for rel in current_files:
            if rel.as_posix() not in snapshot_files:
                orphans.append(rel)

        for rel in orphans:
            (self.root / rel).unlink(missing_ok=True)

        _ok(f"Restored {restored} files from {snapshot_id}")
        if orphans:
            _info(f"Deleted {len(orphans)} orphan file(s):")
            for rel in orphans:
                print(f"  - {rel.as_posix()}")

    def diff(self, snapshot_id: str) -> None:
        snapshot_id = self._resolve_id(snapshot_id)
        snap_dir = self._snapshot_dir(snapshot_id)
        meta_path = snap_dir / METADATA_FILE

        if not snap_dir.exists():
            _err(f"Snapshot not found: {snapshot_id}")
            sys.exit(1)
        if not meta_path.exists():
            _err(f"Snapshot {snapshot_id} has no {METADATA_FILE} — may be corrupt.")
            sys.exit(1)

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

        changes: list[tuple[str, str]] = []  # (status, path)
        snapshot_paths: set[str] = set()

        for rec in metadata["files"]:
            posix = rec["path"]
            snapshot_paths.add(posix)
            cur = self.root / posix
            if not cur.exists():
                changes.append(("DELETED ", posix))
            else:
                stat = cur.stat()
                if stat.st_size != rec["size"] or abs(stat.st_mtime - rec["mtime"]) > 1.0:
                    changes.append(("MODIFIED", posix))

        current_files, _ = self._collect_files()
        for rel in current_files:
            if rel.as_posix() not in snapshot_paths:
                changes.append(("ADDED   ", rel.as_posix()))

        if not changes:
            _ok(f"No changes since snapshot {snapshot_id}")
            return

        print(f"\nChanges since snapshot {snapshot_id}:\n")
        for status, path in sorted(changes, key=lambda x: x[1]):
            if _RICH:
                colour = {"DELETED ": "red", "MODIFIED": "yellow", "ADDED   ": "green"}.get(status, "white")
                _console.print(f"  [{colour}]{status.strip()}[/{colour}]  {path}")
            else:
                print(f"  {status}  {path}")
        print()

    def delete(self, snapshot_id: str, force: bool = False) -> None:
        snapshot_id = self._resolve_id(snapshot_id)
        snap_dir = self._snapshot_dir(snapshot_id)

        if not snap_dir.exists():
            _err(f"Snapshot not found: {snapshot_id}")
            sys.exit(1)

        if "pre-restore" in snapshot_id and not force:
            _err(
                f"'{snapshot_id}' is a safety backup. Use --force to delete it."
            )
            sys.exit(1)

        shutil.rmtree(snap_dir)
        _ok(f"Deleted snapshot: {snapshot_id}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_freeze(args: argparse.Namespace, mgr: SnapshotManager) -> None:
    mgr.freeze(label=args.label or None, dry_run=args.dry_run)


def cmd_list(args: argparse.Namespace, mgr: SnapshotManager) -> None:
    snapshots = mgr.list_snapshots()
    if not snapshots:
        _info("No snapshots found. Run: python scripts/dagi_freeze.py freeze")
        return

    headers = ["ID", "Label", "Created", "Git", "Files", "Size"]
    rows = []
    for s in snapshots:
        git_short = (s.get("git_hash") or "")[:7] or "—"
        created = (s.get("created_at") or "")[:19].replace("T", " ")
        label = s.get("label") or "—"
        rows.append([
            s.get("id", "?"),
            label,
            created,
            git_short,
            str(s.get("total_files", "?")),
            _format_size(s.get("total_size", 0)),
        ])

    widths = [max(len(headers[i]), max(len(r[i]) for r in rows)) for i in range(len(headers))]
    sep = "  ".join("-" * w for w in widths)
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(sep)
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))

    print(f"\n{len(snapshots)} snapshot(s) in {SNAPSHOTS_DIR}/")


def cmd_restore(args: argparse.Namespace, mgr: SnapshotManager) -> None:
    mgr.restore(args.snapshot_id, auto_backup=not args.no_backup)


def cmd_diff(args: argparse.Namespace, mgr: SnapshotManager) -> None:
    mgr.diff(args.snapshot_id)


def cmd_delete(args: argparse.Namespace, mgr: SnapshotManager) -> None:
    mgr.delete(args.snapshot_id, force=args.force)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DAGI freeze — snapshot and restore DAGI for safe patch testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root", type=Path, default=ROOT,
        help="Project root directory (default: parent of this script).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # freeze
    p_freeze = sub.add_parser("freeze", help="Save a snapshot of the current state.")
    p_freeze.add_argument("--label", "-l", help="Short human-readable tag (no spaces).")
    p_freeze.add_argument("--dry-run", action="store_true", help="Print what would be copied; don't write anything.")

    # list
    sub.add_parser("list", help="List all snapshots.")

    # restore
    p_restore = sub.add_parser("restore", help="True revert: restore snapshot and delete orphan files.")
    p_restore.add_argument("snapshot_id", help="Snapshot ID or unique prefix.")
    p_restore.add_argument("--no-backup", action="store_true", help="Skip the automatic pre-restore safety backup.")

    # diff
    p_diff = sub.add_parser("diff", help="Show what changed since a snapshot.")
    p_diff.add_argument("snapshot_id", help="Snapshot ID or unique prefix.")

    # delete
    p_delete = sub.add_parser("delete", help="Delete a snapshot.")
    p_delete.add_argument("snapshot_id", help="Snapshot ID or unique prefix.")
    p_delete.add_argument("--force", action="store_true", help="Required to delete pre-restore safety backups.")

    args = parser.parse_args()
    mgr = SnapshotManager(args.root)

    dispatch = {
        "freeze": cmd_freeze,
        "list": cmd_list,
        "restore": cmd_restore,
        "diff": cmd_diff,
        "delete": cmd_delete,
    }
    dispatch[args.command](args, mgr)


if __name__ == "__main__":
    main()
