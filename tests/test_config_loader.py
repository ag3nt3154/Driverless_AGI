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


from agent.config_loader import PdfConfig, load_pdf_config


class TestLoadPdfConfig:
    def test_defaults_when_pdf_key_absent(self, monkeypatch):
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {})
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=2.0, max_workers=None)

    def test_overrides_from_config(self, monkeypatch):
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"worker_ram_gb": 4.0, "max_workers": 3}},
        )
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=4.0, max_workers=3)

    def test_partial_override_keeps_other_default(self, monkeypatch):
        monkeypatch.setattr(
            "agent.config_loader.load_raw_config",
            lambda: {"pdf": {"max_workers": 5}},
        )
        cfg = load_pdf_config()
        assert cfg.worker_ram_gb == 2.0
        assert cfg.max_workers == 5

    def test_null_pdf_key_uses_defaults(self, monkeypatch):
        monkeypatch.setattr("agent.config_loader.load_raw_config", lambda: {"pdf": None})
        cfg = load_pdf_config()
        assert cfg == PdfConfig(worker_ram_gb=2.0, max_workers=None)
