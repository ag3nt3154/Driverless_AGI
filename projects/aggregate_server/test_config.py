"""Tests for aggregate_server config loader."""

import pytest
import tempfile
import os
from pathlib import Path

from config import BackendConfig, ServerConfig, load_config


class TestBackendConfig:
    def test_dataclass_fields(self):
        b = BackendConfig(api_url="http://x", api_key="k", model_name="m")
        assert b.api_url == "http://x"
        assert b.api_key == "k"
        assert b.model_name == "m"


class TestServerConfig:
    def test_holds_backends(self):
        b1 = BackendConfig(api_url="http://a", api_key="k1", model_name="gpt-4o")
        b2 = BackendConfig(api_url="http://b", api_key="k2", model_name="claude-3")
        sc = ServerConfig(backends=[b1, b2])
        assert len(sc.backends) == 2


class TestLoadConfig:
    def test_loads_two_backends(self):
        yaml_content = """backends:
  - api_url: "https://api.openai.com/v1/chat/completions"
    api_key: "sk-key1"
    model_name: "gpt-4o"
  - api_url: "https://openrouter.ai/api/v1"
    api_key: "sk-key2"
    model_name: "claude-3-opus"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            sc = load_config(path)
            assert len(sc.backends) == 2
            assert sc.backends[0].api_url == "https://api.openai.com/v1/chat/completions"
            assert sc.backends[0].api_key == "sk-key1"
            assert sc.backends[0].model_name == "gpt-4o"
            assert sc.backends[1].api_key == "sk-key2"
        finally:
            os.unlink(path)

    def test_missing_backends_section(self):
        yaml_content = """generation_endpoint:
  api_url: "http://x"
  api_key: "k"
  model_name: "m"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="backends"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_api_url(self):
        yaml_content = """backends:
  - api_key: "sk-key"
    model_name: "gpt-4o"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="api_url"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_api_key(self):
        yaml_content = """backends:
  - api_url: "http://x"
    model_name: "gpt-4o"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="api_key"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_missing_model_name(self):
        yaml_content = """backends:
  - api_url: "http://x"
    api_key: "sk-key"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="model_name"):
                load_config(path)
        finally:
            os.unlink(path)

    def test_empty_backends_list(self):
        yaml_content = "backends: []"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name
        try:
            with pytest.raises(ValueError, match="at least one backend"):
                load_config(path)
        finally:
            os.unlink(path)
