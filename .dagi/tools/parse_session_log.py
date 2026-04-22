"""
parse_session_log — Compact extractor for DAGI session JSONL files.
Returns a structured summary for LLM qualitative analysis.
Skips raw_messages to avoid context overflow.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from agent.base_tool import BaseTool


class ParseSessionLogTool(BaseTool):
    name = "parse_session_log"
    description = (
        "Extract a compact, LLM-readable summary of a DAGI session JSONL file: "
        "model, token totals, cost, ordered tool sequence with truncated inputs "
        "and results, user/assistant messages (truncated), and session metadata. "
        "Skips raw_messages. Use before asking DAGI to analyze a session for "
        "improvement signals (errors, friction, inefficiency, missing capabilities)."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or CWD-relative path to the session JSONL file.",
            },
        },
        "required": ["path"],
    }

    _RESULT_TRUNCATE = 400
    _CONTENT_TRUNCATE = 600

    def run(self, path: str) -> str:
        p = Path(path)
        if not p.is_absolute():
            p = Path(os.getcwd()) / p
        if not p.exists():
            return f"Error: file not found: {p}"

        session: dict = {
            "filename": p.name,
            "model": None,
            "started_at": None,
            "incomplete": True,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": None,
            "tool_call_counts": {},
            "conversation": [],  # interleaved messages and tool calls (root agent only)
        }

        pending_tool_input: str = ""

        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for raw_line in fh:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    try:
                        rec = json.loads(raw_line)
                    except json.JSONDecodeError:
                        continue

                    rtype = rec.get("type")

                    if rtype == "session_start":
                        session["model"] = rec.get("model")
                        session["started_at"] = rec.get("started_at")

                    elif rtype == "session_end":
                        session["incomplete"] = False
                        session["total_input_tokens"] = rec.get("total_input_tokens", 0)
                        session["total_output_tokens"] = rec.get("total_output_tokens", 0)
                        session["total_cost"] = rec.get("total_cost")
                        session["tool_call_counts"] = rec.get("tool_call_counts", {})
                        # raw_messages intentionally skipped — can be 200KB+

                    elif rtype == "message":
                        # Skip subagent messages — depth field indicates nesting level
                        if rec.get("depth", 0) > 0:
                            continue
                        entity = rec.get("entity", "")
                        content = (rec.get("content") or "")[:self._CONTENT_TRUNCATE]
                        session["conversation"].append({
                            "role": entity,
                            "content": content,
                            "tokens_in": rec.get("input_tokens"),
                            "tokens_out": rec.get("output_tokens"),
                        })

                    elif rtype == "tool_start":
                        if rec.get("depth", 0) > 0:
                            continue
                        pending_tool_input = (rec.get("input") or "")[:self._RESULT_TRUNCATE]

                    elif rtype == "tool_end":
                        if rec.get("depth", 0) > 0:
                            continue
                        result_str = rec.get("result") or ""
                        session["conversation"].append({
                            "tool_call": rec.get("name"),
                            "input": pending_tool_input,
                            "result": result_str[:self._RESULT_TRUNCATE],
                            "error": result_str.startswith("Error:"),
                        })
                        pending_tool_input = ""

        except OSError as e:
            return f"Error reading file: {e}"

        return json.dumps(session, indent=2)
