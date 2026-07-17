"""tests/test_compact_tool.py — Unit tests for CompactTool context compaction."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.loop import AgentConfig
from tools.compact import CompactTool, _estimate_tokens, _format_messages_for_summary


def _summary_response(text="Summary text.", prompt_tokens=10, completion_tokens=5, cost=None):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost=cost)
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def _config(**overrides):
    base = dict(
        model="test-model",
        api_key="test-key",
        system_prompt="You are a test agent.",
        keep_recent_tokens=100,
    )
    base.update(overrides)
    return AgentConfig(**base)


class TestUnbound:
    def test_compact_before_bind_raises_runtime_error(self):
        tool = CompactTool()
        with pytest.raises(RuntimeError, match="bind"):
            tool.compact(force=True)


class TestNoSafeCutPoints:
    def test_all_messages_mid_tool_call_returns_no_compaction(self):
        """A conversation with no safe cut points (every assistant msg has a
        pending tool call) must not be mutated."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do X"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "tc1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}
            ]},
        ]
        client = MagicMock()
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        result = tool.compact(force=True)

        assert result.did_compact is False
        assert client.chat.completions.create.call_count == 0

    def test_empty_middle_after_system_returns_no_compaction(self):
        messages = [{"role": "system", "content": "sys"}]
        client = MagicMock()
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        result = tool.compact(force=True)

        assert result.did_compact is False


class TestThresholdGating:
    def test_without_force_below_threshold_does_not_compact(self):
        """Recent-tail budget large enough to cover everything -> nothing compacted."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        client = MagicMock()
        tool = CompactTool()
        tool.bind(messages, _config(keep_recent_tokens=100_000), client)

        result = tool.compact(force=False)

        assert result.did_compact is False
        assert client.chat.completions.create.call_count == 0

    def test_force_true_compacts_even_below_threshold_if_safe_cut_exists(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
            {"role": "user", "content": "next task"},
            {"role": "assistant", "content": "working on it"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response()
        tool = CompactTool()
        tool.bind(messages, _config(keep_recent_tokens=100_000), client)

        result = tool.compact(force=True)

        assert result.did_compact is True


class TestSuccessfulCompaction:
    def test_replaces_middle_with_single_summary_message(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "done A"},
            {"role": "user", "content": "task B"},
            {"role": "assistant", "content": "done B"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response("Cumulative summary.")
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        result = tool.compact(force=True)

        assert result.did_compact is True
        assert messages[0] == {"role": "system", "content": "sys"}
        assert "[CONTEXT SUMMARY" in messages[1]["content"]
        assert "Cumulative summary." in messages[1]["content"]

    def test_result_reports_token_usage_from_summary_call(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "done A"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response(
            prompt_tokens=42, completion_tokens=7, cost=0.003
        )
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        result = tool.compact(force=True)

        assert result.summary_input_tokens == 42
        assert result.summary_output_tokens == 7
        assert result.summary_cost == 0.003

    def test_on_summary_and_on_compaction_callbacks_fire(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "done A"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response("The summary body.")

        on_summary_calls = []
        on_compaction_calls = []
        tool = CompactTool()
        tool.bind(
            messages, _config(), client,
            on_compaction=lambda total, removed: on_compaction_calls.append((total, removed)),
            on_summary=lambda text: on_summary_calls.append(text),
        )

        tool.compact(force=True)

        assert len(on_summary_calls) == 1
        assert "The summary body." in on_summary_calls[0]
        assert len(on_compaction_calls) == 1

    def test_progressive_resummarization_carries_prior_summary_forward(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "[CONTEXT SUMMARY — prior conversation compacted]\n\nOld summary."},
            {"role": "user", "content": "task C"},
            {"role": "assistant", "content": "done C"},
            {"role": "user", "content": "task D"},
            {"role": "assistant", "content": "done D"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response("New cumulative summary.")
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        tool.compact(force=True)

        # The summarisation prompt sent to the model must include the prior summary.
        sent_messages = client.chat.completions.create.call_args.kwargs["messages"]
        user_prompt = sent_messages[1]["content"]
        assert "Old summary." in user_prompt


class TestFailureRollback:
    def test_exception_during_summarisation_restores_original_messages(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "done A"},
        ]
        original = [dict(m) for m in messages]
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("network down")
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        with pytest.raises(RuntimeError, match="network down"):
            tool.compact(force=True)

        assert messages == original


class TestRunWrapper:
    def test_run_reports_compaction_summary_string(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi!"},
            {"role": "user", "content": "task A"},
            {"role": "assistant", "content": "done A"},
        ]
        client = MagicMock()
        client.chat.completions.create.return_value = _summary_response()
        tool = CompactTool()
        tool.bind(messages, _config(), client)

        output = tool.run(force=True)

        assert "Context compacted" in output

    def test_run_reports_nothing_to_compact(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
        client = MagicMock()
        tool = CompactTool()
        tool.bind(messages, _config(keep_recent_tokens=100_000), client)

        output = tool.run(force=False)

        assert output == "Nothing to compact."


class TestHelperFunctions:
    def test_estimate_tokens_counts_content_and_tool_call_args(self):
        msg = {
            "content": "a" * 40,
            "tool_calls": [{"function": {"arguments": "b" * 20}}],
        }
        # (40 + 20) chars / 4 = 15
        assert _estimate_tokens(msg) == 15

    def test_estimate_tokens_has_floor_of_four(self):
        assert _estimate_tokens({"content": ""}) == 4

    def test_format_messages_for_summary_renders_roles(self):
        messages = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello", "tool_calls": [
                {"function": {"name": "bash", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "tc1", "content": "output"},
        ]
        rendered = _format_messages_for_summary(messages)
        assert "[USER]: hi" in rendered
        assert "[ASSISTANT]: hello" in rendered
        assert "[TOOL CALL bash]" in rendered
        assert "[TOOL RESULT tool_call_id=tc1]: output" in rendered
