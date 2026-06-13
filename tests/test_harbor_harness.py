"""tests/test_harbor_harness.py — Harbor harness regression tests."""
from __future__ import annotations
from pathlib import Path
from agent.loop import AgentConfig


class TestSystemPromptPreamble:
    def test_default_is_empty(self):
        cfg = AgentConfig()
        assert cfg.system_prompt_preamble == ""

    def test_preamble_field_accepts_string(self):
        cfg = AgentConfig(system_prompt_preamble="## Harbor\nuse harbor_bash")
        assert "harbor_bash" in cfg.system_prompt_preamble
