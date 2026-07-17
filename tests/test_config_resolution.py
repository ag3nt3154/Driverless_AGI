"""tests/test_config_resolution.py — Tests for config_loader file loading, merging,
and top-level resolve_model_config()/save_config() behaviour (complements the
key-resolution tests in test_config_loader.py)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
import yaml

from agent.config_loader import (
    _load_project_config,
    _merge_configs,
    list_model_ids,
    load_raw_config,
    resolve_model_config,
    save_config,
)


def _write_config(path, text):
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadRawConfig:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        missing = tmp_path / "does_not_exist.yaml"
        assert load_raw_config(config_path=missing) == {}

    def test_reads_and_parses_yaml(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\nmodels:\n  m1:\n    model: test/model\n",
        )
        raw = load_raw_config(config_path=cfg_file)
        assert raw["default_model"] == "m1"
        assert raw["models"]["m1"]["model"] == "test/model"

    def test_empty_file_returns_empty_dict(self, tmp_path):
        cfg_file = _write_config(tmp_path / "config.yaml", "")
        assert load_raw_config(config_path=cfg_file) == {}


class TestListModelIds:
    def test_returns_catalog_keys_in_order(self, tmp_path, monkeypatch):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "models:\n  alpha:\n    model: a\n  beta:\n    model: b\n",
        )
        monkeypatch.setattr("agent.config_loader._CONFIG_PATH", cfg_file)
        assert list_model_ids() == ["alpha", "beta"]

    def test_no_models_key_returns_empty_list(self, tmp_path, monkeypatch):
        cfg_file = _write_config(tmp_path / "config.yaml", "default_model: m1\n")
        monkeypatch.setattr("agent.config_loader._CONFIG_PATH", cfg_file)
        assert list_model_ids() == []


class TestLoadProjectConfig:
    def test_missing_project_config_returns_none(self, tmp_path):
        assert _load_project_config(tmp_path) is None

    def test_reads_project_dagi_config(self, tmp_path):
        dagi_dir = tmp_path / ".dagi"
        dagi_dir.mkdir()
        _write_config(dagi_dir / "config.yaml", "default_model: project-model\n")

        raw = _load_project_config(tmp_path)

        assert raw["default_model"] == "project-model"

    def test_invalid_yaml_raises_value_error(self, tmp_path):
        dagi_dir = tmp_path / ".dagi"
        dagi_dir.mkdir()
        _write_config(dagi_dir / "config.yaml", "key: [unclosed")

        with pytest.raises(ValueError, match="Invalid YAML"):
            _load_project_config(tmp_path)


class TestMergeConfigs:
    def test_project_scalar_wins_over_root(self):
        root = {"default_model": "root-model", "stream": True}
        project = {"default_model": "project-model"}
        merged = _merge_configs(root, project)
        assert merged["default_model"] == "project-model"
        assert merged["stream"] is True

    def test_model_catalogs_are_shallow_merged(self):
        root = {"models": {"m1": {"model": "root/m1"}, "m2": {"model": "root/m2"}}}
        project = {"models": {"m1": {"model": "project/m1"}, "m3": {"model": "project/m3"}}}
        merged = _merge_configs(root, project)
        assert merged["models"] == {
            "m1": {"model": "project/m1"},
            "m2": {"model": "root/m2"},
            "m3": {"model": "project/m3"},
        }

    def test_root_only_key_survives_when_project_lacks_it(self):
        root = {"bash_backend": "subprocess"}
        project = {}
        merged = _merge_configs(root, project)
        assert merged["bash_backend"] == "subprocess"


class TestResolveModelConfig:
    def test_explicit_model_id_wins_over_default(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "models:\n"
            "  m1:\n    model: model-one\n    api_url: https://x/v1\n    api_key: sk-1\n"
            "  m2:\n    model: model-two\n    api_url: https://x/v1\n    api_key: sk-2\n",
        )
        cfg = resolve_model_config("m2", config_path=cfg_file)
        assert cfg.model == "model-two"

    def test_falls_back_to_default_model_when_none_given(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "models:\n  m1:\n    model: model-one\n    api_url: https://x/v1\n    api_key: sk-1\n",
        )
        cfg = resolve_model_config(None, config_path=cfg_file)
        assert cfg.model == "model-one"

    def test_falls_back_to_builtin_default_when_no_config_at_all(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        with patch.dict(os.environ, {}, clear=False):
            cfg = resolve_model_config(None, config_path=missing)
        assert cfg.model == "gpt-4o"

    def test_unknown_model_id_raises_key_error(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "models:\n  m1:\n    model: model-one\n    api_url: https://x/v1\n    api_key: sk-1\n",
        )
        with pytest.raises(KeyError):
            resolve_model_config("does-not-exist", config_path=cfg_file)

    def test_project_path_merges_project_config_over_root(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "models:\n  m1:\n    model: root-model\n    api_url: https://x/v1\n    api_key: sk-1\n",
        )
        project_dir = tmp_path / "myproject"
        dagi_dir = project_dir / ".dagi"
        dagi_dir.mkdir(parents=True)
        _write_config(
            dagi_dir / "config.yaml",
            "models:\n  m1:\n    model: project-model\n    api_url: https://x/v1\n    api_key: sk-1\n",
        )

        cfg = resolve_model_config("m1", config_path=cfg_file, project_path=project_dir)

        assert cfg.model == "project-model"
        assert cfg.project_path == project_dir

    def test_worker_model_resolved_when_present_in_catalog(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "worker_model: m2\n"
            "models:\n"
            "  m1:\n    model: model-one\n    api_url: https://x/v1\n    api_key: sk-1\n"
            "  m2:\n    model: model-two\n    api_url: https://x/v1\n    api_key: sk-2\n",
        )
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.worker_config is not None
        assert cfg.worker_config.model == "model-two"

    def test_unknown_worker_model_silently_ignored(self, tmp_path):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "worker_model: does-not-exist\n"
            "models:\n  m1:\n    model: model-one\n    api_url: https://x/v1\n    api_key: sk-1\n",
        )
        cfg = resolve_model_config("m1", config_path=cfg_file)
        assert cfg.worker_config is None


class TestSaveConfig:
    def test_save_config_updates_default_model_and_preserves_rest(self, tmp_path, monkeypatch):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\n"
            "stream: true\n"
            "models:\n  m1:\n    model: model-one\n",
        )
        monkeypatch.setattr("agent.config_loader._CONFIG_PATH", cfg_file)

        save_config("m2")

        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        assert raw["default_model"] == "m2"
        assert raw["stream"] is True
        assert raw["models"]["m1"]["model"] == "model-one"

    def test_save_config_drops_legacy_max_iterations_key(self, tmp_path, monkeypatch):
        cfg_file = _write_config(
            tmp_path / "config.yaml",
            "default_model: m1\nmax_iterations: 42\n",
        )
        monkeypatch.setattr("agent.config_loader._CONFIG_PATH", cfg_file)

        save_config("m1")

        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8"))
        assert "max_iterations" not in raw
