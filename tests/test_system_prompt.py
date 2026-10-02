"""Verify system-prompt assembly works from the extracted module.

Why this matters: _assemble_system_string is the single source of truth for
what the model sees. The extraction must produce byte-identical prompts —
these tests pin the placeholder passthrough and the tools/skills formatting.
"""
from agent._system_prompt import (
    _SafeDict,
    _format_tools_and_skills,
    assemble_system_string,
    prompt_sections,
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


def test_prompt_sections_empty_config(tmp_path):
    """No preamble, no soul, no AGENTS.md — nothing to inject."""
    from agent._loop_config import AgentConfig

    cfg = AgentConfig(project_path=tmp_path)
    assert prompt_sections(cfg, tmp_path) == []


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


def _assemble(tmp_path, dagi_root, project_path, prompt="PROMPT"):
    from unittest.mock import MagicMock

    from agent._loop_config import AgentConfig

    cfg = AgentConfig(project_path=project_path, system_prompt=prompt)
    reg = MagicMock()
    reg.list_tools.return_value = []
    return assemble_system_string(
        config=cfg,
        registry=reg,
        skills=[],
        effective_memory_root=tmp_path / "mem",
        system_prompt_override=None,
        dagi_root=dagi_root,
    )


def test_agents_md_injected_once_when_dagi_root_is_project_path(tmp_path):
    """Regression: self-hosting dagi (dagi_root == project_path) injected AGENTS.md twice.

    Both roots pointed at the same file, so the loop appended it twice: the model saw
    the same ~4.3 KB twice, that duplicate was persisted in every request/header event,
    and `system_parts` listed it twice. A prompt that repeats one file is wrong whichever
    way the caller spells the path.
    """
    (tmp_path / "AGENTS.md").write_text("# AGENTS.md\nONLY-ONE-COPY\n", encoding="utf-8")

    system, parts = _assemble(tmp_path, tmp_path, tmp_path)

    assert system.count("ONLY-ONE-COPY") == 1
    agents_parts = [p for p in parts if p["label"].startswith("AGENTS.md")]
    assert len(agents_parts) == 1


def test_agents_md_kept_for_both_roots_when_they_differ(tmp_path):
    """Dedup must not collapse genuinely different files: a real project needs both.

    Guards against over-correction — the fix is about the same file, never about
    dropping the project's own conventions when the roots are distinct.
    """
    dagi_root = tmp_path / "dagi"
    project = tmp_path / "proj"
    dagi_root.mkdir()
    project.mkdir()
    (dagi_root / "AGENTS.md").write_text("DAGI-CONVENTIONS\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("PROJECT-CONVENTIONS\n", encoding="utf-8")

    system, parts = _assemble(tmp_path, dagi_root, project)

    assert system.count("DAGI-CONVENTIONS") == 1
    assert system.count("PROJECT-CONVENTIONS") == 1
    assert system.index("DAGI-CONVENTIONS") < system.index("PROJECT-CONVENTIONS")
    labels = [p["label"] for p in parts if p["label"].startswith("AGENTS.md")]
    assert labels == ["AGENTS.md (dagi)", "AGENTS.md (project)"]


def test_system_parts_mirror_the_injected_sections(tmp_path):
    """Invariant: everything injected into the prompt is visible in system_parts.

    The prompt string and the metadata list used to be built independently and had already
    drifted — the benchmark preamble reached the model but never appeared in the parts.
    Re-splitting them is the regression this guards against.
    """
    from unittest.mock import MagicMock

    from agent._loop_config import AgentConfig

    (tmp_path / "AGENTS.md").write_text("AGENTS-TEXT\n", encoding="utf-8")
    cfg = AgentConfig(
        project_path=tmp_path,
        system_prompt="PROMPT",
        system_prompt_preamble="BENCH-PREAMBLE",
    )
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

    assert [p["label"] for p in parts] == ["Preamble", "AGENTS.md (dagi)", "System Prompt"]
    for part in parts:
        assert part["content"] in system


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
