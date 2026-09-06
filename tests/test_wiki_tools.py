"""Project wiki delegation must not inherit private context or overclaim failed writes."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.subagent_tools import _discover_subagent_tools
from tools.subagent_api import SubagentResult


def make_tool(tmp_path, operation):
    (tmp_path / "wiki").mkdir(exist_ok=True)
    config = SimpleNamespace(project_path=tmp_path, memory_root=tmp_path / "private")
    tools = _discover_subagent_tools(tmp_path, config, None, None, parent_context=object())
    matches = [tool for tool in tools if tool.name == f"wiki_{operation}"]
    assert matches, f"wiki_{operation} must be discoverable"
    return matches[0]


def handoff(operation, outcome="success"):
    sections = {
        "Outcome": outcome,
        "Findings": "Stored evidence.", "Wiki sources": "architecture.md",
        "Conflicts": "None", "Gaps": "None", "Failure details": "None",
    }
    if operation == "add":
        sections = {"Outcome": outcome, "Created/updated paths": "architecture.md",
                    "Change summary": "Recorded supplied evidence.", "Dated conflicts": "None",
                    "Partial writes": "None", "Failure details": "None"}
    return "\n\n".join(f"## {key}\n{value}" for key, value in sections.items())


def result(tmp_path, text, status="ok", **kwargs):
    return SubagentResult(status, text, tmp_path / "handoff.md", None, 7, **kwargs)


@pytest.mark.parametrize("operation", ["query", "add"])
def test_delegates_selected_points_with_explicit_root_and_clean_context(tmp_path, operation):
    tool = make_tool(tmp_path, operation)
    points = "2026-09-05: Approved X; suspected Y remains unverified."
    with patch("tools.subagent_api.run_subagent",
               return_value=result(tmp_path, handoff(operation))) as run:
        text = tool.run(task=points)
    args = run.call_args.kwargs
    assert args["task"] == points
    assert str(tmp_path.resolve() / "wiki") in args["custom_instructions"]
    assert args.get("parent_context") is None
    assert args["project_path"] == tmp_path.resolve()
    assert args["tools"] == ["read", "grep", "find"] + (
        ["write", "edit"] if operation == "add" else [])
    assert "Child protocol" in args["prompt"]
    assert "[wiki-" not in text
    assert handoff(operation) in text


@pytest.mark.parametrize("scope", ["../outside", "/absolute", "C:\\outside", "..\\outside"])
def test_scope_cannot_escape_project_wiki(tmp_path, scope):
    tool = make_tool(tmp_path, "query")
    with patch("tools.subagent_api.run_subagent") as run:
        assert "error" in tool.run("question", scope=scope).lower()
    run.assert_not_called()


@pytest.mark.parametrize("operation", ["query", "add"])
@pytest.mark.parametrize("status,text", [
    ("ok", ""), ("ok", "success"), ("ok_unverified", "complete"),
    ("ok", "## Outcome\nsuccess\n\n## Findings\npartial"),
])
def test_incomplete_or_unverified_handoff_is_error(tmp_path, operation, status, text):
    tool = make_tool(tmp_path, operation)
    with patch("tools.subagent_api.run_subagent",
               return_value=result(tmp_path, text, status)):
        assert "error" in tool.run("question").lower()


@pytest.mark.parametrize("operation", ["query", "add"])
def test_semantic_failure_and_process_diagnostics_reach_main(tmp_path, operation):
    tool = make_tool(tmp_path, operation)
    with patch("tools.subagent_api.run_subagent", return_value=result(
        tmp_path, handoff(operation, "error"), message="permission denied",
        output_tail="diagnostic detail", output_log_path=tmp_path / "process.log",
    )):
        text = tool.run("question")
    assert "error" in text.lower()
    assert "diagnostic detail" in text
    assert "process.log" in text


def test_empty_wiki_no_results_is_valid_but_missing_wiki_is_error(tmp_path):
    tool = make_tool(tmp_path, "query")
    with patch("tools.subagent_api.run_subagent", return_value=result(
        tmp_path, handoff("query", "no_results"))) as run:
        assert "no_results" in tool.run("question")
        (tmp_path / "wiki").rmdir()
        assert "/init" in tool.run("question")
    assert run.call_count == 1


@pytest.mark.parametrize("status", ["timeout", "error"])
def test_process_failures_preserve_actionable_diagnostics_without_retry(tmp_path, status):
    tool = make_tool(tmp_path, "add")
    with patch("tools.subagent_api.run_subagent", return_value=result(
        tmp_path, "", status, message="provider unavailable", exit_code=1,
        output_tail="request failed", output_log_path=tmp_path / "output.log",
    )) as run:
        text = tool.run("approved decision")
    assert "error" in text
    assert status in text
    assert "provider unavailable" in text
    assert "request failed" in text
    assert "output.log" in text
    assert "pid: 7" in text
    assert run.call_count == 1


@pytest.mark.parametrize("replacement", [
    ("## Failure details\nNone", "## Failure details\nDisk full"),
    ("## Partial writes\nNone", "## Partial writes\nWrote one page only"),
    ("## Change summary\nRecorded supplied evidence.", "## Change summary\n"),
])
def test_add_cannot_claim_completion_with_failed_or_empty_sections(tmp_path, replacement):
    tool = make_tool(tmp_path, "add")
    text = handoff("add").replace(*replacement)
    with patch("tools.subagent_api.run_subagent", return_value=result(tmp_path, text)):
        assert "error" in tool.run("approved decision")
