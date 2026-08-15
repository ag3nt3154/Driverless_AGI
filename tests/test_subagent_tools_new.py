"""Tests for auto-discovered subagent BaseTool wrappers in .dagi/subagents/*/main.py."""
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


def _load_tool_class(type_name: str) -> type:
    """Import main.py and return the BaseTool subclass."""
    main_py = SUBAGENTS_DIR / type_name / "main.py"
    mod_name = f"_dagi_subagent_{type_name}"
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


class TestGenericSubagentTool:
    # Maps a subagent directory name to its expected tool `name` when the two
    # differ. `read-large-text` still exposes the tool as
    # `spawn_document-reader_subagent` pending a later rename that also
    # updates benchmarks/dagi_eval/config_dagi_eval.yaml in lockstep.
    _TOOL_NAME_OVERRIDES = {"read-large-text": "spawn_document-reader_subagent"}

    @pytest.mark.parametrize("type_name", [
        "explore_files", "web_research", "memory-query",
        "memory-add", "read-large-text",
    ])
    def test_tool_has_required_attributes(self, type_name):
        cls = _load_tool_class(type_name)
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "_parameters")
        assert isinstance(tool.name, str)
        expected_name = self._TOOL_NAME_OVERRIDES.get(
            type_name, f"spawn_{type_name}_subagent"
        )
        assert tool.name == expected_name

    @pytest.mark.parametrize("type_name", [
        "explore_files", "web_research",
    ])
    def test_generic_tool_calls_run_subagent_with_preset(self, type_name):
        cls = _load_tool_class(type_name)
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        mock_result = MagicMock()
        mock_result.status = "ok"
        mock_result.handoff_text = "Found things."
        mock_result.handoff_path = Path("/tmp/h.md")
        with patch(
            f"tools.subagent_api.run_subagent", return_value=mock_result,
        ) as mock_run:
            tool.run(task="Find stuff")

        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["preset"] == type_name


class TestWorkerSubagentTool:
    def test_worker_extracts_subtask_from_plan(self):
        cls = _load_tool_class("worker")
        config, cb, tr = _make_runtime_args()
        plan_file = Path("/tmp/plan.md")
        config.plan_file = plan_file
        config.active_plan_file = None
        tool = cls(config=config, callbacks=cb, tracker=tr)

        mock_result = MagicMock()
        mock_result.status = "ok"
        mock_result.handoff_text = "Implemented."
        mock_result.handoff_path = Path("/tmp/h.md")
        with patch("tools.subagent_api.run_subagent", return_value=mock_result), \
             patch("builtins.open", create=True), \
             patch.object(Path, "read_text", return_value=(
                 "## Subtasks\n\n### Subtask 1: Do it\n**Goal:** Build.\n"
             )):
            result = tool.run(subtask_name="Do it")

        assert "Implemented." in result

    def test_ok_unverified_includes_banner(self):
        """ok_unverified must route through format_handoff_result so the banner is prepended."""
        cls = _load_tool_class("worker")
        config, cb, tr = _make_runtime_args()
        config.plan_file = Path("/tmp/plan.md")
        config.active_plan_file = None
        tool = cls(config=config, callbacks=cb, tracker=tr)

        mock_result = MagicMock()
        mock_result.status = "ok_unverified"
        mock_result.is_ok = True
        mock_result.handoff_text = "scraped text"  # must NOT be returned directly
        mock_result.handoff_path = Path("/tmp/h.md")
        plan_content = "## Subtasks\n\n### Subtask 1: Do it\n**Goal:** Build.\n"

        def _read_text_side_effect(self_path, *args, **kwargs):
            if "plan" in str(self_path):
                return plan_content
            return "## Handoff\nWork done.\n"

        with patch("tools.subagent_api.run_subagent", return_value=mock_result), \
             patch.object(Path, "read_text", _read_text_side_effect):
            result = tool.run(subtask_name="Do it")

        assert "UNVERIFIED" in result, f"Expected unverified banner in result, got: {result!r}"
        assert "scraped text" not in result, "handoff_text fast-path must be skipped for ok_unverified"


class TestReviewSubagentTool:
    def test_review_includes_worker_handoff_path(self):
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        mock_result = MagicMock()
        mock_result.status = "ok"
        mock_result.handoff_text = "LGTM."
        mock_result.handoff_path = Path("/tmp/review.md")
        with patch("tools.subagent_api.run_subagent", return_value=mock_result) as mock_run:
            tool.run(
                subtask_name="Do it",
                worker_handoff_path="/tmp/worker.md",
                unit_test_paths=["tests/test_a.py"],
            )

        call_kwargs = mock_run.call_args.kwargs
        assert "/tmp/worker.md" in call_kwargs.get("custom_instructions", "") or \
               "/tmp/worker.md" in call_kwargs.get("task", "")
