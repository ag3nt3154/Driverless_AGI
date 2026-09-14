"""agent/_model_switch.py — LLM tier switching & client construction.

Extracted verbatim from AgentLoop._handle_switch_model in agent/loop.py
(`self` became the explicit `loop` parameter). `build_extra_body` is the
single source of truth for the OpenRouter extension body — it replaces the
previously duplicated construction in AgentLoop.__init__ and in
handle_switch_model.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import openai

if TYPE_CHECKING:
    from agent._loop_config import AgentConfig
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


def load_client_script(script_path: str) -> tuple[openai.OpenAI, dict]:
    """Execute a Python client script and extract `client` and `request_kwargs`.

    The script must define a module-level `client` (openai.OpenAI instance).
    It may optionally define `request_kwargs` (dict) with extra kwargs to
    spread into chat.completions.create() calls.

    Returns (client, request_kwargs).
    """
    from agent import DAGI_ROOT
    path = Path(script_path)
    if not path.is_absolute():
        path = DAGI_ROOT / path
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Client script not found: {path}")

    spec = importlib.util.spec_from_file_location(f"_dagi_client_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        del sys.modules[mod.__name__]
        raise RuntimeError(f"Failed to execute client script {path}: {exc}") from exc

    client = getattr(mod, "client", None)
    if client is None:
        del sys.modules[mod.__name__]
        raise AttributeError(f"Client script {path} must define a `client` variable")
    if not isinstance(client, openai.OpenAI):
        del sys.modules[mod.__name__]
        raise TypeError(
            f"Client script {path}: `client` must be an openai.OpenAI instance, "
            f"got {type(client).__name__}"
        )

    request_kwargs = getattr(mod, "request_kwargs", {})
    if not isinstance(request_kwargs, dict):
        del sys.modules[mod.__name__]
        raise TypeError(
            f"Client script {path}: `request_kwargs` must be a dict, "
            f"got {type(request_kwargs).__name__}"
        )

    return client, request_kwargs


def build_openai_client(config: AgentConfig) -> tuple[openai.OpenAI, dict]:
    """Build an OpenAI client + request_kwargs from config.

    If config.client_script is set, loads and executes the script.
    Otherwise falls back to openai.OpenAI(api_key, base_url).

    Returns (client, request_kwargs).
    """
    if config.client_script:
        return load_client_script(config.client_script)
    return openai.OpenAI(api_key=config.api_key, base_url=config.base_url), {}


def _history_has_images(loop: AgentLoop) -> bool:
    """True if any surface user message carries a ``dagi_image`` content part."""
    for msg in loop.log.derive_messages():
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "dagi_image":
                return True
    return False


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
        target_supports_images = tier_cfg.supports_images
    elif target == "worker":
        tier_cfg = loop.config.worker_config
        if tier_cfg is None:
            return (
                "Cannot switch to 'worker' tier: no worker_model is configured in .dagi/config.yaml. "
                "Continuing with the current model."
            )
        target_supports_images = tier_cfg.supports_images
    elif target == "default":
        tier_cfg = None
        # config.supports_images is never mutated by a switch (only the six
        # identity fields snapshotted below are), so it still holds the
        # original "default" tier value here.
        target_supports_images = loop.config.supports_images
    else:
        return f"Unknown model tier '{target}'. Valid values: plan, default, worker."

    if _history_has_images(loop) and target_supports_images is False:
        return (
            f"Cannot switch to '{target}' tier: model does not support images "
            "and history contains images."
        )

    if target == "default":
        snap = loop._base_config_snapshot
        loop.config.model          = snap["model"]
        loop.config.base_url       = snap["base_url"]
        loop.config.api_key        = snap["api_key"]
        loop.config.thinking       = snap["thinking"]
        loop.config.display_name   = snap["display_name"]
        loop.config.provider_order = snap["provider_order"]
        loop.config.client_script  = snap["client_script"]
        loop.config.request_kwargs = snap["request_kwargs"]

    if tier_cfg is not None:
        loop.config.model          = tier_cfg.model
        loop.config.base_url       = tier_cfg.base_url
        loop.config.api_key        = tier_cfg.api_key
        loop.config.thinking       = tier_cfg.thinking
        loop.config.display_name   = tier_cfg.display_name
        loop.config.provider_order = tier_cfg.provider_order
        loop.config.client_script  = tier_cfg.client_script
        loop.config.request_kwargs = tier_cfg.request_kwargs

    loop.client, script_rk = build_openai_client(loop.config)
    if script_rk:
        loop.config.request_kwargs = script_rk

    loop._extra_body = build_extra_body(
        loop.config.thinking, loop.config.cache_prompt, loop.config.provider_order,
    )

    loop._current_tier = target
    to_name = loop.config.display_name or loop.config.model
    loop.callbacks.on_model_switch(from_name, to_name)

    return f"Switched to '{target}' tier: {to_name}. Reason: {reason}"
