"""Tests for Stage 3 of the image input feature.

Covers: AgentConfig image fields, history labels for image messages,
image-aware token estimation, and model-switch preflight rejection.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from agent._loop_config import AgentConfig
from agent.history import _content_label, _derive_title, build_turn_list, build_copyable_messages
from tools.compact._tail_boundary import estimate_tokens
from tui.utils import _breakdown


# ── 1. AgentConfig defaults ─────────────────────────────────────────────────

def test_agent_config_image_defaults():
    cfg = AgentConfig()
    assert cfg.supports_images is None
    assert cfg.image_input_max_images_per_message == 4
    assert cfg.image_input_max_image_bytes == 8 * 1024 * 1024
    assert cfg.image_input_max_pixels == 24_000_000
    assert cfg.image_input_max_request_image_bytes == 20 * 1024 * 1024
    assert cfg.image_input_detail is None
    assert cfg.image_input_estimated_tokens_per_image == 1024


# ── 2. _content_label ────────────────────────────────────────────────────────

def test_content_label_plain_string():
    assert _content_label("hello world") == "hello world"


def test_content_label_text_only_list():
    content = [{"type": "text", "text": "hi there"}]
    assert _content_label(content) == "hi there"


def test_content_label_image_only():
    content = [{"type": "dagi_image", "sha256": "a" * 64}]
    assert _content_label(content) == "[1 image]"


def test_content_label_multiple_images():
    content = [
        {"type": "dagi_image", "sha256": "a" * 64},
        {"type": "dagi_image", "sha256": "b" * 64},
    ]
    assert _content_label(content) == "[2 images]"


def test_content_label_text_and_images():
    content = [
        {"type": "text", "text": "Check this screenshot"},
        {"type": "dagi_image", "sha256": "a" * 64},
    ]
    assert _content_label(content) == "Check this screenshot [1 image]"


def test_content_label_empty_list():
    assert _content_label([]) == ""


# ── 3. _derive_title with image-only messages ───────────────────────────────

def test_derive_title_image_only_message(tmp_path):
    path = tmp_path / "session_1_logs.jsonl"
    lines = [
        {
            "type": "session_end",
            "raw_messages": [
                {
                    "role": "user",
                    "content": [{"type": "dagi_image", "sha256": "a" * 64}],
                },
            ],
        },
    ]
    title = _derive_title(path, lines)
    assert title == "[1 image]"


def test_derive_title_text_and_image_message(tmp_path):
    path = tmp_path / "session_1_logs.jsonl"
    lines = [
        {
            "type": "session_end",
            "raw_messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look at this"},
                        {"type": "dagi_image", "sha256": "a" * 64},
                    ],
                },
            ],
        },
    ]
    title = _derive_title(path, lines)
    assert title == "look at this [1 image]"


def test_derive_title_falls_back_to_filename_stem(tmp_path):
    path = tmp_path / "session_1_logs.jsonl"
    assert _derive_title(path, []) == "session_1"


# ── 4. build_turn_list image labels ─────────────────────────────────────────

def test_build_turn_list_image_count_in_label():
    raw_messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Check this screenshot"},
                {"type": "dagi_image", "sha256": "a" * 64},
            ],
        },
    ]
    turns = build_turn_list(raw_messages)
    assert len(turns) == 1
    assert turns[0]["label"] == "Check this screenshot [1 image]"


def test_build_turn_list_image_only_label():
    raw_messages = [
        {"role": "user", "content": [{"type": "dagi_image", "sha256": "a" * 64}]},
    ]
    turns = build_turn_list(raw_messages)
    assert turns[0]["label"] == "[1 image]"


def test_build_copyable_messages_image_only_not_skipped():
    messages = [
        {"role": "user", "content": [{"type": "dagi_image", "sha256": "a" * 64}]},
    ]
    items = build_copyable_messages(messages)
    assert len(items) == 1
    assert "[1 image]" in items[0]["content"]


# ── 5. estimate_tokens image awareness ──────────────────────────────────────

def test_estimate_tokens_counts_images_not_flat_placeholder():
    msg_one_image = {"content": [{"type": "dagi_image", "sha256": "a" * 64}]}
    msg_two_images = {
        "content": [
            {"type": "dagi_image", "sha256": "a" * 64},
            {"type": "dagi_image", "sha256": "b" * 64},
        ]
    }
    one = estimate_tokens(msg_one_image)
    two = estimate_tokens(msg_two_images)
    assert one == 1024
    assert two == 2048
    assert two == 2 * one


def test_estimate_tokens_text_and_image_combo():
    msg = {
        "content": [
            {"type": "text", "text": "x" * 400},
            {"type": "dagi_image", "sha256": "a" * 64},
        ]
    }
    # 400 chars / 4 = 100 text tokens + 1024 image tokens
    assert estimate_tokens(msg) == 1124


def test_estimate_tokens_plain_text_unaffected():
    msg = {"content": "x" * 40}
    assert estimate_tokens(msg) == 10


# ── 6. _breakdown image awareness ───────────────────────────────────────────

def test_breakdown_counts_images_in_tokens():
    messages_text_only = [{"role": "user", "content": "x" * 40}]
    messages_with_image = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "x" * 40},
                {"type": "dagi_image", "sha256": "a" * 64},
            ],
        }
    ]
    text_only = _breakdown(messages_text_only)
    with_image = _breakdown(messages_with_image)
    assert with_image["user"] > text_only["user"]
    assert with_image["user"] - text_only["user"] == 1024


# ── 7. Model switch preflight rejection ─────────────────────────────────────

class _FakeLog:
    def __init__(self, messages):
        self._messages = messages

    def derive_messages(self):
        return self._messages


class _FakeCallbacks:
    def on_model_switch(self, *_args, **_kwargs):
        pass


class _FakeLoop:
    """Minimal stand-in exposing only what handle_switch_model touches."""

    def __init__(self, config, messages):
        self.config = config
        self.log = _FakeLog(messages)
        self._current_tier = "default"
        self.callbacks = _FakeCallbacks()
        self.client = None
        self._extra_body = {}
        self._base_config_snapshot = {
            "model": config.model,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "thinking": config.thinking,
            "display_name": config.display_name,
            "provider_order": config.provider_order,
            "client_script": config.client_script,
            "request_kwargs": dict(config.request_kwargs),
        }


def _image_history():
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look"},
                {"type": "dagi_image", "sha256": "a" * 64},
            ],
        },
    ]


def test_history_has_images_helper_detects_images():
    from agent._model_switch import _history_has_images

    loop = _FakeLoop(AgentConfig(), _image_history())
    assert _history_has_images(loop) is True


def test_history_has_images_helper_false_for_text_only():
    from agent._model_switch import _history_has_images

    loop = _FakeLoop(AgentConfig(), [{"role": "user", "content": "hello"}])
    assert _history_has_images(loop) is False


def test_switch_model_rejected_when_history_has_images_and_target_blocks(monkeypatch):
    from agent import _model_switch

    monkeypatch.setattr(
        _model_switch, "build_openai_client", lambda cfg: (object(), {})
    )

    worker_cfg = AgentConfig(model="no-vision-model", supports_images=False)
    base_cfg = AgentConfig(model="vision-model", worker_config=worker_cfg)

    loop = _FakeLoop(base_cfg, _image_history())

    result = _model_switch.handle_switch_model(loop, "worker", {})

    assert "does not support images" in result
    # Config must NOT have been mutated by the rejected switch.
    assert loop.config.model == "vision-model"
    assert loop._current_tier == "default"


def test_switch_model_allowed_when_target_supports_images(monkeypatch):
    from agent import _model_switch

    monkeypatch.setattr(
        _model_switch, "build_openai_client", lambda cfg: (object(), {})
    )

    worker_cfg = AgentConfig(model="vision-worker", supports_images=True)
    base_cfg = AgentConfig(model="vision-model", worker_config=worker_cfg)

    loop = _FakeLoop(base_cfg, _image_history())

    result = _model_switch.handle_switch_model(loop, "worker", {})

    assert "Switched to 'worker' tier" in result
    assert loop.config.model == "vision-worker"
    assert loop._current_tier == "worker"


def test_switch_model_allowed_when_no_images_in_history(monkeypatch):
    from agent import _model_switch

    monkeypatch.setattr(
        _model_switch, "build_openai_client", lambda cfg: (object(), {})
    )

    worker_cfg = AgentConfig(model="no-vision-model", supports_images=False)
    base_cfg = AgentConfig(model="vision-model", worker_config=worker_cfg)

    loop = _FakeLoop(base_cfg, [{"role": "user", "content": "hello"}])

    result = _model_switch.handle_switch_model(loop, "worker", {})

    assert "Switched to 'worker' tier" in result
    assert loop.config.model == "no-vision-model"
