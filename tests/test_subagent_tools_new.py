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


def _run_with_minimal_arguments(tool, type_name: str) -> None:
    """Exercise each wrapper without invoking a real subagent."""
    if type_name == "memory-add":
        tool.run(task="Remember this", category="knowledge")
    elif type_name == "memory-refresh":
        tool.run()
    elif type_name == "worker":
        tool.run(subtask_name="Implement it")
    elif type_name == "review":
        tool.run(
            material="/tmp/worker.md",
            passing_criteria=["All criteria met"],
        )
    else:
        tool.run(task="Do the task")


class TestGenericSubagentTool:
    # Maps every auto-discovered subagent directory name (under
    # .dagi/subagents/, i.e. every directory with both prompt.md and
    # subagent_config.yaml) to its expected tool `name`. All subagent-backed
    # tools now use a plain, task-descriptive name — the
    # `spawn_{type}_subagent` fallback naming convention was retired
    # project-wide so the LLM never sees "this is implemented via a spawned
    # subagent" in the tool name (mirroring `read_large_text`, which set the
    # precedent). This dict is the sole source of truth for expected names.
    _EXPECTED_TOOL_NAMES = {
        "read-large-text": "read_large_text",
        "explore_files": "explore_files",
        "web_research": "web_research",
        "memory-query": "memory_query",
        "memory-add": "memory_add",
        "memory-refresh": "memory_refresh",
        "review": "review_work",
        "worker": "run_worker",
    }

    @pytest.mark.parametrize("type_name", sorted(_EXPECTED_TOOL_NAMES))
    def test_tool_has_required_attributes(self, type_name):
        cls = _load_tool_class(type_name)
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "_parameters")
        assert isinstance(tool.name, str)
        expected_name = self._EXPECTED_TOOL_NAMES[type_name]
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
    def _make_ok_result(self, path="/tmp/review.md"):
        r = MagicMock()
        r.status = "ok"
        r.is_ok = True
        r.handoff_text = "LGTM."
        r.handoff_path = Path(path)
        return r

    def test_review_material_appears_in_task(self):
        """material path must appear in the composed task sent to run_subagent."""
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        with patch("tools.subagent_api.run_subagent", return_value=self._make_ok_result()) as mock_run:
            tool.run(
                material="/tmp/worker.md",
                passing_criteria=["No regressions", "All tests green"],
            )

        task_text = mock_run.call_args.kwargs["task"]
        assert "/tmp/worker.md" in task_text
        assert "No regressions" in task_text
        assert "All tests green" in task_text

    def test_review_standalone_plan_no_active_plan(self):
        """Reviewer can evaluate a plan document with no active plan or worker report."""
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        config.plan_file = None
        config.active_plan_file = None
        tool = cls(config=config, callbacks=cb, tracker=tr)

        with patch("tools.subagent_api.run_subagent", return_value=self._make_ok_result()) as mock_run:
            result = tool.run(
                material="docs/plan.md",
                passing_criteria=["Plan covers rollback"],
                context="Reviewing the delivery plan before implementation.",
            )

        task_text = mock_run.call_args.kwargs["task"]
        assert "docs/plan.md" in task_text
        assert "Plan covers rollback" in task_text
        assert "Reviewing the delivery plan" in task_text
        assert mock_run.call_args.kwargs["preset"] == "review"

    def test_review_explicit_diff_preserves_criteria_and_verification(self):
        """Diff-based review must include all caller-supplied fields in the task."""
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        with patch("tools.subagent_api.run_subagent", return_value=self._make_ok_result()) as mock_run:
            tool.run(
                material="git diff HEAD~1",
                passing_criteria=["No secrets committed", "Tests not deleted"],
                context="Post-merge diff check.",
                verification="Run: pytest tests/ -q",
            )

        task_text = mock_run.call_args.kwargs["task"]
        assert "git diff HEAD~1" in task_text
        assert "No secrets committed" in task_text
        assert "Tests not deleted" in task_text
        assert "pytest tests/ -q" in task_text

    def test_review_empty_material_returns_error(self):
        """Empty material must return an actionable error without calling run_subagent."""
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(material="   ", passing_criteria=["All good"])

        mock_run.assert_not_called()
        assert "material" in result.lower()

    def test_review_empty_criteria_returns_error(self):
        """Empty passing_criteria must return an actionable error without calling run_subagent."""
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        tool = cls(config=config, callbacks=cb, tracker=tr)

        with patch("tools.subagent_api.run_subagent") as mock_run:
            result = tool.run(material="/tmp/plan.md", passing_criteria=[])

        mock_run.assert_not_called()
        assert "passing_criteria" in result.lower()


