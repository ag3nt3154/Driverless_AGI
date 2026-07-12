"""tests/test_escalate_issue_wiring.py — escalate_issue reaches subagent registries."""
from __future__ import annotations

from pathlib import Path

import yaml

from agent.tools import build_subagent_registry
from tools.escalate_issue import EscalateIssueTool


def _make_config(tmp_path: Path):
    from agent.loop import AgentConfig
    return AgentConfig(model="test-model", api_key="test-key", project_path=tmp_path)


class TestEscalateIssueWiring:
    def test_worker_registry_includes_escalate_issue_when_handoff_path_given(self, tmp_path):
        subagent_dir = tmp_path / ".dagi" / "subagents" / "worker"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "subagent_config.yaml").write_text(
            yaml.dump({"model_tier": "worker", "tools": ["read", "escalate_issue"]}),
            encoding="utf-8",
        )
        config = _make_config(tmp_path)
        handoff_path = tmp_path / "worker_ab12cd34.md"

        registry = build_subagent_registry(
            subagent_type="worker",
            config=config,
            project_path=tmp_path,
            handoff_path=handoff_path,
        )

        tool = registry._tools.get("escalate_issue")
        assert isinstance(tool, EscalateIssueTool)
        assert tool._handoff_path == handoff_path

    def test_registry_omits_escalate_issue_when_not_in_tools_list(self, tmp_path):
        subagent_dir = tmp_path / ".dagi" / "subagents" / "explore_files"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "subagent_config.yaml").write_text(
            yaml.dump({"model_tier": "worker", "tools": ["read"]}),
            encoding="utf-8",
        )
        config = _make_config(tmp_path)

        registry = build_subagent_registry(
            subagent_type="explore_files",
            config=config,
            project_path=tmp_path,
            handoff_path=tmp_path / "explore_1.md",
        )

        assert registry._tools.get("escalate_issue") is None
