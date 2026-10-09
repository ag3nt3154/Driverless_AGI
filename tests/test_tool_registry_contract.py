"""tests/test_tool_registry_contract.py — create_tool_registry ordering contract.

ToolRegistry is an insertion-ordered dict, so registration order is the order
of the tool schemas sent to the provider. Reordering silently changes every
request's tool block and invalidates the warm prompt-cache prefix, so these
tests pin exact ordered name lists rather than sets.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent import DAGI_ROOT
from agent.base_tool import BaseTool
from agent.loop import AgentCallbacks
from agent.tools import create_tool_registry


class _FakeTool(BaseTool):
    description = "fake"
    _parameters = {"type": "object", "properties": {}}

    def __init__(self, name: str):
        self.name = name

    def run(self, **_kwargs) -> str:
        return ""


def _config(project: Path, **overrides) -> MagicMock:
    cfg = MagicMock()
    cfg.tools = None
    cfg.disabled_tools = []
    cfg.sandbox_mode = False
    cfg.code_mode = False  # a bare MagicMock attribute is truthy
    cfg.advanced_config = None
    cfg.worker_config = None
    cfg.autonomous = False
    cfg.ask_user_timeout = None
    cfg.project_path = project
    cfg.services = {}
    cfg.reserve_tokens = 0
    cfg.truncate_edge_chars = 100
    cfg.image_input_max_image_bytes = None
    cfg.image_input_max_pixels = None
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _names(config, tmp_path, callbacks=None, skill_roots=None) -> list[str]:
    discovered = [_FakeTool("spawn_alpha"), _FakeTool("spawn_beta")]
    with patch("agent.tools._discover_subagent_tools", return_value=discovered), \
         patch("agent.tools._load_project_tools", return_value=[_FakeTool("project_x")]):
        reg = create_tool_registry(
            cwd=tmp_path, config=config, callbacks=callbacks, skill_roots=skill_roots,
        )
    return [name for name, _ in reg.list_tools()]


_FILE_TOOLS = ["read", "grep", "find", "write", "edit", "copy", "bash"]
_SESSION_TOOLS = [
    "set_active_plan", "check_active_plan", "update_task_status", "ask_user",
]


def test_no_config_fallback_order(tmp_path):
    names = _names(None, tmp_path, skill_roots=[tmp_path])

    assert names == _FILE_TOOLS + _SESSION_TOOLS + [
        "reload_skills", "read_notepad", "web_search", "web_fetch", "skill", "write_handoff",
    ]


def test_full_interactive_config_order(tmp_path):
    config = _config(tmp_path, advanced_config=object())

    names = _names(config, tmp_path, callbacks=AgentCallbacks(), skill_roots=[tmp_path])

    assert names == _FILE_TOOLS + _SESSION_TOOLS + [
        "switch_model", "reload_skills", "show_file", "read_notepad",
        "spawn_alpha", "spawn_beta", "extend_subagent_timeout", "project_x",
        "skill", "run_skill_script",
        "schedule_task", "list_scheduled_tasks", "remove_scheduled_task",
        "write_handoff",
    ]


def test_autonomous_without_callbacks_hides_interactive_tools(tmp_path):
    names = _names(_config(tmp_path, autonomous=True), tmp_path)

    assert names == _FILE_TOOLS + _SESSION_TOOLS + [
        "reload_skills", "read_notepad",
        "spawn_alpha", "spawn_beta", "extend_subagent_timeout", "project_x",
        "write_handoff",
    ]


def test_allow_and_deny_lists_keep_write_handoff(tmp_path):
    config = _config(tmp_path, tools=["read", "grep"], disabled_tools=["grep"])

    assert _names(config, tmp_path) == ["read", "write_handoff"]


def test_sandbox_mode_lifts_file_roots(tmp_path):
    with patch("agent.tools._discover_subagent_tools", return_value=[]):
        sandboxed = create_tool_registry(cwd=tmp_path, config=_config(tmp_path, sandbox_mode=True))
        default = create_tool_registry(cwd=tmp_path, config=_config(tmp_path))

    assert sandboxed.get("grep").allowed_roots is None
    assert default.get("grep").allowed_roots == [DAGI_ROOT, tmp_path]


def test_extra_bash_and_partial_frontend_callbacks(tmp_path):
    extra_roots = [tmp_path / "only"]
    callbacks = AgentCallbacks(on_show_file=None)
    with patch("agent.tools._discover_subagent_tools", return_value=[]), \
         patch("agent.tools._load_project_tools", return_value=[]):
        reg = create_tool_registry(
            cwd=tmp_path, allowed_roots=extra_roots, callbacks=callbacks,
            config=_config(tmp_path, autonomous=True), bash_tool=_FakeTool("bash_session"),
        )

    names = [name for name, _ in reg.list_tools()]
    assert names == _FILE_TOOLS + ["bash_session"] + _SESSION_TOOLS + [
        "reload_skills", "read_notepad", "extend_subagent_timeout", "write_handoff",
    ]
    assert reg.get("grep").allowed_roots == extra_roots


def test_code_mode_inserts_code_after_bash_and_nowhere_else(tmp_path):
    kwargs = dict(callbacks=AgentCallbacks(), skill_roots=[tmp_path])
    off = _names(_config(tmp_path), tmp_path, **kwargs)
    on = _names(_config(tmp_path, code_mode=True), tmp_path, **kwargs)

    assert on == _FILE_TOOLS + ["code"] + off[len(_FILE_TOOLS):]


def test_code_mode_respects_disabled_tools(tmp_path):
    config = _config(tmp_path, code_mode=True, disabled_tools=["code"])

    assert "code" not in _names(config, tmp_path)


def test_board_tools_take_emote_slot_before_show_file(tmp_path):
    names = _names(_config(tmp_path), tmp_path, callbacks=AgentCallbacks(board=MagicMock()))
    assert names == _FILE_TOOLS + _SESSION_TOOLS + [
        "reload_skills", "read_board", "post_board", "fetch_attachment", "show_file",
        "read_notepad", "spawn_alpha", "spawn_beta", "extend_subagent_timeout", "project_x",
        "schedule_task", "list_scheduled_tasks", "remove_scheduled_task", "write_handoff",
    ]
