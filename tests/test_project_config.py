"""Tests for per-project config + prompt resolution."""
from __future__ import annotations

from pathlib import Path

import pytest


# ── Prompt resolution ────────────────────────────────────────────────────────

def test_load_main_system_prompt_falls_back_to_dagi_root(tmp_path):
    """When no project prompt exists, load from dagi root."""
    from agent.prompts import load_main_system_prompt
    dagi_root = Path(__file__).parent.parent
    # tmp_path has no .dagi/prompts/main_system.md
    result = load_main_system_prompt(dagi_root, tmp_path)
    # Should be the real dagi system prompt (non-empty, contains known marker)
    assert "<<END_OF_RESPONSE>>" in result or "<<TASK_END>>" in result


def test_load_main_system_prompt_uses_project_prompt_when_present(tmp_path):
    """When project has a main_system.md, it fully replaces the dagi root prompt."""
    from agent.prompts import load_main_system_prompt
    project_prompt_dir = tmp_path / ".dagi" / "prompts"
    project_prompt_dir.mkdir(parents=True)
    (project_prompt_dir / "main_system.md").write_text(
        "Project-specific system prompt.\n{tools_and_skills}\n", encoding="utf-8"
    )
    dagi_root = Path(__file__).parent.parent
    result = load_main_system_prompt(dagi_root, tmp_path)
    assert result == "Project-specific system prompt.\n{tools_and_skills}\n"


def test_load_soul_falls_back_to_dagi_root(tmp_path):
    """When no project soul exists, load from dagi root .dagi/prompts/soul.md."""
    from agent.prompts import load_soul
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    # Dagi root soul exists and is non-empty (content is intentionally not asserted)
    assert result is not None and len(result) > 0


def test_load_soul_uses_project_soul_when_present(tmp_path):
    """Project .dagi/prompts/soul.md overrides dagi root soul."""
    from agent.prompts import load_soul
    soul_dir = tmp_path / ".dagi" / "prompts"
    soul_dir.mkdir(parents=True)
    (soul_dir / "soul.md").write_text("Custom project persona.\n", encoding="utf-8")
    dagi_root = Path(__file__).parent.parent
    result = load_soul(dagi_root, tmp_path)
    assert result == "Custom project persona.\n"


def test_load_soul_returns_none_when_absent(tmp_path):
    """Returns None when neither project nor dagi root soul exists."""
    from agent.prompts import load_soul
    # Point dagi_root to tmp_path so neither soul exists
    result = load_soul(tmp_path, tmp_path)
    assert result is None


# ── Config merge ─────────────────────────────────────────────────────────────

def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip(), encoding="utf-8")


def test_project_config_overrides_scalar_field(tmp_path, monkeypatch):
    """Project config scalars win over dagi root scalars."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
max_continuations: 10
models:
  root-model:
    name: Root Model
    model: root/model
    api_url: http://root/v1
    api_key: root-key
""")
    _write_yaml(tmp_path / ".dagi" / "config.yaml", """
max_continuations: 3
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_continuations == 3


def test_project_config_model_catalog_merged(tmp_path, monkeypatch):
    """Project model catalog entries are added to root catalog."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
models:
  root-model:
    name: Root
    model: root/m
    api_url: http://root/v1
    api_key: rk
""")
    _write_yaml(tmp_path / ".dagi" / "config.yaml", """
default_model: fast-local
models:
  fast-local:
    name: Local
    model: ollama/llama
    api_url: http://localhost:11434/v1
    api_key: ollama
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.model == "ollama/llama"
    assert cfg.base_url == "http://localhost:11434/v1"


def test_project_config_absent_uses_root(tmp_path, monkeypatch):
    """When no project config exists, root config is used unchanged."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
max_continuations: 7
models:
  root-model:
    name: Root
    model: root/m
    api_url: http://root/v1
    api_key: rk
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    assert cfg.max_continuations == 7


def test_project_config_invalid_yaml_raises(tmp_path, monkeypatch):
    """Invalid YAML in project config surfaces a clear ValueError."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
models:
  root-model:
    name: Root
    model: root/m
    api_url: http://root/v1
    api_key: rk
""")
    bad = tmp_path / ".dagi" / "config.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text(": bad: yaml: [unclosed\n", encoding="utf-8")
    from agent.config_loader import resolve_model_config
    with pytest.raises(ValueError, match=".dagi"):
        resolve_model_config(project_path=tmp_path, config_path=root_cfg)


def test_project_config_models_null_does_not_crash(tmp_path, monkeypatch):
    """Project config with 'models: null' should not crash — treated as no model overrides."""
    monkeypatch.chdir(tmp_path)
    root_cfg = tmp_path / "config.yaml"
    _write_yaml(root_cfg, """
default_model: root-model
models:
  root-model:
    name: Root
    model: root/m
    api_url: http://root/v1
    api_key: rk
""")
    _write_yaml(tmp_path / ".dagi" / "config.yaml", """
models:
""")
    from agent.config_loader import resolve_model_config
    cfg = resolve_model_config(project_path=tmp_path, config_path=root_cfg)
    # Root model still accessible — no crash
    assert cfg.model == "root/m"
