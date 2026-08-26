"""Verify tool dispatch bookkeeping works from the extracted module.

Why this matters: the dispatch path owns the tool-call protocol — sentinel
short-circuits, output filtering, JSONL records. The extraction must keep
identical call-through behaviour, including instance-level delegation so
patch.object(loop, ...) tests keep working.
"""
from types import SimpleNamespace

from agent._tool_dispatch import dispatch_tool_calls


def test_module_functions_importable():
    import agent._tool_dispatch as td

    for fn in (
        "dispatch_tool_calls",
        "bookkeep_tool_call",
        "finalize_turn",
        "handle_end_turn",
    ):
        assert callable(getattr(td, fn)), fn


def test_finalize_turn_records_and_reports():
    from agent._tool_dispatch import finalize_turn

    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        cost=0.01,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=2),
        prompt_tokens_details=SimpleNamespace(cached_tokens=3),
    )
    message = SimpleNamespace(content="hi")
    response = SimpleNamespace(usage=usage)
    records = ["rec1"]
    recorded = {}

    loop = SimpleNamespace(
        tracker=SimpleNamespace(
            record_assistant=lambda content, u, r, cached_tokens, thinking_tokens: (
                recorded.update(
                    content=content,
                    cached=cached_tokens,
                    thinking=thinking_tokens,
                    records=r,
                )
            )
        ),
        callbacks=SimpleNamespace(
            on_token_update=lambda i, o, c, t, ca: recorded.update(tok=(i, o, c, t, ca)),
        ),
    )
    finalize_turn(loop, message, response, records)
    assert recorded["content"] == "hi"
    assert recorded["cached"] == 3
    assert recorded["thinking"] == 2
    assert recorded["records"] == records
    assert recorded["tok"] == (10, 5, 0.01, 2, 3)


def test_dispatch_returns_none_without_tool_calls():
    loop = SimpleNamespace(registry=SimpleNamespace(_tools={}))
    message = SimpleNamespace(tool_calls=[], content=None)
    assert dispatch_tool_calls(loop, message, None, []) is None
