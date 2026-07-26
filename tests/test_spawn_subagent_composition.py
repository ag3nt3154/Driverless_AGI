"""tests/test_spawn_subagent_composition.py — Universal briefing/handoff_spec schema coverage.

Covers Stage 2 Task 9: every registered subagent type (the .dagi/subagents/*
directories with both prompt.md and subagent_config.yaml) must expose optional
`briefing` and `handoff_spec` string properties in its parameters schema, plus
a non-empty top-level `default_handoff_spec` key. The dynamic spawn_cli_subagent
path and the _FALLBACK_PARAMETERS fallback get schema parity too.

Also covers Stage 2 Task 10: those schema properties are now actually wired
into the composed task text via a universal envelope (`## Instructions` /
`## Output`), for every registered type plus the dynamic spawn_cli_subagent
path.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from agent import DAGI_ROOT
from tools.cli_subagent import SpawnCliSubagentTool
from tools.spawn_subagent import SpawnSubagentTool, _FALLBACK_PARAMETERS

SUBAGENTS_DIR = DAGI_ROOT / ".dagi" / "subagents"


def _registered_subagent_dirs() -> list[Path]:
    dirs = []
    for path in sorted(SUBAGENTS_DIR.iterdir()):
        if not path.is_dir():
            continue
        if (path / "prompt.md").is_file() and (path / "subagent_config.yaml").is_file():
            dirs.append(path)
    return dirs


REGISTERED_DIRS = _registered_subagent_dirs()
REGISTERED_IDS = [d.name for d in REGISTERED_DIRS]


def _assert_optional_string_property(properties: dict, required: list, name: str) -> None:
    assert name in properties, f"missing '{name}' property"
    assert properties[name].get("type") == "string", f"'{name}' must be type string"
    assert name not in required, f"'{name}' must be optional, not required"


@pytest.mark.parametrize("subagent_dir", REGISTERED_DIRS, ids=REGISTERED_IDS)
def test_subagent_config_exposes_universal_params(subagent_dir: Path) -> None:
    data = yaml.safe_load((subagent_dir / "subagent_config.yaml").read_text(encoding="utf-8"))

    parameters = data.get("parameters")
    assert parameters, f"{subagent_dir.name}: missing parameters block"
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    _assert_optional_string_property(properties, required, "briefing")
    _assert_optional_string_property(properties, required, "handoff_spec")

    default_handoff_spec = data.get("default_handoff_spec")
    assert isinstance(default_handoff_spec, str) and default_handoff_spec.strip(), (
        f"{subagent_dir.name}: missing non-empty default_handoff_spec"
    )


def test_all_seven_registered_types_present() -> None:
    assert set(REGISTERED_IDS) == {
        "worker",
        "review",
        "explore_files",
        "web_research",
        "memory-query",
        "memory-add",
        "document-reader",
    }


def test_cli_subagent_tool_exposes_briefing_and_handoff_spec() -> None:
    properties = SpawnCliSubagentTool._parameters["properties"]
    required = SpawnCliSubagentTool._parameters.get("required", [])

    _assert_optional_string_property(properties, required, "briefing")
    _assert_optional_string_property(properties, required, "handoff_spec")


def test_fallback_parameters_expose_briefing_and_handoff_spec() -> None:
    properties = _FALLBACK_PARAMETERS["properties"]
    required = _FALLBACK_PARAMETERS.get("required", [])

    _assert_optional_string_property(properties, required, "briefing")
    _assert_optional_string_property(properties, required, "handoff_spec")


# ---------------------------------------------------------------------------
# Task 10: envelope wiring — briefing/handoff_spec actually land in the
# composed task text sent to the model.
# ---------------------------------------------------------------------------


def _default_handoff_spec_for(subagent_dir: Path) -> str:
    data = yaml.safe_load((subagent_dir / "subagent_config.yaml").read_text(encoding="utf-8"))
    return data["default_handoff_spec"]


def _make_config(tmp_path: Path) -> MagicMock:
    """A config whose project_path has no local .dagi override, so
    SpawnSubagentTool falls back to the real repo's `.dagi/subagents/*`."""
    cfg = MagicMock()
    cfg.project_path = tmp_path
    cfg.plan_file = None
    cfg.active_plan_file = None
    return cfg


_EXTRA_KWARGS = {
    "worker": {"subtask_name": "Do the thing"},
    "review": {
        "subtask_name": "Do the thing",
        "worker_handoff_path": "/tmp/worker_handoff.md",
        "unit_test_paths": ["tests/test_thing.py"],
    },
}


