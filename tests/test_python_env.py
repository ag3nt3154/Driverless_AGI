"""Tests for DEFAULT_PYTHON_ENV system prompt injection."""
from __future__ import annotations

import os
from unittest.mock import patch


def test_python_env_from_conda(tmp_path):
    from agent.config_loader import _detect_python_env
    with patch.dict(os.environ, {"CONDA_DEFAULT_ENV": "dagi"}):
        assert _detect_python_env() == "conda:dagi"


def test_python_env_from_venv(tmp_path):
    from agent.config_loader import _detect_python_env
    with patch.dict(os.environ, {"VIRTUAL_ENV": "/home/user/.venv"}, clear=False):
        env = os.environ.copy()
        env.pop("CONDA_DEFAULT_ENV", None)
        with patch.dict(os.environ, env, clear=True):
            assert _detect_python_env() == "venv:/home/user/.venv"


def test_python_env_fallback():
    from agent.config_loader import _detect_python_env
    with patch.dict(os.environ, {}, clear=True):
        result = _detect_python_env()
        assert result.startswith("system:")
