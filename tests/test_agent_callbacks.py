"""tests/test_agent_callbacks.py — AgentCallbacks default no-op behavior."""
from __future__ import annotations

from agent.loop import AgentCallbacks


class TestOnPlanShownDefault:
    def test_on_plan_shown_defaults_to_noop(self):
        callbacks = AgentCallbacks()
        # Must not raise, must return None, with zero arguments.
        assert callbacks.on_plan_shown() is None
