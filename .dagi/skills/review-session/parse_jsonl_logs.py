"""
parse_jsonl_logs.py — Simplify a DAGI session JSONL log for analysis.

What is stripped (without losing analytical meaning):
  - tool_start + tool_end pairs are merged into a single tool_call record
    (halves the record count for tool-heavy sessions)
  - `description` field on tool records (verbose; tool names are self-explanatory)
  - Per-message fields not needed for analysis: `id`, `input_tokens`,
    `output_tokens`, `cost`, `model` (all aggregated in session_end)
  - System-prompt message records from sub-agents (depth > 0, entity=system):
    identical text repeated for every sub-agent adds no new information
  - `raw_messages` field in session_end (can be 200 KB+, zero analysis value)
  - Long content is truncated to configurable limits

What is always kept:
  - session_start / session_end metadata
  - All user messages (full content — primary signal)
  - All assistant messages (truncated if very long)
  - All tool calls with name, truncated input, truncated result, error flag
  - subagent_start / subagent_end boundaries
  - Error information (never truncated below MIN_ERROR_CHARS)
  - depth / subagent_id tags on sub-agent records

Modes:
  <path>              Output simplified JSONL to stdout; stats to stderr
  <path> --stats      Output only a stats JSON object to stdout (no records)
  <path> --output F   Write simplified JSONL to file F; stats to stderr

Stats JSON keys:
  original_nodes      Total lines in the original file
  simplified_nodes    Records in simplified output (tool pairs counted as 1)
  estimated_chars     Total character length of simplified JSONL output
  fits_in_context     True if estimated_chars < context_limit
  context_limit       The limit used (default 60000)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_DEFAULT_TRUNCATE_CONTENT = 2000   # user / assistant message content
_DEFAULT_TRUNCATE_RESULT = 1200    # tool result
_DEFAULT_TRUNCATE_INPUT = 800      # tool input
_DEFAULT_CONTEXT_LIMIT = 60_000   # chars; ~15k tokens — comfortable single-pass read
_MIN_ERROR_CHARS = 400             # never truncate error text below this


def _trunc(text: str | None, limit: int, label: str = "") -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    suffix = f"…[truncated {len(text) - limit} chars{' in ' + label if label else ''}]"
    return text[:limit] + suffix


def _is_error(result: str) -> bool:
    low = result.lower()
    return any(k in low for k in ("error:", "traceback", "exception", "exit code"))


def simplify(
    path: Path,
    truncate_content: int = _DEFAULT_TRUNCATE_CONTENT,
    truncate_result: int = _DEFAULT_TRUNCATE_RESULT,
    truncate_input: int = _DEFAULT_TRUNCATE_INPUT,
    context_limit: int = _DEFAULT_CONTEXT_LIMIT,
    root_only: bool = False,
) -> tuple[list[dict], dict]:
    """
    Returns (simplified_records, stats_dict).
    stats_dict contains original_nodes, simplified_nodes, estimated_chars,
    fits_in_context, context_limit.
    """
    original_nodes = 0
    simplified: list[dict] = []
    pending_tool: dict | None = None   # holds tool_start data until tool_end arrives

    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            original_nodes += 1
            try:
                rec = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            rtype = rec.get("type")
            depth = rec.get("depth", 0)

            if root_only and depth > 0:
                continue

            # ── session_start ─────────────────────────────────────────────
            if rtype == "session_start":
                simplified.append({
                    "type": "session_start",
                    "thread_id": rec.get("thread_id"),
                    "model": rec.get("model"),
                    "started_at": rec.get("started_at"),
                })

            # ── session_end ───────────────────────────────────────────────
            elif rtype == "session_end":
                r = {
                    "type": "session_end",
                    "finished_at": rec.get("finished_at"),
                    "total_input_tokens": rec.get("total_input_tokens"),
                    "total_output_tokens": rec.get("total_output_tokens"),
                    "total_cost": rec.get("total_cost"),
                    "tool_call_counts": rec.get("tool_call_counts", {}),
                    # raw_messages intentionally omitted (can be 200KB+)
                }
                simplified.append(r)

            # ── message ───────────────────────────────────────────────────
            elif rtype == "message":
                entity = rec.get("entity", "")

                # Skip sub-agent system prompts (same text repeated per sub-agent)
                if entity == "system" and depth > 0:
                    continue

                content = rec.get("content") or ""
                # User messages kept at full length (primary signal)
                if entity == "user":
                    display_content = content
                else:
                    display_content = _trunc(content, truncate_content, entity)

                r: dict = {
                    "type": "message",
                    "entity": entity,
                    "content": display_content,
                    "timestamp": rec.get("timestamp"),
                }
                if depth > 0:
                    r["depth"] = depth
                if rec.get("subagent_id"):
                    r["subagent_id"] = rec["subagent_id"]
                # tool_calls list embedded in assistant messages
                if rec.get("tool_calls"):
                    r["tool_calls"] = rec["tool_calls"]
                simplified.append(r)

            # ── tool_start — buffer until tool_end ────────────────────────
            elif rtype == "tool_start":
                pending_tool = {
                    "name": rec.get("name"),
                    "input": _trunc(rec.get("input") or "", truncate_input, "input"),
                    "timestamp": rec.get("timestamp"),
                    "depth": depth,
                    "subagent_id": rec.get("subagent_id"),
                }

            # ── tool_end — merge with buffered tool_start ─────────────────
            elif rtype == "tool_end":
                result_raw = rec.get("result") or ""
                is_err = _is_error(result_raw)
                # Never truncate error output below MIN_ERROR_CHARS
                effective_limit = max(truncate_result, _MIN_ERROR_CHARS) if is_err else truncate_result
                result_display = _trunc(result_raw, effective_limit, "result")

                r = {
                    "type": "tool_call",
                    "name": rec.get("name"),
                    "timestamp": rec.get("timestamp"),
                    "error": is_err,
                    "result": result_display,
                }
                if pending_tool and pending_tool["name"] == rec.get("name"):
                    r["input"] = pending_tool["input"]
                    r["started_at"] = pending_tool["timestamp"]
                    depth = pending_tool["depth"]
                    subagent_id = pending_tool["subagent_id"]
                else:
                    r["input"] = ""
                    subagent_id = rec.get("subagent_id")

                if depth > 0:
                    r["depth"] = depth
                if subagent_id:
                    r["subagent_id"] = subagent_id
                simplified.append(r)
                pending_tool = None

            # ── subagent_start / subagent_end ─────────────────────────────
            elif rtype in ("subagent_start", "subagent_end"):
                r = {"type": rtype, "subagent_id": rec.get("subagent_id"),
                     "depth": rec.get("depth"), "timestamp": rec.get("timestamp")}
                if rtype == "subagent_start":
                    r["tool"] = rec.get("tool")
                    r["task"] = _trunc(rec.get("task") or "", truncate_content, "task")
                else:
                    r["result"] = _trunc(rec.get("result") or "", truncate_result, "result")
                simplified.append(r)

    # Estimate output size
    lines = [json.dumps(r, ensure_ascii=False) for r in simplified]
    estimated_chars = sum(len(l) + 1 for l in lines)  # +1 for newline

    stats = {
        "original_nodes": original_nodes,
        "simplified_nodes": len(simplified),
        "estimated_chars": estimated_chars,
        "fits_in_context": estimated_chars < context_limit,
        "context_limit": context_limit,
    }
    return simplified, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Simplify a DAGI session JSONL log for analysis.")
    parser.add_argument("path", help="Path to session JSONL file")
    parser.add_argument("--stats", action="store_true",
                        help="Output only stats JSON to stdout (no records)")
    parser.add_argument("--output", metavar="FILE",
                        help="Write simplified JSONL to FILE instead of stdout")
    parser.add_argument("--root-only", action="store_true",
                        help="Exclude all sub-agent records (depth > 0)")
    parser.add_argument("--truncate-content", type=int, default=_DEFAULT_TRUNCATE_CONTENT,
                        help=f"Max chars for message content (default {_DEFAULT_TRUNCATE_CONTENT})")
    parser.add_argument("--truncate-result", type=int, default=_DEFAULT_TRUNCATE_RESULT,
                        help=f"Max chars for tool results (default {_DEFAULT_TRUNCATE_RESULT})")
    parser.add_argument("--truncate-input", type=int, default=_DEFAULT_TRUNCATE_INPUT,
                        help=f"Max chars for tool inputs (default {_DEFAULT_TRUNCATE_INPUT})")
    parser.add_argument("--context-limit", type=int, default=_DEFAULT_CONTEXT_LIMIT,
                        help=f"Char threshold for fits_in_context (default {_DEFAULT_CONTEXT_LIMIT})")
    args = parser.parse_args()

    records, stats = simplify(
        Path(args.path),
        truncate_content=args.truncate_content,
        truncate_result=args.truncate_result,
        truncate_input=args.truncate_input,
        context_limit=args.context_limit,
        root_only=args.root_only,
    )

    if args.stats:
        print(json.dumps(stats, ensure_ascii=False))
        return

    print(json.dumps(stats, ensure_ascii=False), file=sys.stderr)

    lines = (json.dumps(r, ensure_ascii=False) for r in records)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
    else:
        for line in lines:
            print(line)


if __name__ == "__main__":
    main()
