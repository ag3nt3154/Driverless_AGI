"""tests/test_subagent_configs.py — Guard rails on registered subagent_config.yaml files.

Stage 1 gate: subagents must never be given a path-like parameter (e.g.
`handoff_file`) in their schema. The `write_handoff` tool is auto-injected with
the path baked in at construction, so the model should never see or choose a
path — it should only ever call `write_handoff(content=...)`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBAGENTS_DIR = REPO_ROOT / ".dagi" / "subagents"

# Parameter names that would indicate a path is being handed to the model.
PATH_LIKE_PARAM_NAMES = {"handoff_file", "handoff_path", "output_file", "output_path"}


def _registered_subagent_config_paths() -> list[Path]:
    """Return subagent_config.yaml paths for dirs that also have a prompt.md.

    Dirs with only a prompt.md (e.g. plan, cli) are vestigial/unregistered and
    excluded — they are out of scope.
    """
    configs = []
    for subagent_dir in sorted(SUBAGENTS_DIR.iterdir()):
        if not subagent_dir.is_dir():
            continue
        config_path = subagent_dir / "subagent_config.yaml"
        prompt_path = subagent_dir / "prompt.md"
        if config_path.exists() and prompt_path.exists():
            configs.append(config_path)
    return configs


def test_at_least_the_seven_registered_subagents_are_found():
    """Sanity check that the discovery glob matches the expected registered set."""
    names = {p.parent.name for p in _registered_subagent_config_paths()}
    assert names == {
        "web_research",
        "memory-query",
        "memory-add",
        "worker",
        "review",
        "document-reader",
        "explore_files",
    }


def test_no_registered_subagent_schema_exposes_a_path_like_parameter():
    """No subagent_config.yaml should declare handoff_file (or similar) as a parameter.

    The write_handoff tool's path is baked in at construction and auto-injected
    by the parent — the model must never be told a path to write to.
    """
    for config_path in _registered_subagent_config_paths():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        properties = (data.get("parameters") or {}).get("properties") or {}
        required = (data.get("parameters") or {}).get("required") or []

        offending_properties = PATH_LIKE_PARAM_NAMES & set(properties.keys())
        offending_required = PATH_LIKE_PARAM_NAMES & set(required)

        assert not offending_properties, (
            f"{config_path} declares path-like parameter(s) {offending_properties} "
            "in 'properties' — write_handoff's path is baked in, remove it."
        )
        assert not offending_required, (
            f"{config_path} declares path-like parameter(s) {offending_required} "
            "in 'required' — write_handoff's path is baked in, remove it."
        )
