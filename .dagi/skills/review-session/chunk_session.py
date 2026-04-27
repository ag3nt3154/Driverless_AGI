"""
chunk_session.py — session log utility for the review-session skill.

Modes:
  <path>                      Chunk a session JSONL into overlapping windows
  <path> --info               Print metadata + node count (fast, reads only start/end records)
  --list [logs_dir]           List all sessions in logs_dir with metadata, newest first
  --latest [logs_dir]         Print absolute path of the most recent session file
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_DEFAULT_LOGS_DIR = ".dagi/logs"
_DEFAULT_CHUNK_SIZE = 60
_DEFAULT_OVERLAP = 10


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_records(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def _session_info(path: Path) -> dict:
    """Read only session_start and session_end records; count all nodes."""
    info: dict = {
        "path": str(path.resolve()),
        "node_count": 0,
        "thread_id": None,
        "model": None,
        "started_at": None,
        "finished_at": None,
        "total_input_tokens": None,
        "total_output_tokens": None,
        "total_cost": None,
        "tool_call_counts": {},
        "incomplete": True,
    }
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            info["node_count"] += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rtype = rec.get("type")
            if rtype == "session_start":
                info["thread_id"] = rec.get("thread_id")
                info["model"] = rec.get("model")
                info["started_at"] = rec.get("started_at")
            elif rtype == "session_end":
                info["finished_at"] = rec.get("finished_at")
                info["total_input_tokens"] = rec.get("total_input_tokens")
                info["total_output_tokens"] = rec.get("total_output_tokens")
                info["total_cost"] = rec.get("total_cost")
                info["tool_call_counts"] = rec.get("tool_call_counts", {})
                info["incomplete"] = False
    return info


def _find_session_files(logs_dir: Path) -> list[Path]:
    """Return session JSONL files sorted newest-first (by filename timestamp)."""
    files = sorted(logs_dir.glob("session_*.jsonl"), reverse=True)
    return files


# ── modes ─────────────────────────────────────────────────────────────────────

def mode_info(path: Path) -> None:
    info = _session_info(path)
    print(json.dumps(info, ensure_ascii=False))


def mode_list(logs_dir: Path) -> None:
    files = _find_session_files(logs_dir)
    if not files:
        print(json.dumps([]))
        return
    result = [_session_info(f) for f in files]
    print(json.dumps(result, ensure_ascii=False))


def mode_latest(logs_dir: Path) -> None:
    files = _find_session_files(logs_dir)
    if not files:
        print("", end="")
        sys.exit(1)
    print(str(files[0].resolve()))


def mode_chunk(path: Path, chunk_size: int, overlap: int) -> None:
    if overlap >= chunk_size:
        print(
            f"Error: overlap ({overlap}) must be less than chunk_size ({chunk_size})",
            file=sys.stderr,
        )
        sys.exit(1)

    records = _read_records(path)
    total = len(records)

    if total == 0:
        print(json.dumps([]))
        return

    if total <= chunk_size:
        chunks = [
            {
                "chunk_index": 0,
                "total_chunks": 1,
                "node_range": [0, total - 1],
                "is_overlap_start": False,
                "records": records,
            }
        ]
        print(json.dumps(chunks, ensure_ascii=False))
        return

    step = chunk_size - overlap
    starts = list(range(0, total, step))
    # Ensure the last chunk reaches the end
    if starts[-1] + chunk_size < total:
        starts.append(total - chunk_size)

    # Deduplicate and sort starts
    starts = sorted(set(starts))

    chunks = []
    for i, start in enumerate(starts):
        end = min(start + chunk_size, total)
        chunks.append(
            {
                "chunk_index": i,
                "total_chunks": len(starts),
                "node_range": [start, end - 1],
                "is_overlap_start": i > 0,
                "overlap_node_count": overlap if i > 0 else 0,
                "records": records[start:end],
            }
        )

    print(json.dumps(chunks, ensure_ascii=False))


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Session log utility for the review-session skill."
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to session JSONL file (required for default chunking and --info)",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Print metadata + node count for the given session file",
    )
    parser.add_argument(
        "--list",
        metavar="LOGS_DIR",
        nargs="?",
        const=_DEFAULT_LOGS_DIR,
        help=f"List all sessions in LOGS_DIR (default: {_DEFAULT_LOGS_DIR})",
    )
    parser.add_argument(
        "--latest",
        metavar="LOGS_DIR",
        nargs="?",
        const=_DEFAULT_LOGS_DIR,
        help=f"Print path of newest session in LOGS_DIR (default: {_DEFAULT_LOGS_DIR})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=_DEFAULT_CHUNK_SIZE,
        help=f"Records per chunk (default: {_DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=_DEFAULT_OVERLAP,
        help=f"Overlap records between chunks (default: {_DEFAULT_OVERLAP})",
    )

    args = parser.parse_args()

    if args.list is not None:
        mode_list(Path(args.list))
    elif args.latest is not None:
        mode_latest(Path(args.latest))
    elif args.info:
        if not args.path:
            parser.error("--info requires a path argument")
        mode_info(Path(args.path))
    else:
        if not args.path:
            parser.error("a path argument is required for chunking")
        mode_chunk(Path(args.path), args.chunk_size, args.overlap)


if __name__ == "__main__":
    main()