class TestReviewOutcomeRouting:
    """Verify that ESCALATE and PASS reviewer outcomes reach the caller correctly."""

    def _make_review_tool(self):
        cls = _load_tool_class("review")
        config, cb, tr = _make_runtime_args()
        config.plan_file = None
        config.active_plan_file = None
        return cls(config=config, callbacks=cb, tracker=tr)

    def _result(self, status, handoff_text="", handoff_path="/tmp/review.md"):
        r = MagicMock()
        r.status = status
        r.is_ok = status in ("ok", "ok_unverified")
        r.handoff_text = handoff_text
        r.handoff_path = Path(handoff_path)
        r.message = ""
        r.exit_code = 0
        r.output_tail = ""
        r.output_log_path = None
        return r

    def test_escalate_report_reaches_caller(self, tmp_path):
        """ESCALATE handoff content must flow through format_handoff_result to the caller."""
        escalate_content = (
            "## Outcome\nESCALATE\n\n"
            "## Blocking Findings\n1. Missing error handling in parser.\n"
        )
        handoff_path = tmp_path / "review_abc.md"
        handoff_path.write_text(escalate_content, encoding="utf-8")
        tool = self._make_review_tool()

        with patch("tools.subagent_api.run_subagent",
                   return_value=self._result("ok", handoff_path=str(handoff_path))):
            result = tool.run(
                material="src/parser.py",
                passing_criteria=["Error paths handled"],
            )

        assert "ESCALATE" in result
        assert "Missing error handling" in result

    def test_pass_with_observations_includes_full_report(self, tmp_path):
        """PASS with non-blocking observations must retain all observation text."""
        pass_content = (
            "## Outcome\nPASS\n\n"
            "## Non-blocking Observations\n- Minor: variable name could be clearer.\n"
        )
        handoff_path = tmp_path / "review_pass.md"
        handoff_path.write_text(pass_content, encoding="utf-8")
        tool = self._make_review_tool()

        with patch("tools.subagent_api.run_subagent",
                   return_value=self._result("ok", handoff_path=str(handoff_path))):
            result = tool.run(
                material="src/parser.py",
                passing_criteria=["All criteria met"],
            )

        assert "PASS" in result
        assert "Non-blocking Observations" in result or "variable name" in result

    def test_child_crash_diagnostics_reach_caller(self):
        """A child crash (no handoff) must include output_tail and exit code in result."""
        tool = self._make_review_tool()
        crashed = MagicMock()
        crashed.status = "error"
        crashed.is_ok = False
        crashed.message = "reviewer exited without writing handoff"
        crashed.exit_code = 1
        crashed.output_tail = "Traceback (most recent call last):\n  File 'main.py'"
        crashed.output_log_path = None
        crashed.pid = 999

        with patch("tools.subagent_api.run_subagent", return_value=crashed):
            result = tool.run(
                material="plan.md",
                passing_criteria=["Plan is complete"],
            )

        assert "Traceback" in result or "main.py" in result
        assert "1" in result  # exit code present


class TestSessionLogThreading:
    """session_log is threaded from create_tool_registry to subagent tools."""

    def test_discover_passes_session_log(self, tmp_path):
        """_discover_subagent_tools passes session_log to tool constructors."""
        from agent.subagent_tools import _discover_subagent_tools
        from agent.session_log import SessionLog
        from unittest.mock import MagicMock

        log = SessionLog()
        config = MagicMock()
        config.project_path = tmp_path

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            session_log=log,
        )
        for tool in tools:
            assert getattr(tool, "_session_log", None) is log

    def test_discover_passes_parent_context_to_all_typed_tools(self, tmp_path):
        """Every discovered live wrapper retains the loop's exact provider."""
        from agent.subagent_tools import _discover_subagent_tools

        config = MagicMock()
        config.project_path = tmp_path
        provider = object()

        tools = _discover_subagent_tools(
            cwd=tmp_path,
            config=config,
            callbacks=None,
            tracker=None,
            parent_context=provider,
        )

        assert tools
        for tool in tools:
            assert tool._parent_context is provider

    @pytest.mark.parametrize("type_name", sorted(TestGenericSubagentTool._EXPECTED_TOOL_NAMES))
    def test_typed_tools_forward_the_exact_parent_context(self, type_name):
        """Dropping or replacing the provider would lose inherited parent state."""
        cls = _load_tool_class(type_name)
        config, callbacks, tracker = _make_runtime_args()
        provider = object()
        tool = cls(
            config=config,
            callbacks=callbacks,
            tracker=tracker,
            parent_context=provider,
        )
        result = MagicMock(is_ok=False, status="error", pid=None)

        with patch("tools.subagent_api.run_subagent", return_value=result) as mock_run:
            _run_with_minimal_arguments(tool, type_name)

        assert tool._parent_context is provider
        assert mock_run.call_args.kwargs["parent_context"] is provider

