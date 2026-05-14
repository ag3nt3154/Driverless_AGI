"""tests/test_spawn_subagent_tool.py — Unit tests for SpawnSubagentTool."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest
import yaml

from tools.spawn_subagent import SpawnSubagentTool, _FALLBACK_PARAMETERS


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

SAMPLE_PLAN = """\
# Plan — Test Feature

## Context
Why this change is needed.

## Approach
High-level strategy.

## Subtasks

### Subtask 1: Do the thing
**Goal:** Implement the feature.
**Requirements:**
- Requirement A
**Acceptance Criteria:**
- Works correctly
#### Tests
test_thing.py — tests the thing

### Subtask 2: Another task
**Goal:** Do something else.
"""

WORKER_SCHEMA = {
    "type": "object",
    "properties": {
        "subtask_name": {"type": "string", "description": "Name of the subtask."},
        "custom_instructions": {"type": "string", "description": "Extra instructions."},
        "handoff_file": {"type": "string", "description": "Path to write handoff report."},
    },
    "required": ["subtask_name", "handoff_file"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "subtask_name": {"type": "string", "description": "Name of the subtask being reviewed."},
        "handoff_report_path": {"type": "string", "description": "Path to the handoff report."},
        "unit_test_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Paths to unit test files.",
        },
        "review_file": {"type": "string", "description": "Path to write the review report."},
        "custom_instructions": {"type": "string", "description": "Extra instructions."},
    },
    "required": ["subtask_name", "handoff_report_path", "unit_test_paths", "review_file"],
}


def _make_config(project_path: Path, plan_file: Path | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.project_path = project_path
    cfg.plan_file = plan_file
    cfg.active_plan_file = None
    return cfg


def _make_tool(type_name: str, config, parameters: dict | None = None) -> SpawnSubagentTool:
    """Create a SpawnSubagentTool with _parameters pre-set (bypasses file I/O)."""
    with patch.object(SpawnSubagentTool, "_load_parameters", return_value=parameters or _FALLBACK_PARAMETERS):
        tool = SpawnSubagentTool(
            type_name=type_name,
            description=f"Test {type_name} tool",
            config=config,
        )
    return tool


# ---------------------------------------------------------------------------
# Schema loading tests
# ---------------------------------------------------------------------------

class TestSchemaLoading:
    def test_worker_schema_from_config_yaml(self, tmp_path):
        """Schema should come from config.yaml 'parameters' key when present."""
        subagent_dir = tmp_path / ".dagi" / "subagents" / "worker"
        subagent_dir.mkdir(parents=True)
        config_yaml = subagent_dir / "config.yaml"
        config_yaml.write_text(
            yaml.dump({"model_tier": "worker", "parameters": WORKER_SCHEMA}),
            encoding="utf-8",
        )

        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(
            type_name="worker",
            description="Worker",
            config=config,
        )
        assert tool._parameters == WORKER_SCHEMA

    def test_fallback_when_parameters_absent(self, tmp_path):
        """Should fall back to task:string schema when config.yaml has no 'parameters'."""
        subagent_dir = tmp_path / ".dagi" / "subagents" / "web_research"
        subagent_dir.mkdir(parents=True)
        config_yaml = subagent_dir / "config.yaml"
        config_yaml.write_text(
            yaml.dump({"model_tier": "worker", "description": "Web research"}),
            encoding="utf-8",
        )

        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(
            type_name="web_research",
            description="Web Research",
            config=config,
        )
        assert tool._parameters == _FALLBACK_PARAMETERS

    def test_fallback_when_config_yaml_missing(self, tmp_path):
        """Should fall back to task:string schema when config.yaml doesn't exist."""
        config = _make_config(tmp_path)
        # Patch _DAGI_ROOT so it also points to tmp_path (no config there either)
        with patch("tools.spawn_subagent._DAGI_ROOT", tmp_path):
            tool = SpawnSubagentTool(
                type_name="nonexistent_type",
                description="Nonexistent",
                config=config,
            )
        assert tool._parameters == _FALLBACK_PARAMETERS

    def test_instance_attr_shadows_class_attr(self, tmp_path):
        """_parameters must be an instance attr so different instances can have different schemas."""
        subagent_dir_worker = tmp_path / ".dagi" / "subagents" / "worker"
        subagent_dir_worker.mkdir(parents=True)
        (subagent_dir_worker / "config.yaml").write_text(
            yaml.dump({"parameters": WORKER_SCHEMA}), encoding="utf-8"
        )

        config = _make_config(tmp_path)
        worker_tool = SpawnSubagentTool(type_name="worker", description="W", config=config)
        fallback_tool = SpawnSubagentTool(type_name="web_research", description="WR", config=config)

        assert worker_tool._parameters == WORKER_SCHEMA
        assert fallback_tool._parameters == _FALLBACK_PARAMETERS
        # Confirm they are distinct objects
        assert worker_tool._parameters is not fallback_tool._parameters


# ---------------------------------------------------------------------------
# Worker context composition tests
# ---------------------------------------------------------------------------

