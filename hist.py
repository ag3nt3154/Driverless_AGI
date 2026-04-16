#!/usr/bin/env python3
"""
hist.py — Show the 20 most recent dagi agent sessions.

Usage:
    python hist.py [--n N] [--project DIR]

Reads from .dagi/logs/ in the project directory; falls back to logs/ if
.dagi/logs/ is absent or empty (backward compat with pre-migration sessions).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _find_logs_dir(project: Path) -> tuple[Path, bool]:
    """Return (logs_dir, is_fallback). Prefer .dagi/logs/, fall back to logs/."""
    primary = project / ".dagi" / "logs"
    if primary.exists() and any(primary.glob("session_*.jsonl")):
        return primary, False
    fallback = project / "logs"
    return fallback, True


def _parse_session(path: Path) -> dict | None:
    """Extract metadata from a session JSONL file. Returns None on parse error."""
    started_at: str | None = None
    model: str | None = None
    first_user_msg: str | None = None

    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                t = record.get("type")
                if t == "session_start":
                    started_at = record.get("started_at")
                    model = record.get("model")
                elif t == "message" and record.get("entity") == "user" and first_user_msg is None:
                    content = record.get("content") or ""
                    first_user_msg = content.replace("\n", " ").strip()

                if started_at and model and first_user_msg is not None:
                    break  # got everything we need
    except OSError:
        return None

    if not started_at:
        return None

    try:
        dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(timezone.utc)
        dt_str = dt_utc.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt_str = started_at[:19]

    return {
        "path": path,
        "started_at": started_at,
        "dt_str": dt_str,
        "model": model or "unknown",
        "first_msg": first_user_msg or "(no user message)",
    }


def _truncate(s: str, width: int) -> str:
    return s if len(s) <= width else s[: width - 3] + "..."


def run(project: Path | str = ".", n: int = 20) -> None:
    """Print session history table. Called directly by main.py for /hist."""
    project = Path(project).resolve()
    logs_dir, is_fallback = _find_logs_dir(project)

    if not logs_dir.exists():
        print(f"No session logs found. Expected: {project / '.dagi' / 'logs'}")
        return

    files = sorted(logs_dir.glob("session_*.jsonl"), reverse=True)
    total = len(files)

    if total == 0:
        print(f"No sessions in {logs_dir}")
        return

    sessions = []
    for f in files:
        s = _parse_session(f)
        if s:
            sessions.append(s)
        if len(sessions) >= n:
            break

    label = f"{logs_dir}  [fallback]" if is_fallback else str(logs_dir)
    shown = len(sessions)
    print(f"\nPast sessions | {label}  ({shown} of {total})\n")

    model_w = max(len(s["model"]) for s in sessions) if sessions else 7
    model_w = max(model_w, 5)
    msg_w = 50

    header_idx   = " # "
    header_dt    = "Started (UTC)       "
    header_model = "Model".ljust(model_w)
    header_msg   = "First message"

    sep_idx   = "-" * 3
    sep_dt    = "-" * 20
    sep_model = "-" * model_w
    sep_msg   = "-" * msg_w

    print(f"  {header_idx}  {header_dt}  {header_model}  {header_msg}")
    print(f"  {sep_idx}  {sep_dt}  {sep_model}  {sep_msg}")

    for i, s in enumerate(sessions, 1):
        idx   = str(i).rjust(3)
        dt    = s["dt_str"].ljust(20)
        model = _truncate(s["model"], model_w).ljust(model_w)
        msg   = _truncate(s["first_msg"], msg_w)
        print(f"  {idx}  {dt}  {model}  {msg}")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Show recent dagi agent sessions")
    parser.add_argument("--n", type=int, default=20, help="Number of sessions to show (default: 20)")
    parser.add_argument("--project", default=".", help="Project directory (default: cwd)")
    args = parser.parse_args()
    run(project=args.project, n=args.n)


if __name__ == "__main__":
    main()
