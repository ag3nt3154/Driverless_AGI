"""Tests for the read_large_text tool (.dagi/subagents/read-large-text/main.py)."""
from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import DAGI_ROOT
from agent.base_tool import BaseTool

SUBAGENTS_DIR = DAGI_ROOT / ".dagi" / "subagents"


def _load_tool_class() -> type:
    """Import main.py and return the BaseTool subclass."""
    main_py = SUBAGENTS_DIR / "read-large-text" / "main.py"
    mod_name = "_dagi_subagent_read_large_text"
    dagi_str = str(DAGI_ROOT)
    if dagi_str not in sys.path:
        sys.path.insert(0, dagi_str)
    spec = importlib.util.spec_from_file_location(mod_name, main_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseTool) and obj is not BaseTool:
            return obj
    raise RuntimeError(f"No BaseTool subclass in {main_py}")


def _make_runtime_args():
    config = MagicMock()
    config.project_path = Path("/tmp/project")
    config.plan_file = None
    config.active_plan_file = None
    callbacks = MagicMock()
    callbacks.on_subagent_event_factory = None
    tracker = MagicMock()
    tracker._depth = 0
    return config, callbacks, tracker


class TestReadLargeTextTool:
    def test_tool_name(self):
        cls = _load_tool_class()
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)
        assert tool.name == "read_large_text"

    def test_run_calls_run_subagent_with_preset_and_returns_handoff(self, tmp_path):
        cls = _load_tool_class()
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        handoff_path = tmp_path / "handoff.md"
        handoff_path.write_text("## Summary\nKey excerpt here.", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.status = "ok"
        mock_result.handoff_path = handoff_path

        with patch(
            "tools.subagent_api.run_subagent", return_value=mock_result
        ) as mock_run:
            result = tool.run(task="Summarize file.txt")

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["preset"] == "read-large-text"
        assert "Key excerpt here." in result

    def test_run_passes_custom_instructions_through(self, tmp_path):
        cls = _load_tool_class()
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        handoff_path = tmp_path / "handoff.md"
        handoff_path.write_text("done", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.is_ok = True
        mock_result.status = "ok"
        mock_result.handoff_path = handoff_path

        with patch(
            "tools.subagent_api.run_subagent", return_value=mock_result
        ) as mock_run:
            tool.run(
                task="Summarize file.txt",
                custom_instructions="Focus on section 3.",
            )

        assert (
            mock_run.call_args.kwargs["custom_instructions"] == "Focus on section 3."
        )

    def test_run_dispatches_error_status(self):
        cls = _load_tool_class()
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        mock_result = MagicMock()
        mock_result.is_ok = False
        mock_result.status = "timeout"
        mock_result.pid = 1234
        mock_result.escalation = None

        with patch("tools.subagent_api.run_subagent", return_value=mock_result):
            result = tool.run(task="Summarize file.txt")

        assert "timeout" in result
        assert "1234" in result