@pytest.mark.parametrize("subagent_dir", REGISTERED_DIRS, ids=REGISTERED_IDS)
class TestEnvelopeWiring:
    def test_output_is_last_section_and_uses_default_when_omitted(
        self, subagent_dir: Path, tmp_path
    ) -> None:
        type_name = subagent_dir.name
        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(type_name=type_name, description="t", config=config)

        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            task="do something",
            **_EXTRA_KWARGS.get(type_name, {}),
        )

        assert composed.split("---")[-1].strip().startswith("## Output")
        assert _default_handoff_spec_for(subagent_dir) in composed

    def test_output_uses_supplied_handoff_spec_instead_of_default(
        self, subagent_dir: Path, tmp_path
    ) -> None:
        type_name = subagent_dir.name
        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(type_name=type_name, description="t", config=config)

        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            task="do something",
            handoff_spec="Write a haiku about the outcome.",
            **_EXTRA_KWARGS.get(type_name, {}),
        )

        assert "Write a haiku about the outcome." in composed
        assert _default_handoff_spec_for(subagent_dir) not in composed

    def test_no_instructions_heading_when_briefing_omitted(
        self, subagent_dir: Path, tmp_path
    ) -> None:
        type_name = subagent_dir.name
        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(type_name=type_name, description="t", config=config)

        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            task="do something",
            **_EXTRA_KWARGS.get(type_name, {}),
        )

        assert "## Instructions" not in composed

    def test_instructions_heading_when_briefing_given(
        self, subagent_dir: Path, tmp_path
    ) -> None:
        type_name = subagent_dir.name
        config = _make_config(tmp_path)
        tool = SpawnSubagentTool(type_name=type_name, description="t", config=config)

        composed = tool._compose_task(
            handoff_path=Path("/tmp/handoff.md"),
            task="do something",
            briefing="Watch out for edge cases.",
            **_EXTRA_KWARGS.get(type_name, {}),
        )

        assert "## Instructions\nWatch out for edge cases." in composed
        assert composed.index("## Instructions") < composed.index("## Output")


def test_worker_still_receives_plan_subtask(tmp_path) -> None:
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(
        "## Subtasks\n\n### Subtask 1: Do the thing\n**Goal:** Implement it.\n",
        encoding="utf-8",
    )
    config = _make_config(tmp_path)
    config.plan_file = plan_file
    tool = SpawnSubagentTool(type_name="worker", description="t", config=config)

    composed = tool._compose_task(
        handoff_path=Path("/tmp/handoff.md"), subtask_name="Do the thing"
    )

    assert "## Subtask" in composed
    assert "Implement it." in composed


def test_review_still_receives_worker_handoff_and_unit_tests(tmp_path) -> None:
    config = _make_config(tmp_path)
    tool = SpawnSubagentTool(type_name="review", description="t", config=config)

    composed = tool._compose_task(
        handoff_path=Path("/tmp/review.md"),
        subtask_name="Do the thing",
        worker_handoff_path="/tmp/worker_handoff.md",
        unit_test_paths=["tests/test_a.py", "tests/test_b.py"],
    )

    assert "## Worker Handoff" in composed
    assert "/tmp/worker_handoff.md" in composed
    assert "tests/test_a.py" in composed
    assert "tests/test_b.py" in composed


class TestCliSubagentEnvelope:
    def test_no_instructions_when_briefing_omitted(self, tmp_path) -> None:
        from unittest.mock import patch

        tool = SpawnCliSubagentTool(project_path=tmp_path)
        with patch("tools._subagent_runner.run_subagent") as mock_run:
            mock_run.return_value = {"status": "ok", "handoff": str(tmp_path / "h.md")}
            (tmp_path / "h.md").write_text("done", encoding="utf-8")
            tool.run(system_prompt="You are a helper.", task="Do the thing")

        task_arg = mock_run.call_args.kwargs["task"]
        assert "## Instructions" not in task_arg
        assert "## Output" in task_arg

    def test_instructions_when_briefing_given(self, tmp_path) -> None:
        from unittest.mock import patch

        tool = SpawnCliSubagentTool(project_path=tmp_path)
        with patch("tools._subagent_runner.run_subagent") as mock_run:
            mock_run.return_value = {"status": "ok", "handoff": str(tmp_path / "h.md")}
            (tmp_path / "h.md").write_text("done", encoding="utf-8")
            tool.run(
                system_prompt="You are a helper.",
                task="Do the thing",
                briefing="Be careful.",
            )

        task_arg = mock_run.call_args.kwargs["task"]
        assert "## Instructions\nBe careful." in task_arg

    def test_uses_hardcoded_fallback_handoff_spec_when_omitted(self, tmp_path) -> None:
        from unittest.mock import patch

        from tools._task_envelope import FALLBACK_HANDOFF_SPEC

        tool = SpawnCliSubagentTool(project_path=tmp_path)
        with patch("tools._subagent_runner.run_subagent") as mock_run:
            mock_run.return_value = {"status": "ok", "handoff": str(tmp_path / "h.md")}
            (tmp_path / "h.md").write_text("done", encoding="utf-8")
            tool.run(system_prompt="You are a helper.", task="Do the thing")

        task_arg = mock_run.call_args.kwargs["task"]
        assert FALLBACK_HANDOFF_SPEC in task_arg

    def test_uses_supplied_handoff_spec(self, tmp_path) -> None:
        from unittest.mock import patch

        tool = SpawnCliSubagentTool(project_path=tmp_path)
        with patch("tools._subagent_runner.run_subagent") as mock_run:
            mock_run.return_value = {"status": "ok", "handoff": str(tmp_path / "h.md")}
            (tmp_path / "h.md").write_text("done", encoding="utf-8")
            tool.run(
                system_prompt="You are a helper.",
                task="Do the thing",
                handoff_spec="Report in one sentence.",
            )

        task_arg = mock_run.call_args.kwargs["task"]
        assert "Report in one sentence." in task_arg
