"""tests/test_agent_callbacks.py — AgentCallbacks default no-op behavior."""
from __future__ import annotations

from agent.loop import AgentCallbacks


class TestOnPlanShownDefault:
    def test_on_plan_shown_defaults_to_noop(self):
        callbacks = AgentCallbacks()
        # Must not raise, must return None, with zero arguments.
        assert callbacks.on_plan_shown() is None


class TestStreamingCallbackDefaults:
    def test_streaming_callbacks_default_to_noops(self):
        """The four streaming callbacks must exist with callable no-op defaults,
        so main.py / telegram_bot.py / scheduler need zero changes."""
        cb = AgentCallbacks()
        # None of these may raise:
        cb.on_stream_start()
        cb.on_stream_end()
        cb.on_assistant_text_delta("chunk")
        cb.on_reasoning_delta("chunk")
