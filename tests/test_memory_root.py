"""Central memory store resolution and the per-turn [MEMORY] pointer."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import agent._loop_config as lc
from agent._loop_config import resolve_memory_root
from agent._loop_helpers import _build_memory_context, project_slug


def test_resolve_memory_root_defaults_and_overrides(tmp_path):
    # lc.DEFAULT_MEMORY_ROOT is patched by the autouse conftest fixture; read it via the module.
    assert resolve_memory_root(None) == lc.DEFAULT_MEMORY_ROOT.resolve()
    assert resolve_memory_root(tmp_path) == tmp_path.resolve()


def test_resolve_memory_root_makes_relative_absolute():
    assert resolve_memory_root(Path("rel")).is_absolute()


def test_default_memory_root_constant_is_the_vault():
    import inspect  # the value is patched in tests, so pin the source constant instead
    assert r'Path(r"G:\My Drive\black_grimoire")' in inspect.getsource(lc)


def test_project_slug():
    assert project_slug(Path("C:/x/Driverless_AGI")) == "driverless-agi"
    assert project_slug(Path("/x/My Proj.v2_")) == "my-proj-v2"
    assert project_slug(Path("/x/hedgefundie")) == "hedgefundie"
    assert project_slug(Path("/x/___")) == "project"


def test_memory_context_missing_wiki_returns_none(tmp_path):
    assert _build_memory_context(tmp_path, tmp_path / "Proj") is None


def test_memory_context_names_store_and_project(tmp_path):
    (tmp_path / "wiki").mkdir()
    text = _build_memory_context(tmp_path, Path("/x/Driverless_AGI"))
    assert text.startswith("[MEMORY]\n") and text.endswith("[END MEMORY]")
    assert str(tmp_path / "wiki") in text
    assert "projects/driverless-agi/" in text
    assert "memory-query" in text and "memory-add" in text


def test_agent_loop_uses_resolved_default_when_unset(tmp_path):
    from agent.loop import AgentConfig, AgentLoop
    from agent.registry import ToolRegistry

    with patch("openai.OpenAI"):
        loop = AgentLoop(
            config=AgentConfig(api_key="test", project_path=tmp_path, system_prompt="x"),
            _registry=ToolRegistry(),
            _system_prompt_override="x",
        )
    assert loop._effective_memory_root == lc.DEFAULT_MEMORY_ROOT.resolve()


def test_subagent_memory_root_fallback_uses_default(monkeypatch, tmp_path):
    import agent.subagent_tools as st
    monkeypatch.setattr(st, "_load_subagent_config",
                        lambda *a, **k: {"root": "memory_root", "tools": ["read"]})
    config = MagicMock(sandbox_mode=False)  # only attribute read (subagent_tools.py:185)
    reg = st.build_subagent_registry("memory-refresh", config, tmp_path, memory_root=None)
    expected = lc.DEFAULT_MEMORY_ROOT.resolve()
    read_tool = reg.get("read")
    assert read_tool.cwd == expected                # today: <project>/<legacy dir> → fails first
    assert read_tool.allowed_roots == [expected]
