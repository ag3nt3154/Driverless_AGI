"""tests/test_harbor_harness.py — Harbor harness regression tests."""
from __future__ import annotations
import textwrap
from pathlib import Path
from agent.loop import AgentConfig
from agent.config_loader import resolve_model_config


class TestSystemPromptPreamble:
    def test_default_is_empty(self):
        cfg = AgentConfig()
        assert cfg.system_prompt_preamble == ""

    def test_preamble_field_accepts_string(self):
        cfg = AgentConfig(system_prompt_preamble="## Harbor\nuse harbor_bash")
        assert "harbor_bash" in cfg.system_prompt_preamble


class TestPreambleFromConfig:
    def test_preamble_read_from_yaml(self, tmp_path):
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(textwrap.dedent("""
            system_prompt_preamble: "## Harbor\\nuse harbor_bash"
            default_model: m
            models:
              m:
                name: Test
                model: test-model
                api_url: http://localhost
                api_key: test-key
        """), encoding="utf-8")
        cfg = resolve_model_config(config_path=cfg_yaml)
        assert cfg.system_prompt_preamble == "## Harbor\nuse harbor_bash"

    def test_preamble_defaults_to_empty_when_absent(self, tmp_path):
        cfg_yaml = tmp_path / "config.yaml"
        cfg_yaml.write_text(textwrap.dedent("""
            default_model: m
            models:
              m:
                name: Test
                model: test-model
                api_url: http://localhost
                api_key: test-key
        """), encoding="utf-8")
        cfg = resolve_model_config(config_path=cfg_yaml)
        assert cfg.system_prompt_preamble == ""