class TestWorkerContext:
    def test_worker_context_excludes_tests_section(self, tmp_path):
        """Worker context must NOT include the #### Tests subsection."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value="Project desc"):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        assert "#### Tests" not in composed
        assert "test_thing.py" not in composed

    def test_worker_context_includes_subtask_content(self, tmp_path):
        """Worker context must include the subtask goal/requirements."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        assert "Implement the feature" in composed
        assert "Requirement A" in composed

    def test_worker_context_includes_global_sections(self, tmp_path):
        """Worker context must include Context and Approach sections."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        assert "Why this change is needed" in composed
        assert "High-level strategy" in composed

    def test_worker_context_includes_project_description(self, tmp_path):
        """Worker context must include agents.md content as Project Description."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value="My project description"):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        assert "## Project Description" in composed
        assert "My project description" in composed

    def test_worker_context_includes_handoff_output(self, tmp_path):
        """Worker context must include the handoff file path in the Output section."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff_report.md",
            )

        assert "## Output" in composed
        assert "/tmp/handoff_report.md" in composed

    def test_worker_context_includes_custom_instructions_when_provided(self, tmp_path):
        """Worker context must include Custom Instructions section when provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
                custom_instructions="Be extra careful with edge cases.",
            )

        assert "## Custom Instructions" in composed
        assert "Be extra careful with edge cases." in composed

    def test_worker_context_omits_custom_instructions_when_absent(self, tmp_path):
        """Worker context must omit Custom Instructions section when not provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        assert "## Custom Instructions" not in composed


# ---------------------------------------------------------------------------
# Review context composition tests
# ---------------------------------------------------------------------------

class TestReviewContext:
    def test_review_context_includes_tests_section(self, tmp_path):
        """Review context MUST include the #### Tests subsection."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_report_path="/tmp/handoff.md",
                unit_test_paths=["tests/test_thing.py"],
                review_file="/tmp/review.md",
            )

        assert "#### Tests" in composed
        assert "test_thing.py" in composed

    def test_review_context_includes_output_files(self, tmp_path):
        """Review context must include Output Files with all paths."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_report_path="/tmp/handoff.md",
                unit_test_paths=["tests/test_a.py", "tests/test_b.py"],
                review_file="/tmp/review.md",
            )

        assert "## Output Files" in composed
        assert "/tmp/handoff.md" in composed
        assert "tests/test_a.py" in composed
        assert "tests/test_b.py" in composed
        assert "/tmp/review.md" in composed

    def test_review_context_includes_project_description(self, tmp_path):
        """Review context must include agents.md as Project Description."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value="Review project desc"):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_report_path="/tmp/handoff.md",
                unit_test_paths=[],
                review_file="/tmp/review.md",
            )

        assert "## Project Description" in composed
        assert "Review project desc" in composed

    def test_review_context_custom_instructions(self, tmp_path):
        """Review context includes Custom Instructions when provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task(
                subtask_name="Do the thing",
                handoff_report_path="/tmp/handoff.md",
                unit_test_paths=[],
                review_file="/tmp/review.md",
                custom_instructions="Focus on security.",
            )

        assert "## Custom Instructions" in composed
        assert "Focus on security." in composed


# ---------------------------------------------------------------------------
# Generic (non-worker/review) subagent tests
# ---------------------------------------------------------------------------

class TestGenericSubagent:
    def test_generic_uses_task_kwarg_directly(self, tmp_path):
        """Generic subagent types pass the task string through without context injection."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools.spawn_subagent._load_agents_md", return_value="ignored"):
            composed = tool._compose_task(task="Search for Python best practices")

        assert composed == "Search for Python best practices"

    def test_generic_returns_empty_string_when_no_task(self, tmp_path):
        """Generic subagent returns empty string when task kwarg is absent."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""):
            composed = tool._compose_task()

        assert composed == ""


# ---------------------------------------------------------------------------
# run() integration tests (mock spawn_terminal_subagent)
# ---------------------------------------------------------------------------

class TestRunMethod:
    def test_run_passes_timeout_none(self, tmp_path):
        """run() must call spawn_terminal_subagent with timeout=None."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""), \
             patch("tools._terminal_subagent.spawn_terminal_subagent", return_value="done") as mock_spawn:
            tool.run(task="Find stuff")

        mock_spawn.assert_called_once()
        _, call_kwargs = mock_spawn.call_args
        assert call_kwargs.get("timeout") is None

    def test_run_returns_result(self, tmp_path):
        """run() returns the string from spawn_terminal_subagent."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""), \
             patch("tools._terminal_subagent.spawn_terminal_subagent", return_value="result text"):
            result = tool.run(task="Do something")

        assert result == "result text"

    def test_run_returns_error_string_on_exception(self, tmp_path):
        """run() catches exceptions and returns an error string."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools.spawn_subagent._load_agents_md", return_value=""), \
             patch("tools._terminal_subagent.spawn_terminal_subagent", side_effect=RuntimeError("boom")):
            result = tool.run(task="Fail")

        assert "[web_research error]" in result
        assert "boom" in result

    def test_run_worker_composes_context(self, tmp_path):
        """run() for worker type composes context and passes it to spawn."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools.spawn_subagent._load_agents_md", return_value="My project"), \
             patch("tools._terminal_subagent.spawn_terminal_subagent", return_value="ok") as mock_spawn:
            tool.run(
                subtask_name="Do the thing",
                handoff_file="/tmp/handoff.md",
            )

        mock_spawn.assert_called_once()
        task_arg = mock_spawn.call_args[1]["task"]
        assert "My project" in task_arg
        assert "#### Tests" not in task_arg
        assert "/tmp/handoff.md" in task_arg
