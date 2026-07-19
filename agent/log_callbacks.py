"""log_callbacks.py — plain-text AgentCallbacks for non-TUI entry points.

Logs dagi's tool calls and assistant messages to stdout via the standard
`logging` module. Used by main.py (interactive CLI) and the benchmark
harness (unattended agent runs), which otherwise have no visibility into
what the agent is doing mid-run.
"""
from __future__ import annotations

import logging
import sys

from agent.loop import AgentCallbacks

logger = logging.getLogger("dagi")


def _truncate(text: str, n: int = 120) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def build_cli_callbacks(verbose: bool = False, prefix: str = "") -> AgentCallbacks:
    """Build AgentCallbacks that log to stdout.

    `prefix` is prepended to every log line (e.g. a task name), so callers
    running several agents concurrently/sequentially can tell them apart.

    Streaming deltas (config.stream=True, the default — see config_loader.py)
    are printed live to stdout as they arrive, raw and unbuffered, so a run
    isn't silent for the entire length of an assistant turn. on_assistant_text
    / on_reasoning still log the same content as a complete, timestamped line
    afterward (mirrors tui/callbacks.py: a live preview plus a finalized
    record) — that is intentional duplication, not a bug.
    """
    tag = f"[{prefix}] " if prefix else ""
    _stream_kind = {"current": None}

    def _write_delta(kind: str, label: str, piece: str) -> None:
        if _stream_kind["current"] != kind:
            if _stream_kind["current"] is not None:
                sys.stdout.write("\n")
            sys.stdout.write(f"{tag}[{label}] ")
            _stream_kind["current"] = kind
        sys.stdout.write(piece)
        sys.stdout.flush()

    def on_stream_start():
        _stream_kind["current"] = None

    def on_assistant_text_delta(piece):
        _write_delta("text", "assistant", piece)

    def on_reasoning_delta(piece):
        if verbose:
            _write_delta("reasoning", "thinking", piece)

    def on_stream_end():
        if _stream_kind["current"] is not None:
            sys.stdout.write("\n")
            sys.stdout.flush()
        _stream_kind["current"] = None

    def on_tool_start(name, _desc, args):
        logger.info("%s-> %s %s", tag, name, args if verbose else _truncate(args))

    def on_tool_end(name, result):
        if verbose:
            logger.info("%s<- %s: %s", tag, name, result)
        else:
            logger.info("%s<- %s (%d chars)", tag, name, len(result))

    def on_assistant_text(text):
        if text.strip():
            logger.info("%s[assistant] %s", tag, text)

    def on_reasoning(text):
        if verbose and text.strip():
            logger.info("%s[thinking] %s", tag, text)

    def on_error(exc):
        logger.error("%s%s", tag, exc)

    def on_compaction(kept, removed):
        logger.info("%scontext compacted — removed %d messages, kept %d", tag, removed, kept)

    def on_model_switch(from_name, to_name):
        logger.info("%smodel switch: %s -> %s", tag, from_name, to_name)

    def on_continue_injected(cur, mx):
        logger.info("%sno exit flag — continue prompt injected (%d/%d)", tag, cur, mx)

    return AgentCallbacks(
        on_tool_start=on_tool_start, on_tool_end=on_tool_end,
        on_assistant_text=on_assistant_text, on_reasoning=on_reasoning,
        on_error=on_error, on_compaction=on_compaction,
        on_model_switch=on_model_switch, on_continue_injected=on_continue_injected,
        on_stream_start=on_stream_start, on_stream_end=on_stream_end,
        on_assistant_text_delta=on_assistant_text_delta,
        on_reasoning_delta=on_reasoning_delta,
    )
