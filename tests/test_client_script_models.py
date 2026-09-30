"""Standalone .py client scripts in .dagi/model_config/ act as catalog models."""
from __future__ import annotations

import textwrap
from pathlib import Path

import openai
import pytest

from agent._model_switch import build_openai_client, load_client_script
from agent.config_loader import list_model_ids, load_raw_config, resolve_model_config


def _write_script(model_dir: Path, stem: str, body: str) -> Path:
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / f"{stem}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


CORP_SCRIPT = """
    import httpx, openai

    client = openai.OpenAI(
        api_key="sk-corp",
        base_url="https://llm-proxy.corp.example.com/v1",
        default_headers={"ENABLE-GUARDRAILS-INPUT-CHECK": "false"},
        http_client=openai.DefaultHttpxClient(transport=httpx.HTTPTransport(retries=1)),
    )

    request_kwargs = {"model": "gpt-4o", "temperature": 0.2}

    dagi_config = {"name": "GPT-4o (Corp)", "context_window": 64000}
"""


@pytest.fixture
def cfg_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text("default_model: corp_gpt4o\n", encoding="utf-8")
    _write_script(tmp_path / "model_config", "corp_gpt4o", CORP_SCRIPT)
    return path


def test_py_script_is_catalog_entry_without_yaml(cfg_file):
    catalog = load_raw_config(cfg_file)["models"]
    assert "corp_gpt4o" in catalog
    entry = catalog["corp_gpt4o"]
    assert Path(entry["client_script"]) == cfg_file.parent / "model_config" / "corp_gpt4o.py"
    # Static metadata is read without executing the script.
    assert entry["name"] == "GPT-4o (Corp)"
    assert entry["model"] == "gpt-4o"


def test_underscore_prefixed_scripts_are_ignored(cfg_file):
    _write_script(cfg_file.parent / "model_config", "_helpers", "x = 1\n")
    assert "_helpers" not in load_raw_config(cfg_file)["models"]


def test_yaml_entry_wins_over_same_named_script(cfg_file):
    (cfg_file.parent / "model_config" / "corp_gpt4o.yaml").write_text(
        "name: From YAML\nmodel: yaml-model\napi_key: sk-y\n", encoding="utf-8"
    )
    assert load_raw_config(cfg_file)["models"]["corp_gpt4o"]["name"] == "From YAML"


def test_resolve_default_model_from_script(cfg_file):
    cfg = resolve_model_config(config_path=cfg_file)
    assert cfg.model_id == "corp_gpt4o"
    assert cfg.display_name == "GPT-4o (Corp)"
    assert cfg.model == "gpt-4o"
    assert cfg.context_window == 64000
    # Identity is taken from the constructed client so subagents can re-resolve it.
    assert cfg.base_url.rstrip("/") == "https://llm-proxy.corp.example.com/v1"
    assert cfg.api_key == "sk-corp"
    assert cfg.client_script is not None


def test_client_comes_from_script(cfg_file):
    cfg = resolve_model_config(config_path=cfg_file)
    client, request_kwargs = build_openai_client(cfg)
    assert isinstance(client, openai.OpenAI)
    assert client.default_headers["ENABLE-GUARDRAILS-INPUT-CHECK"] == "false"
    assert request_kwargs["temperature"] == 0.2


def test_dynamic_model_name_resolved_by_executing(tmp_path, monkeypatch):
    monkeypatch.setenv("CORP_MODEL", "dyn-model")
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("default_model: dyn\n", encoding="utf-8")
    _write_script(
        tmp_path / "model_config",
        "dyn",
        """
        import os, openai
        client = openai.OpenAI(api_key="k", base_url="https://x.example/v1")
        request_kwargs = {"model": os.environ["CORP_MODEL"]}
        """,
    )
    assert "model" not in load_raw_config(cfg_file)["models"]["dyn"]
    assert resolve_model_config(config_path=cfg_file).model == "dyn-model"


def test_script_without_model_raises(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("default_model: nomodel\n", encoding="utf-8")
    _write_script(
        tmp_path / "model_config",
        "nomodel",
        """
        import openai
        client = openai.OpenAI(api_key="k", base_url="https://x.example/v1")
        """,
    )
    with pytest.raises(ValueError, match="model"):
        resolve_model_config(config_path=cfg_file)


def test_async_client_rejected_with_hint(tmp_path):
    path = _write_script(
        tmp_path,
        "async_one",
        """
        import openai
        client = openai.AsyncOpenAI(api_key="k", base_url="https://x.example/v1")
        """,
    )
    with pytest.raises(TypeError, match="AsyncOpenAI"):
        load_client_script(str(path))


def test_broken_worker_script_does_not_block_startup(tmp_path, capsys):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "default_model: corp_gpt4o\nworker_model: broken\n", encoding="utf-8"
    )
    _write_script(tmp_path / "model_config", "corp_gpt4o", CORP_SCRIPT)
    _write_script(tmp_path / "model_config", "broken", "raise RuntimeError('boom')\n")
    cfg = resolve_model_config(config_path=cfg_file)
    assert cfg.worker_config is None
    assert "broken" in capsys.readouterr().err


def test_list_model_ids_includes_scripts(cfg_file, monkeypatch):
    import agent.config_loader as cl

    monkeypatch.setattr(cl, "_CONFIG_PATH", cfg_file)
    assert "corp_gpt4o" in list_model_ids()


def test_subagent_inheritance_matches_script_model(cfg_file, tmp_path, monkeypatch):
    import agent.config_loader as cl
    from tools.subagent_main import _find_inherited_model_id

    monkeypatch.setattr(cl, "_CONFIG_PATH", cfg_file)
    project = tmp_path / "project"
    project.mkdir()
    found = _find_inherited_model_id(
        "gpt-4o", "https://llm-proxy.corp.example.com/v1/", project
    )
    assert found == "corp_gpt4o"
