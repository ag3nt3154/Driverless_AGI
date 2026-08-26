"""Verify system-prompt assembly works from the extracted module.

Why this matters: _assemble_system_string is the single source of truth for
what the model sees. The extraction must produce byte-identical prompts —
these tests pin the placeholder passthrough and the tools/skills formatting.
"""
from agent._system_prompt import (
    _SafeDict,
    _format_tools_and_skills,
    assemble_system_string,
    build_preamble,
)


def test_safe_dict_missing_key_passthrough():
    d = _SafeDict(name="test")
    result = "{name} and {missing}".format_map(d)
    assert result == "test and {missing}"


def test_safe_dict_known_key_substitutes():
    d = _SafeDict(name="test")
    assert "{name}".format_map(d) == "test"


def test_format_tools_and_skills_without_skills():
    from unittest.mock import MagicMock

    reg = MagicMock()
    reg.list_tools.return_value = [("read", "Read files")]
    result = _format_tools_and_skills(reg, [])
    assert "## Available Tools" in result
    assert "**read**: Read files" in result
    assert "## Available Skills" not in result


def test_format_tools_and_skills_with_skills():
    from unittest.mock import MagicMock

    reg = MagicMock()
    reg.list_tools.return_value = [("read", "Read files")]
    skill = MagicMock()
    skill.name = "my-skill"
    skill.description = "does things"
    skill.triggers = ["go"]
    result = _format_tools_and_skills(reg, [skill])
    assert "**my-skill** — does things" in result
    assert 'Triggers: "go"' in result


def test_build_preamble_empty_config(tmp_path):
    from agent._loop_config import AgentConfig

    cfg = AgentConfig(project_path=tmp_path)
    assert build_preamble(cfg, tmp_path) == ""


def test_assemble_system_string_appends_project_root(tmp_path):
    from unittest.mock import MagicMock

    from agent._loop_config import AgentConfig

    cfg = AgentConfig(project_path=tmp_path, system_prompt="PROMPT {cwd}")
    reg = MagicMock()
    reg.list_tools.return_value = []
    system, parts = assemble_system_string(
        config=cfg,
        registry=reg,
        skills=[],
        effective_memory_root=tmp_path / "mem",
        system_prompt_override=None,
        dagi_root=tmp_path,
    )
    assert f"Project root: {tmp_path}" in system
    # The final part is always the assembled prompt itself.
    assert parts[-1]["label"] == "System Prompt"


def test_assemble_system_string_override_wins(tmp_path):
    from unittest.mock import MagicMock

    from agent._loop_config import AgentConfig

    cfg = AgentConfig(project_path=tmp_path, system_prompt="PROMPT {cwd}")
    reg = MagicMock()
    reg.list_tools.return_value = []
    system, _parts = assemble_system_string(
        config=cfg,
        registry=reg,
        skills=[],
        effective_memory_root=tmp_path / "mem",
        system_prompt_override="OVERRIDE WINS",
        dagi_root=tmp_path,
    )
    assert system == "OVERRIDE WINS"
