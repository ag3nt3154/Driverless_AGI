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
TYPED_SUBAGENT_NAMES = {
    "explore_files",
    "memory-add",
    "memory-query",
    "memory-refresh",
    "read-large-text",
    "review",
    "web_research",
    "worker",
    "wtf",
}


def _registered_subagent_config_paths() -> list[Path]:
    """Return subagent_config.yaml paths for dirs that also have a prompt.md."""
    configs = []
    for subagent_dir in sorted(SUBAGENTS_DIR.iterdir()):
        if not subagent_dir.is_dir():
            continue
        config_path = subagent_dir / "subagent_config.yaml"
        prompt_path = subagent_dir / "prompt.md"
        if config_path.exists() and prompt_path.exists():
            configs.append(config_path)
    return configs


def test_all_registered_subagents_are_found():
    """Sanity check that the discovery glob matches the expected registered set."""
    names = {p.parent.name for p in _registered_subagent_config_paths()}
    assert names == TYPED_SUBAGENT_NAMES | {"compact"}


def test_config_schema_has_required_keys():
    """Each subagent config must have the required keys and no deprecated ones.

    Required keys: tools, model_tier, default_handoff_spec, agents_md.
    Forbidden keys: parameters, description (moved to main.py in Task 3).
    """
    for config_path in _registered_subagent_config_paths():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        assert "tools" in data, f"{config_path}: missing 'tools'"
        assert "model_tier" in data, f"{config_path}: missing 'model_tier'"
        assert (
            "default_handoff_spec" in data
        ), f"{config_path}: missing 'default_handoff_spec'"
        assert "agents_md" in data, f"{config_path}: missing 'agents_md'"
        assert (
            "parameters" not in data
        ), f"{config_path}: 'parameters' should be removed"
        assert "description" not in data, f"{config_path}: 'description' should be removed"


def test_subagent_tool_allowlists_never_expose_adjust_emotion():
    """Emotion adjustment is a main-agent affordance, not a child registry surface."""
    for config_path in _registered_subagent_config_paths():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        assert "adjust_emotion" not in data["tools"], (
            f"{config_path}: subagents must not expose adjust_emotion"
        )


def test_wtf_preset_is_read_only_and_requires_structured_sections():
    """The diagnostic preset must not be able to apply its suggested fix."""
    config_path = SUBAGENTS_DIR / "wtf" / "subagent_config.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert data["model_tier"] == "worker"
    assert data["tools"] == ["read", "grep", "find"]
    assert data["required_sections"] == ["Description", "Error Report", "Suggested Fix"]
    assert data["agents_md"] == ["cwd"]
