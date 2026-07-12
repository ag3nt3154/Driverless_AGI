"""tests/test_escalate_issue.py — Unit tests for tools/escalate_issue.py."""
from __future__ import annotations

from pathlib import Path

from tools.escalate_issue import EscalateIssueTool


class TestEscalateIssueTool:
    def test_writes_escalation_file_next_to_handoff(self, tmp_path):
        handoff_path = tmp_path / "worker_ab12cd34.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="Which auth library?", context="Plan doesn't specify.")

        escalation_path = tmp_path / "worker_ab12cd34_escalation.md"
        assert escalation_path.exists()

    def test_escalation_file_contains_question_and_context(self, tmp_path):
        handoff_path = tmp_path / "review_9f8e7d6c.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="Is 200 or 201 expected?", context="Test asserts 200, criteria says 201.")

        content = (tmp_path / "review_9f8e7d6c_escalation.md").read_text(encoding="utf-8")
        assert "Is 200 or 201 expected?" in content
        assert "Test asserts 200, criteria says 201." in content

    def test_creates_parent_dir_if_missing(self, tmp_path):
        handoff_path = tmp_path / "nested" / "dir" / "worker_1.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        tool.run(question="q", context="c")

        assert (tmp_path / "nested" / "dir" / "worker_1_escalation.md").exists()

    def test_run_returns_end_turn_instruction(self, tmp_path):
        handoff_path = tmp_path / "worker_1.md"
        tool = EscalateIssueTool(handoff_path=handoff_path)

        result = tool.run(question="q", context="c")

        assert "end your turn" in result.lower()

    def test_schema_requires_question_and_context(self, tmp_path):
        tool = EscalateIssueTool(handoff_path=tmp_path / "worker_1.md")

        assert tool._parameters["required"] == ["question", "context"]
        assert tool.name == "escalate_issue"
