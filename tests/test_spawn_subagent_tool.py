"""tests/test_spawn_subagent_tool.py — Unit tests for SpawnSubagentTool."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
        "briefing": {"type": "string", "description": "Extra instructions."},
    },
    "required": ["subtask_name"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "subtask_name": {"type": "string", "description": "Name of the subtask being reviewed."},
        "worker_handoff_path": {"type": "string", "description": "Path to the worker's handoff report."},
        "unit_test_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Paths to unit test files.",
        },
        "briefing": {"type": "string", "description": "Extra instructions."},
    },
    "required": ["subtask_name", "worker_handoff_path", "unit_test_paths"],
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
    def test_worker_schema_from_subagent_config_yaml(self, tmp_path):
        """Schema should come from subagent_config.yaml 'parameters' key when present."""
        subagent_dir = tmp_path / ".dagi" / "subagents" / "worker"
        subagent_dir.mkdir(parents=True)
        config_yaml = subagent_dir / "subagent_config.yaml"
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
        """Should fall back to task:string schema when subagent_config.yaml has no 'parameters'."""
        subagent_dir = tmp_path / ".dagi" / "subagents" / "web_research"
        subagent_dir.mkdir(parents=True)
        config_yaml = subagent_dir / "subagent_config.yaml"
        config_yaml.write_text(
            yaml.dump({"model_tier": "worker", "description": "Web research"}),
            encoding="utf-8",
        )

        config = _make_config(tmp_path)
        with patch("tools.spawn_subagent._spawn_subagent._DAGI_ROOT", tmp_path):
            tool = SpawnSubagentTool(
                type_name="web_research",
                description="Web Research",
                config=config,
            )
        assert tool._parameters == _FALLBACK_PARAMETERS

    def test_fallback_when_config_yaml_missing(self, tmp_path):
        """Should fall back to task:string schema when subagent_config.yaml doesn't exist."""
        config = _make_config(tmp_path)
        with patch("tools.spawn_subagent._spawn_subagent._DAGI_ROOT", tmp_path):
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
        (subagent_dir_worker / "subagent_config.yaml").write_text(
            yaml.dump({"parameters": WORKER_SCHEMA}), encoding="utf-8"
        )

        config = _make_config(tmp_path)
        with patch("tools.spawn_subagent._spawn_subagent._DAGI_ROOT", tmp_path):
            worker_tool = SpawnSubagentTool(type_name="worker", description="W", config=config)
            fallback_tool = SpawnSubagentTool(type_name="web_research", description="WR", config=config)

        assert worker_tool._parameters == WORKER_SCHEMA
        assert fallback_tool._parameters == _FALLBACK_PARAMETERS
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
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
        )

        assert "#### Tests" not in composed
        assert "test_thing.py" not in composed

    def test_worker_context_includes_subtask_content(self, tmp_path):
        """Worker context must include the subtask goal/requirements."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
        )

        assert "Implement the feature" in composed
        assert "Requirement A" in composed

    def test_worker_context_excludes_global_sections(self, tmp_path):
        """Worker context must NOT include global plan sections (now in system prompt)."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
        )

        assert "Why this change is needed" not in composed
        assert "High-level strategy" not in composed

    def test_worker_context_excludes_project_description(self, tmp_path):
        """Worker task body must NOT contain agents.md (now in subagent system prompt)."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
        )

        assert "## Project Description" not in composed

    def test_worker_context_includes_handoff_output(self, tmp_path):
        """Worker context must include the handoff file path in the Output section."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff_report.md"),
            subtask_name="Do the thing",
        )

        assert "## Output" in composed
        assert "handoff_report.md" in composed

    def test_worker_context_includes_instructions_when_provided(self, tmp_path):
        """Worker context must include Instructions section when briefing provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
            briefing="Be extra careful with edge cases.",
        )

        assert "## Instructions" in composed
        assert "Be extra careful with edge cases." in composed

    def test_worker_context_omits_instructions_when_absent(self, tmp_path):
        """Worker context must omit Instructions section when not provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            subtask_name="Do the thing",
        )

        assert "## Instructions" not in composed


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
        composed = tool._compose_task(
            handoff_path=Path("/tmp/review.md"),
            subtask_name="Do the thing",
            worker_handoff_path="/tmp/handoff.md",
            unit_test_paths=["tests/test_thing.py"],
        )

        assert "#### Tests" in composed
        assert "test_thing.py" in composed

    def test_review_context_includes_worker_handoff_section(self, tmp_path):
        """Review context must include Worker Handoff section with the path."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/review.md"),
            subtask_name="Do the thing",
            worker_handoff_path="/tmp/handoff.md",
            unit_test_paths=["tests/test_a.py", "tests/test_b.py"],
        )

        assert "## Worker Handoff" in composed
        assert "/tmp/handoff.md" in composed
        assert "tests/test_a.py" in composed
        assert "tests/test_b.py" in composed
        assert "review.md" in composed

    def test_review_context_excludes_project_description(self, tmp_path):
        """Review task body must NOT contain agents.md (now in subagent system prompt)."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/review.md"),
            subtask_name="Do the thing",
            worker_handoff_path="/tmp/handoff.md",
            unit_test_paths=[],
        )

        assert "## Project Description" not in composed

    def test_review_context_briefing(self, tmp_path):
        """Review context includes Instructions section when provided."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("review", config, REVIEW_SCHEMA)
        composed = tool._compose_task(
            handoff_path=Path("/tmp/review.md"),
            subtask_name="Do the thing",
            worker_handoff_path="/tmp/handoff.md",
            unit_test_paths=[],
            briefing="Focus on security.",
        )

        assert "## Instructions" in composed
        assert "Focus on security." in composed


# ---------------------------------------------------------------------------
# Generic (non-worker/review) subagent tests
# ---------------------------------------------------------------------------

class TestGenericSubagent:
    def test_generic_uses_task_kwarg_directly(self, tmp_path):
        """Generic subagent types pass the task string through without context injection."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            task="Search for Python best practices",
        )

        assert composed == "Search for Python best practices"

    def test_generic_returns_empty_string_when_no_task(self, tmp_path):
        """Generic subagent returns empty string when task kwarg is absent."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        composed = tool._compose_task(handoff_path=Path("/tmp/handoff.md"))

        assert composed == ""


# ---------------------------------------------------------------------------
# run() integration tests (mock run_subagent)
# ---------------------------------------------------------------------------

_OK_RESULT = {"status": "ok", "handoff": "/tmp/handoff.md"}
_TIMEOUT_RESULT = {"status": "timeout", "pid": 12345}
_ERROR_RESULT = {"status": "error", "message": "something went wrong"}


class TestRunMethod:
    def test_run_returns_handoff_path_on_success(self, tmp_path):
        """run() returns a message with the handoff path on success."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools._subagent_runner.run_subagent", return_value=_OK_RESULT):
            result = tool.run(task="Find stuff")

        assert "Handoff written to" in result
        assert "/tmp/handoff.md" in result

    def test_run_includes_handoff_content_by_default(self, tmp_path):
        """run() must read and inline the handoff file's content on success — the
        main agent should never have to make a separate `read` call to see it."""
        handoff_file = tmp_path / "worker_abc123.md"
        handoff_file.write_text(
            "# Handoff\n\nImplemented the login endpoint. All tests pass.",
            encoding="utf-8",
        )
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        ok_result = {"status": "ok", "handoff": str(handoff_file)}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(subtask_name="Do the thing")

        assert "Implemented the login endpoint. All tests pass." in result

    def test_run_reports_unreadable_handoff_without_raising(self, tmp_path):
        """If the handoff file can't be read, run() must degrade gracefully,
        not raise — the path is still reported so the agent can investigate."""
        missing_path = tmp_path / "does_not_exist.md"
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        ok_result = {"status": "ok", "handoff": str(missing_path)}

        with patch("tools._subagent_runner.run_subagent", return_value=ok_result):
            result = tool.run(subtask_name="Do the thing")

        assert str(missing_path) in result
        assert "could not read handoff" in result.lower()

    def test_run_returns_timeout_json_on_timeout(self, tmp_path):
        """run() returns a JSON timeout dict when the subagent times out."""
        import json
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools._subagent_runner.run_subagent", return_value=_TIMEOUT_RESULT):
            result = tool.run(task="Slow task")

        parsed = json.loads(result)
        assert parsed["status"] == "timeout"
        assert parsed["pid"] == 12345

    def test_run_returns_error_string_on_error(self, tmp_path):
        """run() returns an error string when the subagent exits without handoff."""
        config = _make_config(tmp_path)
        tool = _make_tool("web_research", config, _FALLBACK_PARAMETERS)

        with patch("tools._subagent_runner.run_subagent", return_value=_ERROR_RESULT):
            result = tool.run(task="Fail")

        assert "[web_research error]" in result
        assert "something went wrong" in result

    def test_run_returns_escalation_content_on_escalated_status(self, tmp_path):
        """run() surfaces the escalation question/context when status is 'escalated'."""
        config = _make_config(tmp_path)
        tool = _make_tool("worker", config, WORKER_SCHEMA)
        escalated_result = {
            "status": "escalated",
            "escalation": "# Escalation\n\n## Question\nWhich lib?\n\n## Context\nAmbiguous.\n",
        }

        with patch("tools._subagent_runner.run_subagent", return_value=escalated_result):
            result = tool.run(subtask_name="Do the thing")

        assert "[worker escalated]" in result
        assert "Which lib?" in result
        assert "Ambiguous." in result

    def test_run_escalated_works_for_review_type_too(self, tmp_path):
        """Escalated branch is not worker-specific — review subagents use it too."""
        config = _make_config(tmp_path)
        tool = _make_tool("review", config, REVIEW_SCHEMA)
        escalated_result = {
            "status": "escalated",
            "escalation": "# Escalation\n\n## Question\nExpected status code?\n\n## Context\nMismatch.\n",
        }

        with patch("tools._subagent_runner.run_subagent", return_value=escalated_result):
            result = tool.run(
                subtask_name="Do the thing",
                worker_handoff_path="/tmp/handoff.md",
                unit_test_paths=["tests/test_thing.py"],
            )

        assert "[review escalated]" in result
        assert "Expected status code?" in result

    def test_run_worker_composes_subtask_context(self, tmp_path):
        """run() for worker type includes subtask content in the task sent to run_subagent."""
        plan_file = tmp_path / "plan.md"
        plan_file.write_text(SAMPLE_PLAN, encoding="utf-8")
        config = _make_config(tmp_path, plan_file=plan_file)

        tool = _make_tool("worker", config, WORKER_SCHEMA)

        with patch("tools._subagent_runner.run_subagent", return_value=_OK_RESULT) as mock_run:
            tool.run(subtask_name="Do the thing")

        mock_run.assert_called_once()
        task_arg = mock_run.call_args.kwargs["task"]
        assert "Implement the feature" in task_arg
        assert "#### Tests" not in task_arg
        assert "## Project Description" not in task_arg
