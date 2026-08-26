"""agent/_model_switch.py — LLM tier switching.

Extracted verbatim from AgentLoop._handle_switch_model in agent/loop.py
(`self` became the explicit `loop` parameter). `build_extra_body` is the
single source of truth for the OpenRouter extension body — it replaces the
previously duplicated construction in AgentLoop.__init__ and in
handle_switch_model.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import openai

if TYPE_CHECKING:
    from agent.loop import AgentLoop


def build_extra_body(
    thinking: str,
    cache_prompt: bool,
    provider_order: list[str] | None,
) -> dict:
    """Build the OpenRouter extra_body dict (reasoning, caching, provider routing).

    Single source of truth — used by AgentLoop.__init__ and handle_switch_model.
    """
    body: dict = {}
    if thinking and thinking.lower() != "none":
        body["reasoning"] = {"effort": thinking.lower()}
    if cache_prompt:
        body["cache_prompt"] = True
    if provider_order:
        body["provider"] = {"order": provider_order}
    return body


def handle_switch_model(loop: AgentLoop, target: str, args: dict) -> str:
    """Switch the active LLM tier in-place without changing the tool registry."""
    reason = args.get("reason", "")

    if target == loop._current_tier:
        return (
            f"Already on the '{target}' tier "
            f"({loop.config.display_name or loop.config.model}) — no switch needed."
        )

    from_name = loop.config.display_name or loop.config.model

    if target == "plan":
        tier_cfg = loop.config.advanced_config
        if tier_cfg is None:
            return (
                "Cannot switch to 'advanced' tier: no advanced_model is configured in .dagi/config.yaml. "
                "Continuing with the current model."
            )
    elif target == "worker":
        tier_cfg = loop.config.worker_config
        if tier_cfg is None:
            return (
                "Cannot switch to 'worker' tier: no worker_model is configured in .dagi/config.yaml. "
                "Continuing with the current model."
            )
    elif target == "default":
        snap = loop._base_config_snapshot
        loop.config.model          = snap["model"]
        loop.config.base_url       = snap["base_url"]
        loop.config.api_key        = snap["api_key"]
        loop.config.thinking       = snap["thinking"]
        loop.config.display_name   = snap["display_name"]
        loop.config.provider_order = snap["provider_order"]
        tier_cfg = None
    else:
        return f"Unknown model tier '{target}'. Valid values: plan, default, worker."

    if tier_cfg is not None:
        loop.config.model          = tier_cfg.model
        loop.config.base_url       = tier_cfg.base_url
        loop.config.api_key        = tier_cfg.api_key
        loop.config.thinking       = tier_cfg.thinking
        loop.config.display_name   = tier_cfg.display_name
        loop.config.provider_order = tier_cfg.provider_order

    loop.client = openai.OpenAI(api_key=loop.config.api_key, base_url=loop.config.base_url)

    loop._extra_body = build_extra_body(
        loop.config.thinking, loop.config.cache_prompt, loop.config.provider_order,
    )

    loop._current_tier = target
    to_name = loop.config.display_name or loop.config.model
    loop.callbacks.on_model_switch(from_name, to_name)

    return f"Switched to '{target}' tier: {to_name}. Reason: {reason}"
