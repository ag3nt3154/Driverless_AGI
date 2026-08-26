"""Verify model-switch handling and the extra_body builder are importable.

Why this matters: build_extra_body is now the single source of truth for
OpenRouter extensions (reasoning effort, prompt caching, provider routing) —
previously constructed identically in two places and at risk of drifting.
"""
from agent._model_switch import build_extra_body


def test_build_extra_body_empty():
    result = build_extra_body(thinking="none", cache_prompt=False, provider_order=None)
    assert result == {}


def test_build_extra_body_with_reasoning():
    result = build_extra_body(thinking="medium", cache_prompt=False, provider_order=None)
    assert result == {"reasoning": {"effort": "medium"}}


def test_build_extra_body_reasoning_case_normalised():
    assert build_extra_body("HIGH", False, None) == {"reasoning": {"effort": "high"}}


def test_build_extra_body_full():
    result = build_extra_body(
        thinking="high",
        cache_prompt=True,
        provider_order=["Anthropic", "Together"],
    )
    assert result == {
        "reasoning": {"effort": "high"},
        "cache_prompt": True,
        "provider": {"order": ["Anthropic", "Together"]},
    }


def test_reexport_from_agent_loop():
    # handle_switch_model stays reachable via the AgentLoop method wrapper.
    from agent.loop import AgentLoop

    assert callable(AgentLoop._handle_switch_model)
