"""tests/test_config_loader.py — Tests for config_loader key resolution."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agent.config_loader import _build_config_from_entry, _load_affect_config


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


def test_affect_config_defaults_when_absent():
    """A missing affect block keeps the controller's documented defaults."""
    cfg = _load_affect_config({})
    assert cfg.drift_pull == 0.05
    assert cfg.drift_noise == 0.02
    assert cfg.emote_hysteresis == 0.05


@pytest.mark.parametrize("affect_value", [[], False, 0, "", None])
def test_affect_config_rejects_present_non_mapping_blocks(affect_value):
    """Present but malformed affect blocks must not be masked as defaults."""
    with pytest.raises(ValueError, match="affect"):
        _load_affect_config({"affect": affect_value})


def test_affect_config_preserves_raw_values_on_all_model_tiers(tmp_path):
    """Changing construction to omit worker/advanced affect values must fail here."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_model: default\n"
        "worker_model: worker\n"
        "advanced_model: advanced\n"
        "affect:\n"
        "  drift_pull: 0.12\n"
        "  drift_noise: 0.34\n"
        "  emote_hysteresis: 0.56\n"
        "models:\n"
        "  default:\n"
        "    model: test/default\n"
        "    api_url: https://example.com/v1\n"
        "    api_key: sk-test\n"
        "  worker:\n"
        "    model: test/worker\n"
        "    api_url: https://example.com/v1\n"
        "    api_key: sk-test\n"
        "  advanced:\n"
        "    model: test/advanced\n"
        "    api_url: https://example.com/v1\n"
        "    api_key: sk-test\n",
        encoding="utf-8",
    )

    from agent.config_loader import resolve_model_config

    cfg = resolve_model_config("default", config_path=cfg_file)
    configs = [cfg, cfg.worker_config, cfg.advanced_config]
    for tier in configs:
        assert tier is not None
        assert tier.affect_drift_pull == 0.12
        assert tier.affect_drift_noise == 0.34
        assert tier.affect_emote_hysteresis == 0.56
        assert tier.affect_wander_volatility == 0.08


@pytest.mark.parametrize(
    ("raw", "field"),
    [
        ({"affect": {"drift_pull": -0.01}}, "drift_pull"),
        ({"affect": {"drift_noise": float("inf")}}, "drift_noise"),
        ({"affect": {"drift_noise": 1.01}}, "drift_noise"),
        ({"affect": {"emote_hysteresis": -0.01}}, "emote_hysteresis"),
    ],
)
def test_affect_config_rejects_invalid_values_with_field_name(raw, field):
    """Bad affect values must fail loudly at config load, naming the bad field."""
    with pytest.raises(ValueError, match=field):
        _load_affect_config(raw)


# def test_tools_none_when_absent():
#     entry = {"model": "m", "api_url": "http://x", "api_key": "k"}
#     cfg = _build_config_from_entry(entry, {})
#     assert cfg.tools is None


class TestStreamResolution:
    def test_stream_defaults_true_when_absent(self, tmp_path, monkeypatch):
        """No `stream` key anywhere → resolved config streams by default."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is True

    def test_stream_global_false(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "stream: false\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is False

    def test_stream_per_model_overrides_global(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "default_model: m1\n"
            "stream: true\n"
            "models:\n"
            "  m1:\n"
            "    model: test/model\n"
            "    api_url: https://example.com/v1\n"
            "    api_key: sk-test\n"
            "    stream: false\n",
            encoding="utf-8",
        )
        from agent.config_loader import resolve_model_config
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.stream is False

    def test_dataclass_default_is_false(self):
        """Direct AgentConfig() construction (tests, benchmarks) must NOT stream —
        only configs resolved through config_loader get the streaming default."""
        from agent.loop import AgentConfig
        assert AgentConfig().stream is False

