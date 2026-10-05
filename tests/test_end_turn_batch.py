"""tests/test_end_turn_batch.py — several END_TURN calls in one tool batch.

The first END_TURN call wins; every later call in the batch is skipped but
still gets an explicit tool result, so the assistant tool-call batch stays
fully paired for strict providers and for persisted-history replay.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from agent import session_events as ev
from agent.protocol import SideEffect, ToolResult
from tests.test_session_log_shadow import _make_loop, _wh_response


def _batch_response(*calls: tuple[str, str, dict]) -> SimpleNamespace:
    """A completion whose single message carries several tool calls."""
    tcs = [
        SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        for cid, name, args in calls
    ]
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=tcs, content=None))],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, cost=None,
            completion_tokens_details=None, prompt_tokens_details=None,
        ),
    )


def _loop(tmp_path, dispatched: list[str], **overrides):
    loop = _make_loop(tmp_path, **overrides)
    loop.client = MagicMock()

    def _dispatch(name, args):
        dispatched.append(name)
        if name in ("write_handoff", "finish"):
            return ToolResult(output=args.get("content", ""), side_effect=SideEffect.END_TURN)
        return "ok"

    loop.registry.dispatch = _dispatch
    done: list[str] = []
    loop.callbacks.on_done = done.append
    return loop, done


def _assert_paired(messages: list[dict]) -> None:
    """Every assistant tool call is answered by exactly one tool message
    before the next non-tool message."""
    for i, msg in enumerate(messages):
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        ids = [tc["id"] for tc in msg["tool_calls"]]
        answered = []
        for follow in messages[i + 1:]:
            if follow.get("role") != "tool":
                break
            answered.append(follow["tool_call_id"])
        assert answered == ids


def _results_by_call(loop) -> dict[str, list]:
    out: dict[str, list] = {}
    for e in loop.log.events:
        if e.type == ev.TOOL_RESULT:
            out.setdefault(e.data["call_id"], []).append(e.data["content"])
    return out


class TestDuplicateHandoffs:
    def test_first_handoff_wins_and_both_calls_get_results(self, tmp_path):
        dispatched: list[str] = []
        loop, done = _loop(tmp_path, dispatched)
        loop.client.chat.completions.create.return_value = _batch_response(
            ("end1", "write_handoff", {"content": "first"}),
            ("end2", "write_handoff", {"content": "second"}),
        )

        result = loop.run("go")

        assert result == "first"
        assert done == ["first"]
        assert dispatched == ["write_handoff"]  # the redundant handoff never ran
        results = _results_by_call(loop)
        assert set(results) == {"end1", "end2"}
        assert all(len(v) == 1 for v in results.values())
        assert results["end1"] == ["first"]
        assert results["end2"][0].startswith("[skipped]")
        _assert_paired(loop._messages)

    def test_mixed_end_turn_tools(self, tmp_path):
        dispatched: list[str] = []
        loop, done = _loop(tmp_path, dispatched)
        loop.registry._tools["finish"] = SimpleNamespace(description="finish")
        loop.client.chat.completions.create.return_value = _batch_response(
            ("f1", "finish", {"content": "from finish"}),
            ("h1", "write_handoff", {"content": "from handoff"}),
        )

        assert loop.run("go") == "from finish"
        assert done == ["from finish"]
        assert set(_results_by_call(loop)) == {"f1", "h1"}
        _assert_paired(loop._messages)

    def test_ordinary_tool_after_handoff_is_skipped_but_answered(self, tmp_path):
        dispatched: list[str] = []
        loop, done = _loop(tmp_path, dispatched)
        loop.client.chat.completions.create.return_value = _batch_response(
            ("r0", "read", {"file_path": "a"}),
            ("end", "write_handoff", {"content": "report"}),
            ("r1", "read", {"file_path": "b"}),
        )

        assert loop.run("go") == "report"
        assert dispatched == ["read", "write_handoff"]
        results = _results_by_call(loop)
        assert results["r0"] == ["ok"]
        assert results["r1"][0].startswith("[skipped]")
        assert done == ["report"]
        _assert_paired(loop._messages)

    def test_history_stays_paired_after_another_turn_and_replay(self, tmp_path):
        dispatched: list[str] = []
        loop, done = _loop(tmp_path, dispatched)
        loop.client.chat.completions.create.side_effect = [
            _batch_response(
                ("end1", "write_handoff", {"content": "first"}),
                ("end2", "write_handoff", {"content": "second"}),
            ),
            _wh_response("again"),
        ]

        loop.run("one")
        loop.run("two")
        assert done == ["first", "again"]
        _assert_paired(loop._messages)
        # The second request carried the full, paired first-turn batch.
        sent = loop.client.chat.completions.create.call_args_list[1].kwargs["messages"]
        _assert_paired(sent)

        replayed = _make_loop(tmp_path, _initial=list(loop._messages))
        assert replayed._messages[1:] == loop._messages[1:]
        _assert_paired(replayed._messages)
