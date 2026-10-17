"""Tests for the `max_spawned_agents` config key (GUI model-spawned peers).

Mirrors the existing `max_continuations` coverage in test_project_config.py
(loader) and test_config_editor.py (validator).
"""
from __future__ import annotations

from pathlib import Path

import pytest


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip(), encoding="utf-8")


def test_max_spawned_agents_defaults_to_four(tmp_path, monkeypatch):
    """With no key present, the loaded config defaults to 4."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
models:
  root-model:
    name: Root Model
    model: root/model
    api_url: http://root/v1
    api_key: root-key
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_spawned_agents == 4


def test_max_spawned_agents_override_is_loaded(tmp_path, monkeypatch):
    """An explicit override in config.yaml is read as an int."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
max_spawned_agents: 2
models:
  root-model:
    name: Root Model
    model: root/model
    api_url: http://root/v1
    api_key: root-key
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_spawned_agents == 2


def test_agent_config_default_field():
    from agent._loop_config import AgentConfig
    assert AgentConfig().max_spawned_agents == 4


from tests.test_config_editor import _check, vdoc  # noqa: F401 (vdoc = pytest fixture)


@pytest.mark.parametrize("value", [0, -1])
def test_validation_rejects_non_positive_max_spawned_agents(vdoc, value):
    """Validation rejects 0 and -1, the same way as max_continuations."""
    vdoc.set("max_spawned_agents", value)
    result = _check(vdoc)
    assert not result.ok
    assert any("max_spawned_agents" in e for e in result.errors)
