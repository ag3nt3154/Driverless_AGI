"""tests/tui/test_context_breakdown.py — the context bar must count what the API bills.

Why this matters: compaction fires on the provider's real prompt_tokens, but the sidebar
estimate skipped echoed reasoning_content, the tool JSON schemas and most of the system
message (tool/skill list, prompt sections). With a reasoning model the bar read ~60% when
compaction triggered.
"""
import json

from tui.utils import _breakdown, _system_other


def test_reasoning_content_is_counted():
    msgs = [{"role": "assistant", "content": "ok", "reasoning_content": "r" * 4000}]

    assert _breakdown(msgs)["reasoning"] == 1000


def test_tool_schemas_are_counted():
    schemas = [{"type": "function", "function": {"name": "x", "description": "d" * 800}}]

    assert _breakdown([], schemas)["schemas"] == len(json.dumps(schemas)) // 4


def test_system_message_is_counted():
    msgs = [{"role": "system", "content": "s" * 8000}]

    assert _breakdown(msgs)["system"] == 2000


def test_system_other_is_remainder_beyond_file_rows():
    sys_parts = {"sys-prompt": 500, "dagi/ag": 300, "proj/ag": 0}

    assert _system_other(sys_parts, {"system": 2000}) == 1200
    # Before the first request there is no real system message: fall back to the files.
    assert _system_other(sys_parts, {}) == 0
