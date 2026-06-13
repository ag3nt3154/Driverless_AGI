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


from unittest.mock import patch


class TestPreambleInjection:
    def _make_loop(self, preamble: str = ""):
        from agent.loop import AgentLoop, AgentConfig, AgentCallbacks
        cfg = AgentConfig(
            system_prompt="Base system prompt. {tools_and_skills}",
            system_prompt_preamble=preamble,
            api_key="test",
        )
        with patch("openai.OpenAI"):
            loop = AgentLoop(cfg, callbacks=AgentCallbacks())
        return loop

    def test_preamble_appears_in_system_message(self):
        loop = self._make_loop(preamble="HARBOR_PREAMBLE_MARKER")
        system_content = loop._messages[0]["content"]
        assert "HARBOR_PREAMBLE_MARKER" in system_content

    def test_preamble_appears_before_base_prompt(self):
        loop = self._make_loop(preamble="HARBOR_PREAMBLE_MARKER")
        system_content = loop._messages[0]["content"]
        assert system_content.index("HARBOR_PREAMBLE_MARKER") < system_content.index("Base system prompt")

    def test_no_preamble_leaves_system_unchanged(self):
        loop_with = self._make_loop(preamble="UNIQUE_MARKER")
        loop_without = self._make_loop(preamble="")
        assert "UNIQUE_MARKER" not in loop_without._messages[0]["content"]
