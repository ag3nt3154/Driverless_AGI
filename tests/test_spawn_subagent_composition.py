"""tests/test_spawn_subagent_composition.py — Universal briefing/handoff_spec schema coverage.

Covers Stage 2 Task 9: every registered subagent type (the .dagi/subagents/*
directories with both prompt.md and subagent_config.yaml) must expose optional
`briefing` and `handoff_spec` string properties in its parameters schema, plus
a non-empty top-level `default_handoff_spec` key. The dynamic spawn_cli_subagent
path and the _FALLBACK_PARAMETERS fallback get schema parity too.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent import DAGI_ROOT
from tools.cli_subagent import SpawnCliSubagentTool
from tools.spawn_subagent import _FALLBACK_PARAMETERS

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
