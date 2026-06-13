"""tests/test_config_loader.py — Tests for config_loader key resolution."""
from __future__ import annotations

import os
from unittest.mock import patch

from agent.config_loader import _build_config_from_entry


def test_direct_api_key_used_when_present():
    """api_key in entry must be used verbatim, env vars not consulted."""
    entry = {
        "model": "my-model",
        "api_url": "https://custom.provider/v1",
        "api_key": "sk-direct-key-123",
        "name": "Test Model",
    }
    with patch.dict(os.environ, {}, clear=False):
        cfg = _build_config_from_entry(entry, {})
    assert cfg.api_key == "sk-direct-key-123"
    assert cfg.base_url == "https://custom.provider/v1"


def test_api_key_env_used_when_no_direct_key():
    """api_key_env pointer must still work when api_key is absent."""
    entry = {
        "model": "my-model",
        "api_url": "https://custom.provider/v1",
        "api_key_env": "MY_CUSTOM_KEY",
        "name": "Test Model",
    }
    with patch.dict(os.environ, {"MY_CUSTOM_KEY": "sk-env-key-456"}):
        cfg = _build_config_from_entry(entry, {})
    assert cfg.api_key == "sk-env-key-456"


def test_empty_direct_key_falls_back_to_env():
    """Empty string api_key must fall back to api_key_env lookup."""
    entry = {
        "model": "my-model",
        "api_url": "https://custom.provider/v1",
        "api_key": "",
        "api_key_env": "MY_CUSTOM_KEY",
        "name": "Test Model",
    }
    with patch.dict(os.environ, {"MY_CUSTOM_KEY": "sk-env-fallback"}):
        cfg = _build_config_from_entry(entry, {})
    assert cfg.api_key == "sk-env-fallback"


def test_tools_list_parsed_from_raw():
    entry = {"model": "m", "api_url": "http://x", "api_key": "k"}
    raw = {"tools": ["read", "grep", "bash"]}
    cfg = _build_config_from_entry(entry, raw)
    assert cfg.tools == ["read", "grep", "bash"]


# def test_tools_none_when_absent():
#     entry = {"model": "m", "api_url": "http://x", "api_key": "k"}
#     cfg = _build_config_from_entry(entry, {})
#     assert cfg.tools is None
