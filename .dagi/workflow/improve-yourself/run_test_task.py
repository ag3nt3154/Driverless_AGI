#!/usr/bin/env python3
"""
Run a DAGI task in single-shot mode from a snapshot directory and return the log path.

Usage:
    conda run -n dagi python run_test_task.py "task string" --snapshot-dir /path/to/snapshot

Stdout (last line): LOG:/absolute/path/to/session_*.jsonl
Exit code 1 if the task fails to produce a log file.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _dagi_python() -> Path:
    """Resolve the Python executable for the 'dagi' conda environment.

    Bypasses `conda run` to avoid conda's cp1252 stdout-capture crashing on
    Unicode output from DAGI (conda 23.x Windows bug).
    """
    conda_root = Path(os.environ.get("CONDA_ROOT", r"C:\Users\alexr\miniconda3"))
    candidates = [
        conda_root / "envs" / "dagi" / "python.exe",   # Windows conda env
        conda_root / "envs" / "dagi" / "bin" / "python",  # Linux/macOS
    ]
    for p in candidates:
        if p.exists():
            return p
    # Fallback: assume we're already running inside the dagi env
    return Path(sys.executable)


def run(task: str, snapshot_dir: Path) -> Path:
    logs_dir = snapshot_dir / ".dagi" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    before: set[Path] = set(logs_dir.glob("session_*.jsonl"))

    python = _dagi_python()
    result = subprocess.run(
        [str(python), "main.py", task],
        cwd=str(snapshot_dir),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )

    after: set[Path] = set(logs_dir.glob("session_*.jsonl"))
    new_logs = sorted(after - before, key=lambda p: p.stat().st_mtime)

    if not new_logs:
        print(
            f"ERROR: No new session log found in {logs_dir} after task run "
            f"(exit code {result.returncode}).",
            file=sys.stderr,
        )
        sys.exit(1)

    return new_logs[-1]  # newest by mtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a DAGI task from a snapshot and return the log path.")
    parser.add_argument("task", help="Task string to pass to main.py")
    parser.add_argument(
        "--snapshot-dir",
        required=True,
        type=Path,
        help="Path to the runnable snapshot directory (created by dagi_freeze.py freeze).",
    )
    args = parser.parse_args()

    snapshot_dir = args.snapshot_dir.resolve()
    if not snapshot_dir.exists():
        print(f"ERROR: snapshot directory not found: {snapshot_dir}", file=sys.stderr)
        sys.exit(1)
    if not (snapshot_dir / "main.py").exists():
        print(f"ERROR: {snapshot_dir} does not contain main.py — is this a valid snapshot?", file=sys.stderr)
        sys.exit(1)

    log_path = run(args.task, snapshot_dir)
    print(f"LOG:{log_path}")


if __name__ == "__main__":
    main()
