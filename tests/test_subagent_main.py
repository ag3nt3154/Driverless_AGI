"""tests/test_subagent_main.py — Unit tests for tools/subagent_main.py."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from tools.subagent_main import _ensure_handoff, _HANDOFF_RETRY_PROMPT, _build_subagent_system_prompt


class _FakeLoop:
    """Minimal AgentLoop test double: tracks .run() calls, optionally writes handoff.

    ``write_on_call`` is 1-indexed against the *cumulative* ``run_calls`` count for this
    instance (including any call the test makes directly before invoking
    ``_ensure_handoff``), not against calls made through ``_ensure_handoff`` alone. Tests
    that pre-seed a call (e.g. ``loop.run("original task")``) before calling
    ``_ensure_handoff`` must account for that call when choosing ``write_on_call``.
    """

    def __init__(self, handoff_path: Path, write_on_call: int | None = None, messages=None):
        self.handoff_path = handoff_path
        self.write_on_call = write_on_call
        self.run_calls: list[str] = []
        self._messages = messages if messages is not None else []
        self.finish_calls = 0

    def run(self, task: str) -> None:
        self.run_calls.append(task)
        if self.write_on_call is not None and len(self.run_calls) == self.write_on_call:
            self.handoff_path.parent.mkdir(parents=True, exist_ok=True)
            self.handoff_path.write_text("# Handoff\n\nreal report", encoding="utf-8")

    def finish(self) -> None:
        self.finish_calls += 1


def _flag_path(handoff_path: Path) -> Path:
    return handoff_path.with_name(f"{handoff_path.stem}_unverified.flag")


def test_handoff_already_exists_after_first_call_no_retry(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=1)

    # Simulate: first loop.run() already happened and wrote the handoff.
    loop.run("original task")
    assert len(loop.run_calls) == 1

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 1  # no retry triggered
    assert not _flag_path(handoff_path).exists()


def test_handoff_absent_then_present_after_retry(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=2)

    loop.run("original task")
    assert len(loop.run_calls) == 1
    assert not handoff_path.exists()

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    assert handoff_path.exists()
    assert not _flag_path(handoff_path).exists()
    assert "write_handoff" in loop.run_calls[1]
    assert loop.run_calls[1] == _HANDOFF_RETRY_PROMPT


def test_handoff_absent_after_both_calls_scrapes_and_flags(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "final report text"},
    ]
    loop = _FakeLoop(handoff_path, write_on_call=None, messages=messages)

    loop.run("original task")
    assert len(loop.run_calls) == 1

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    assert handoff_path.exists()
    content = handoff_path.read_text(encoding="utf-8")
    assert content == "# Handoff\n\nfinal report text"
    assert _flag_path(handoff_path).exists()


def test_handoff_absent_no_usable_text_falls_back(tmp_path):
    handoff_path = tmp_path / "worker_abc123.md"
    loop = _FakeLoop(handoff_path, write_on_call=None, messages=[])

    loop.run("original task")
    _ensure_handoff(loop, handoff_path)

    content = handoff_path.read_text(encoding="utf-8")
    assert content == "# Handoff\n\n(subagent produced no output)"
    assert _flag_path(handoff_path).exists()


def test_retry_call_exception_is_caught_and_emits_error(tmp_path, capsys):
    handoff_path = tmp_path / "worker_abc123.md"

    class _RaisingLoop(_FakeLoop):
        def run(self, task: str) -> None:
            self.run_calls.append(task)
            if len(self.run_calls) == 2:
                raise RuntimeError("boom")

    loop = _RaisingLoop(handoff_path, write_on_call=None, messages=[])
    loop.run("original task")

    _ensure_handoff(loop, handoff_path)

    assert len(loop.run_calls) == 2
    out = capsys.readouterr().out
    assert "error" in out
    assert "boom" in out
    assert "handoff_retry" in out  # phase marker distinguishes retry-path errors
    # Since retry raised, no second successful run wrote the handoff — scrape path still runs.
    assert handoff_path.exists()
    assert _flag_path(handoff_path).exists()


def test_pipe_mode_finish_runs_after_handoff_retry(tmp_path, monkeypatch):
    """loop.finish() must run only after _ensure_handoff's possible retry loop.run().

    Regression test: previously loop.finish() (which snapshots messages/tokens/cost
    for the persisted session record) ran before _ensure_handoff's retry, silently
    dropping the retry's cost/tokens/tool-calls/messages from the session JSONL.
    """
    import tools.subagent_main as subagent_main

    call_order: list[str] = []
    handoff_path = tmp_path / "worker_abc123.md"

    class _OrderedFakeLoop(_FakeLoop):
        def run(self, task: str) -> None:
            call_order.append(f"run:{task}")
            super().run(task)
            # Simulate the subagent forgetting to call write_handoff on the primary
            # run, but succeeding on the retry (write_on_call=2).

        def finish(self) -> None:
            call_order.append("finish")
            super().finish()

    fake_loop = _OrderedFakeLoop(handoff_path, write_on_call=2)

    task_file = tmp_path / "task.txt"
    task_file.write_text("do the thing", encoding="utf-8")

    monkeypatch.setattr(
        subagent_main, "resolve_model_config", lambda model, project_path: subagent_main.AgentConfig()
    )
    monkeypatch.setattr(
        subagent_main, "build_subagent_registry", lambda **kwargs: object()
    )
    monkeypatch.setattr(
        subagent_main, "_build_subagent_system_prompt", lambda subagent_type, project_path: "sys"
    )
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **kwargs: fake_loop)

    subagent_main.run_subagent_pipe_mode(
        subagent_type="worker",
        task_file=str(task_file),
        handoff=str(handoff_path),
        project=str(tmp_path),
        model=None,
    )

    assert call_order == ["run:do the thing", f"run:{_HANDOFF_RETRY_PROMPT}", "finish"]
    assert handoff_path.exists()


# ── _build_subagent_system_prompt reads agents_md from config ─────────────────

def test_build_system_prompt_reads_agents_md_from_config(tmp_path, monkeypatch):
    """_build_subagent_system_prompt reads agents_md list from subagent_config.yaml."""
    import tools.subagent_main as subagent_main

    # Create a fake subagent config with agents_md: [cwd]
    subagent_dir = tmp_path / ".dagi" / "subagents" / "mytype"
    subagent_dir.mkdir(parents=True)
    (subagent_dir / "subagent_config.yaml").write_text(
        yaml.dump({"agents_md": ["cwd"]}), encoding="utf-8"
    )
    (tmp_path / "AGENTS.md").write_text("# Project Context", encoding="utf-8")

    monkeypatch.setattr(subagent_main, "load_subagent_prompt", lambda t: "base prompt")

    result = _build_subagent_system_prompt("mytype", tmp_path)

    assert "base prompt" in result
    assert "# Project Context" in result


def test_build_system_prompt_no_config_returns_base(tmp_path, monkeypatch):
    """_build_subagent_system_prompt returns base prompt only when config is absent."""
    import tools.subagent_main as subagent_main

    monkeypatch.setattr(subagent_main, "load_subagent_prompt", lambda t: "base only")
    # Patch DAGI_ROOT to tmp_path so no real config is accidentally loaded
    monkeypatch.setattr(subagent_main, "DAGI_ROOT", tmp_path)

    result = _build_subagent_system_prompt("nonexistent_type", tmp_path)

    assert result == "base only"


# ── run_subagent_pipe_mode --tools override ───────────────────────────────────

def test_pipe_mode_passes_tool_names_to_registry(tmp_path, monkeypatch):
    """--tools arg is forwarded as tool_names_override to build_subagent_registry."""
    import tools.subagent_main as subagent_main

    handoff_path = tmp_path / "worker_abc123.md"
    task_file = tmp_path / "task.txt"
    task_file.write_text("do the thing", encoding="utf-8")

    captured: dict = {}

    def _fake_registry(**kwargs):
        captured.update(kwargs)
        return object()

    fake_loop = _FakeLoop(handoff_path, write_on_call=1)

    monkeypatch.setattr(
        subagent_main, "resolve_model_config",
        lambda model, project_path: subagent_main.AgentConfig()
    )
    monkeypatch.setattr(subagent_main, "build_subagent_registry", _fake_registry)
    monkeypatch.setattr(
        subagent_main, "_build_subagent_system_prompt",
        lambda subagent_type, project_path: "sys"
    )
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **kwargs: fake_loop)

    subagent_main.run_subagent_pipe_mode(
        subagent_type="worker",
        task_file=str(task_file),
        handoff=str(handoff_path),
        project=str(tmp_path),
        model=None,
        tool_names=["read", "grep"],
    )

    assert captured.get("tool_names_override") == ["read", "grep"]


# ── TestForkedCompactMode ─────────────────────────────────────────────────────

class TestForkedCompactMode:
    def test_inherit_tier_rejects_without_fork_context(self):
        """_resolve_inherited_model raises ValueError when fork_context is None."""
        from tools.subagent_main import _resolve_inherited_model
        with pytest.raises(ValueError, match="inherit.*fork.context"):
            _resolve_inherited_model(None)

    def test_inherit_tier_uses_fork_context_model(self):
        """_resolve_inherited_model returns model and base_url from fork-context."""
        from tools.subagent_main import _resolve_inherited_model
        fork_ctx = {
            "version": 1,
            "request": {
                "model": "anthropic/claude-sonnet-4",
                "base_url": "https://openrouter.ai/api/v1",
            },
        }
        model, base_url = _resolve_inherited_model(fork_ctx)
        assert model == "anthropic/claude-sonnet-4"
        assert base_url == "https://openrouter.ai/api/v1"

    def test_tool_call_response_rejected(self):
        """A tool-call response from the compact model is rejected."""
        from types import SimpleNamespace
        from tools.subagent_main import _validate_compact_response
        msg = SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(id="tc1")],
        )
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="tool_calls")],
        )
        ok, error = _validate_compact_response(response)
        assert ok is False
        assert "tool" in error.lower()

    def test_empty_response_rejected(self):
        """An empty response is rejected."""
        from types import SimpleNamespace
        from tools.subagent_main import _validate_compact_response
        msg = SimpleNamespace(content="", tool_calls=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        )
        ok, error = _validate_compact_response(response)
        assert ok is False
        assert "empty" in error.lower()

    def test_truncated_response_rejected(self):
        """A length finish reason is rejected."""
        from types import SimpleNamespace
        from tools.subagent_main import _validate_compact_response
        msg = SimpleNamespace(content="partial", tool_calls=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="length")],
        )
        ok, error = _validate_compact_response(response)
        assert ok is False
        assert "truncat" in error.lower()

    def test_valid_response_accepted(self):
        """A valid text-only stop response is accepted."""
        from types import SimpleNamespace
        from tools.subagent_main import _validate_compact_response
        msg = SimpleNamespace(content="Summary of conversation.", tool_calls=None)
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        )
        ok, error = _validate_compact_response(response)
        assert ok is True
        assert error == ""

    def test_compact_task_message_structure(self):
        """The compact task message includes prompt rules and handoff spec."""
        from tools.subagent_main import _build_compact_task_message
        prompt = "# Compact\n\nYou are a summariser."
        handoff_spec = "A cumulative summary."
        msg = _build_compact_task_message(prompt, handoff_spec)
        assert msg["role"] == "user"
        content = msg["content"]
        assert "You are a summariser" in content
        assert "Summarize the entire conversation above" in content
        assert "A cumulative summary" in content

    def test_run_forked_compact_mode_writes_handoff(self, tmp_path):
        """run_forked_compact_mode writes the assistant text as the handoff."""
        import json
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from tools.subagent_main import run_forked_compact_mode

        # Set up preset
        preset_dir = tmp_path / ".dagi" / "subagents" / "compact"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("You are a summariser.", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "model_tier: inherit\ntools: []\n"
            "default_handoff_spec: summary\nagents_md: []\n",
            encoding="utf-8",
        )

        # Set up fork-context
        fc = {
            "version": 1,
            "branch": {"id": "compact_t1", "parent_cut_seq": 5, "parent_surface_generation": 0},
            "request": {
                "model": "test/model",
                "messages": [{"role": "system", "content": "sys"}],
                "tools": [],
                "parallel_tool_calls": False,
                "extra_body": {},
                "base_url": "https://api.test.com/v1",
            },
        }
        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text(json.dumps(fc), encoding="utf-8")
        handoff_path = tmp_path / "handoff.md"

        fake_msg = SimpleNamespace(content="This is the summary.", tool_calls=None)
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=fake_msg, finish_reason="stop")],
            usage=None,
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response

        with patch("tools.subagent_main.resolve_model_config") as mock_config:
            mock_config.return_value = MagicMock(
                api_key="sk-test", base_url="https://api.test.com/v1"
            )
            with patch("openai.OpenAI", return_value=mock_client):
                run_forked_compact_mode(
                    fork_context_path=str(fc_path),
                    handoff_path=str(handoff_path),
                    subagent_type="compact",
                    project_path=str(tmp_path),
                )

        assert handoff_path.exists()
        assert handoff_path.read_text(encoding="utf-8") == "This is the summary."

    def test_run_forked_compact_mode_rejects_tool_call(self, tmp_path):
        """run_forked_compact_mode does not write handoff on tool-call response."""
        import json
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        from tools.subagent_main import run_forked_compact_mode

        preset_dir = tmp_path / ".dagi" / "subagents" / "compact"
        preset_dir.mkdir(parents=True)
        (preset_dir / "prompt.md").write_text("summarise", encoding="utf-8")
        (preset_dir / "subagent_config.yaml").write_text(
            "model_tier: inherit\ntools: []\ndefault_handoff_spec: s\nagents_md: []\n",
            encoding="utf-8",
        )

        fc = {
            "version": 1,
            "branch": {"id": "compact_t2", "parent_cut_seq": 5, "parent_surface_generation": 0},
            "request": {
                "model": "test/model",
                "messages": [{"role": "system", "content": "sys"}],
                "tools": [],
                "parallel_tool_calls": False,
                "extra_body": {},
                "base_url": "",
            },
        }
        fc_path = tmp_path / "fork_ctx.json"
        fc_path.write_text(json.dumps(fc), encoding="utf-8")
        handoff_path = tmp_path / "handoff.md"

        fake_msg = SimpleNamespace(
            content=None,
            tool_calls=[SimpleNamespace(id="c1")],
        )
        fake_response = SimpleNamespace(
            choices=[SimpleNamespace(message=fake_msg, finish_reason="tool_calls")],
            usage=None,
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response

        with patch("tools.subagent_main.resolve_model_config") as mock_config:
            mock_config.return_value = MagicMock(api_key="sk-test", base_url="")
            with patch("openai.OpenAI", return_value=mock_client):
                run_forked_compact_mode(
                    fork_context_path=str(fc_path),
                    handoff_path=str(handoff_path),
                    subagent_type="compact",
                    project_path=str(tmp_path),
                )

        # Handoff must NOT exist — tool-call response rejected
        assert not handoff_path.exists()


class _InheritedLoop:
    def __init__(self, results: list[str], **kwargs) -> None:
        self.kwargs = kwargs
        self._results = results
        self.run_calls: list[str] = []
        self.finish_calls = 0

    def run(self, task: str) -> str:
        self.run_calls.append(task)
        return self._results.pop(0)

    def finish(self) -> None:
        self.finish_calls += 1


def _v2_context() -> dict:
    return {
        "version": 2,
        "branch": {"id": "worker_abc", "parent_cut_seq": 4, "parent_surface_generation": 0},
        "request": {
            "model": "parent/model",
            "messages": [
                {"role": "system", "content": "parent system bytes"},
                {"role": "user", "content": "parent request"},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "parent schema",
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
            "parallel_tool_calls": True,
            "extra_body": {"provider": {"order": ["Parent"]}},
            "base_url": "https://parent.example/v1",
        },
        "child": {"type": "worker", "allowed_tools": ["read"]},
    }


def _write_v2_inputs(tmp_path, context: dict | None = None) -> tuple[Path, Path, Path]:
    context_path = tmp_path / "fork.json"
    context_path.write_text(json.dumps(context or _v2_context()), encoding="utf-8")
    task_path = tmp_path / "task.txt"
    task_path.write_text("child task", encoding="utf-8")
    return context_path, task_path, tmp_path / "handoff.md"


def _matching_inherited_config(subagent_main):
    return subagent_main.AgentConfig(
        model="parent/model",
        api_key="local-key", base_url="https://parent.example/v1"
    )


def test_forked_v2_uses_inherited_prefix_and_request_options(tmp_path, monkeypatch):
    """Changing inherited request identity would break the parent's warm cache prefix."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    loop = _InheritedLoop(["completed report"])
    captured: dict = {}

    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: _matching_inherited_config(subagent_main),
    )
    monkeypatch.setattr(
        subagent_main,
        "build_subagent_registry",
        lambda **kwargs: captured.update(kwargs) or MagicMock(),
    )
    monkeypatch.setattr(
        subagent_main,
        "AgentLoop",
        lambda **kwargs: captured.update(loop=kwargs) or loop,
    )

    subagent_main.run_forked_subagent_mode(
        str(context_path), str(task_path), str(handoff_path), str(tmp_path)
    )

    request = _v2_context()["request"]
    assert captured["handoff_path"] is None
    assert captured["loop"]["initial_messages"] == request["messages"]
    assert captured["loop"]["_system_prompt_override"] == "parent system bytes"
    assert captured["loop"]["_registry"].get_openai_tools_list() == request["tools"]
    assert "write_handoff" not in [
        schema["function"]["name"]
        for schema in captured["loop"]["_registry"].get_openai_tools_list()
    ]
    assert captured["loop"]["config"].model == request["model"]
    assert captured["loop"]["config"].base_url == request["base_url"]
    assert loop._extra_body == request["extra_body"]
    assert loop._parallel_tool_calls is True
    assert len(loop.run_calls) == 1
    assert loop.run_calls[0].endswith("child task")
    assert handoff_path.read_text(encoding="utf-8") == "completed report"
    assert loop.finish_calls == 1


def test_forked_v2_places_resolved_preset_prompt_after_inherited_prefix(tmp_path, monkeypatch):
    """Inherited execution must preserve the prefix, then apply preset instructions."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    prompt_path = tmp_path / "resolved-prompt.md"
    prompt_path.write_text("resolved preset instructions", encoding="utf-8")
    loop = _InheritedLoop(["completed report"])
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: _matching_inherited_config(subagent_main),
    )
    monkeypatch.setattr(subagent_main, "build_subagent_registry", lambda **_k: MagicMock())
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **_k: loop)

    subagent_main.run_forked_subagent_mode(
        str(context_path),
        str(task_path),
        str(handoff_path),
        str(tmp_path),
        system_prompt_file=str(prompt_path),
    )

    task = loop.run_calls[0]
    assert task.index("resolved preset instructions") < task.index("## Inherited Child Contract")
    assert task.index("## Inherited Child Contract") < task.index("child task")
    assert "Effective allowed tools: read" in task
    assert "Error: Access blocked for tool '<name>'" in task
    assert "Do not call `write_handoff`" in task
    assert "return the required handoff as your final assistant text" in task


def test_forked_v2_uses_child_allowed_tools_for_implementation_registry(
    tmp_path, monkeypatch
):
    """Preset tools outside the fork allowlist must not receive implementations."""
    import tools.subagent_main as subagent_main

    context = _v2_context()
    context["child"]["allowed_tools"] = ["read", "grep"]
    context["request"]["tools"].append({
        "type": "function",
        "function": {
            "name": "write",
            "description": "parent write schema",
            "parameters": {"type": "object", "properties": {}},
        },
    })
    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path, context)
    captured: dict = {}
    loop = _InheritedLoop(["completed report"])
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: _matching_inherited_config(subagent_main),
    )
    monkeypatch.setattr(
        subagent_main,
        "build_subagent_registry",
        lambda **kwargs: captured.update(kwargs) or MagicMock(),
    )
    monkeypatch.setattr(
        subagent_main,
        "AgentLoop",
        lambda **kwargs: captured.update(loop=kwargs) or loop,
    )

    subagent_main.run_forked_subagent_mode(
        str(context_path), str(task_path), str(handoff_path), str(tmp_path)
    )

    assert captured["tool_names_override"] == ["read", "grep"]
    assert captured["loop"]["_registry"].dispatch("write", {}) == (
        "Error: Access blocked for tool 'write' in subagent 'worker'. Allowed tools: read"
    )


def test_build_inherited_config_resolves_non_default_catalog_model(tmp_path):
    """A valid active model must use its own key instead of the catalog default's key."""
    from tools.subagent_main import _build_inherited_config

    config_dir = tmp_path / ".dagi"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "models:\n"
        "  inherited-active:\n"
        "    model: vendor/non-default\n"
        "    api_url: https://active.example/v1\n"
        "    api_key: active-key\n",
        encoding="utf-8",
    )

    config = _build_inherited_config(
        {"model": "vendor/non-default", "base_url": "https://active.example/v1"},
        tmp_path,
    )

    assert config.model_id == "inherited-active"
    assert config.model == "vendor/non-default"
    assert config.api_key == "active-key"


def test_build_inherited_config_prefers_provider_match_over_catalog_id_collision(tmp_path):
    """A catalog ID collision must not supply credentials for a different provider model."""
    from tools.subagent_main import _build_inherited_config

    config_dir = tmp_path / ".dagi"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "models:\n"
        "  vendor/non-default:\n"
        "    model: vendor/wrong-model\n"
        "    api_url: https://wrong.example/v1\n"
        "    api_key: wrong-key\n"
        "  inherited-active:\n"
        "    model: vendor/non-default\n"
        "    api_url: https://active.example/v1\n"
        "    api_key: active-key\n",
        encoding="utf-8",
    )

    config = _build_inherited_config(
        {"model": "vendor/non-default", "base_url": "https://active.example/v1"},
        tmp_path,
    )

    assert config.model_id == "inherited-active"
    assert config.model == "vendor/non-default"
    assert config.api_key == "active-key"


def test_forked_v2_retries_once_with_the_exact_validation_error(tmp_path, monkeypatch):
    """An invalid final answer must get one corrective turn, never an unverified handoff."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    loop = _InheritedLoop(["", "completed report"])
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: _matching_inherited_config(subagent_main),
    )
    monkeypatch.setattr(subagent_main, "build_subagent_registry", lambda **_k: MagicMock())
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **_k: loop)

    subagent_main.run_forked_subagent_mode(
        str(context_path), str(task_path), str(handoff_path), str(tmp_path)
    )

    assert len(loop.run_calls) == 2
    assert loop.run_calls[0].endswith("child task")
    assert loop.run_calls[1] == f"{loop.run_calls[0]}\n\nEmpty final handoff text"
    assert handoff_path.read_text(encoding="utf-8") == "completed report"
    assert loop.finish_calls == 1


def test_forked_v2_fails_without_writing_an_unverified_handoff(tmp_path, monkeypatch):
    """Keeping a malformed response would let a parent accept an invalid child result."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    loop = _InheritedLoop(["", ""])
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: _matching_inherited_config(subagent_main),
    )
    monkeypatch.setattr(subagent_main, "build_subagent_registry", lambda **_k: MagicMock())
    monkeypatch.setattr(subagent_main, "AgentLoop", lambda **_k: loop)

    with pytest.raises(ValueError, match="Empty final handoff text"):
        subagent_main.run_forked_subagent_mode(
            str(context_path), str(task_path), str(handoff_path), str(tmp_path)
        )

    assert not handoff_path.exists()
    assert loop.finish_calls == 1


def test_final_handoff_validation_requires_configured_headings():
    """Dropping a contract heading makes a handoff unusable for its caller."""
    from tools.subagent_main import _validate_final_handoff

    ok, error = _validate_final_handoff("## Findings\ncontent", ["Findings", "Changes"])

    assert ok is False
    assert error == "Missing required sections: ## Changes"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("## Findings\n\n## Changes\nimplemented", "Empty section: ## Findings"),
        (
            "## Findings\nobserved\n## Changes\nimplemented\n## Changes\nagain",
            "Duplicate section: ## Changes",
        ),
        (
            "## Findings\nobserved\n## Changes\nimplemented\n## Extra\nnope",
            "Unknown section: ## Extra",
        ),
        (
            "# Findings\nobserved\n## Changes\nimplemented",
            "Expected level-2 heading for section: Findings",
        ),
    ],
)
def test_final_handoff_validation_rejects_malformed_configured_sections(text, expected):
    from tools.subagent_main import _validate_final_handoff

    ok, error = _validate_final_handoff(text, ["Findings", "Changes"])

    assert ok is False
    assert error == expected


def test_final_handoff_validation_accepts_exact_non_empty_sections():
    from tools.subagent_main import _validate_final_handoff

    ok, error = _validate_final_handoff(
        "## Findings\nobserved\n## Changes\nimplemented", ["Findings", "Changes"]
    )

    assert ok is True
    assert error == ""


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "intro\n\n## Findings\nobserved\n## Changes\nimplemented",
            "Unexpected preamble before first section",
        ),
        (
            "## Changes\nimplemented\n## Findings\nobserved",
            "Sections out of order: expected ## Findings, ## Changes",
        ),
    ],
)
def test_final_handoff_validation_rejects_preamble_and_wrong_section_order(text, expected):
    """A caller must be able to parse the configured contract without ambiguity."""
    from tools.subagent_main import _validate_final_handoff

    ok, error = _validate_final_handoff(text, ["Findings", "Changes"])

    assert ok is False
    assert error == expected


def test_forked_v2_rejects_incompatible_local_credentials_before_agent_loop(
    tmp_path, monkeypatch
):
    """An inherited endpoint must never use unrelated local provider credentials."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    calls: list[str] = []

    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: subagent_main.AgentConfig(
            model="parent/model",
            api_key="local-key", base_url="https://unrelated.example/v1"
        ),
    )
    monkeypatch.setattr(
        subagent_main,
        "AgentLoop",
        lambda **_kwargs: calls.append("agent-loop")
        or (_ for _ in ()).throw(AssertionError("provider call setup must be blocked")),
    )

    with pytest.raises(ValueError, match="provider.*mismatch"):
        subagent_main.run_forked_subagent_mode(
            str(context_path), str(task_path), str(handoff_path), str(tmp_path)
        )

    assert calls == []
    assert not handoff_path.exists()


def test_forked_v2_does_not_use_default_key_for_same_endpoint_other_model(
    tmp_path, monkeypatch
):
    """A same-endpoint default model is not a credential match for the parent model."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: subagent_main.AgentConfig(
            model="default/model",
            api_key="default-key",
            base_url="https://parent.example/v1",
        ),
    )
    monkeypatch.setattr(
        subagent_main,
        "AgentLoop",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not use default key")),
    )

    with pytest.raises(ValueError, match="different model"):
        subagent_main.run_forked_subagent_mode(
            str(context_path), str(task_path), str(handoff_path), str(tmp_path)
        )

    assert not handoff_path.exists()


def test_forked_v2_rejects_missing_local_credentials_before_agent_loop(tmp_path, monkeypatch):
    """An inherited child must fail before setup when no local key is available."""
    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_a, **_k: subagent_main.AgentConfig(
            model="parent/model",
            api_key="", base_url="https://parent.example/v1"
        ),
    )
    monkeypatch.setattr(
        subagent_main,
        "AgentLoop",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must fail before loop")),
    )

    with pytest.raises(ValueError, match="credentials unavailable"):
        subagent_main.run_forked_subagent_mode(
            str(context_path), str(task_path), str(handoff_path), str(tmp_path)
        )

    assert not handoff_path.exists()


def test_system_override_keeps_the_inherited_request_prefix_byte_identical(tmp_path):
    """Adding local prompt text would turn a cache hit into a fresh provider request."""
    from types import SimpleNamespace

    from agent.loop import AWAIT_USER_FLAG, AgentConfig, AgentLoop
    from agent.registry import ToolRegistry

    inherited = [
        {"role": "system", "content": "parent system bytes"},
        {"role": "user", "content": "parent request"},
    ]
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=f"done {AWAIT_USER_FLAG}", tool_calls=[]),
        )],
        usage=SimpleNamespace(
            prompt_tokens=1,
            completion_tokens=1,
            cost=None,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )
    with patch("openai.OpenAI"):
        loop = AgentLoop(
            config=AgentConfig(api_key="test", project_path=tmp_path, system_prompt="local prompt"),
            initial_messages=inherited,
            _registry=ToolRegistry(),
            _system_prompt_override=inherited[0]["content"],
            _preserve_request_prefix=True,
        )
    loop._skip_slug_generation = True
    loop.client = MagicMock()
    loop.client.chat.completions.create.return_value = response

    loop.run("child task")

    assert loop.system_parts[-1]["content"] == "local prompt"
    assert loop.client.chat.completions.create.call_args.kwargs["messages"] == [
        *inherited,
        {"role": "user", "content": "child task"},
    ]


def test_inherited_run_skips_wiki_context_between_prefix_and_child_task(tmp_path):
    """Configured wiki context must not break the inherited cache prefix."""
    from types import SimpleNamespace

    from agent.loop import AWAIT_USER_FLAG, AgentConfig, AgentLoop
    from agent.registry import ToolRegistry

    inherited = [
        {"role": "system", "content": "parent system bytes"},
        {"role": "user", "content": "parent request"},
    ]
    response = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=f"done {AWAIT_USER_FLAG}", tool_calls=[]),
        )],
        usage=SimpleNamespace(
            prompt_tokens=1,
            completion_tokens=1,
            cost=None,
            completion_tokens_details=None,
            prompt_tokens_details=None,
        ),
    )
    with patch("openai.OpenAI"):
        loop = AgentLoop(
            config=AgentConfig(
                api_key="test",
                project_path=tmp_path,
                system_prompt="local prompt",
                memory_root=tmp_path / "wiki",
            ),
            initial_messages=inherited,
            _registry=ToolRegistry(),
            _system_prompt_override=inherited[0]["content"],
            _preserve_request_prefix=True,
        )
    loop._skip_slug_generation = True
    loop.client = MagicMock()
    loop.client.chat.completions.create.return_value = response

    with patch("agent.loop._build_wiki_index_context", return_value="WIKI CONTEXT"):
        loop.run("child task")

    assert loop.client.chat.completions.create.call_args.kwargs["messages"] == [
        *inherited,
        {"role": "user", "content": "child task"},
    ]


def test_main_keeps_v1_compact_dispatch_and_rejects_unknown_versions(tmp_path, monkeypatch):
    """Routing a v1 compact request through generic execution would change its API contract."""
    import sys

    import tools.subagent_main as subagent_main

    context_path, task_path, handoff_path = _write_v2_inputs(tmp_path)
    context = _v2_context()
    context["version"] = 1
    context_path.write_text(json.dumps(context), encoding="utf-8")
    compact_calls: list[dict] = []
    monkeypatch.setattr(
        subagent_main,
        "run_forked_compact_mode",
        lambda **kwargs: compact_calls.append(kwargs),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "subagent_main.py", "--subagent-type", "compact", "--task-file", str(task_path),
            "--handoff", str(handoff_path), "--fork-context", str(context_path),
        ],
    )

    subagent_main.main()

    assert compact_calls == [{
        "fork_context_path": str(context_path),
        "handoff_path": str(handoff_path),
        "subagent_type": "compact",
        "project_path": None,
    }]

    context["version"] = 99
    context_path.write_text(json.dumps(context), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported fork-context version: 99"):
        subagent_main.main()


def test_inherit_tier_requires_fork_context_in_main_and_pipe_mode(tmp_path, monkeypatch):
    """A bare inherit tier must not silently become a worker subagent with write_handoff."""
    import sys

    import tools.subagent_main as subagent_main

    task_path = tmp_path / "task.txt"
    handoff_path = tmp_path / "handoff.md"
    task_path.write_text("compact this", encoding="utf-8")
    preset_path = tmp_path / ".dagi" / "subagents" / "compact"
    preset_path.mkdir(parents=True)
    (preset_path / "subagent_config.yaml").write_text(
        "model_tier: inherit\ntools: []\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "subagent_main.py", "--subagent-type", "compact", "--task-file", str(task_path),
            "--handoff", str(handoff_path), "--project", str(tmp_path),
        ],
    )
    with pytest.raises(ValueError, match="model_tier 'inherit' requires a fork-context file"):
        subagent_main.main()
    monkeypatch.setattr(
        subagent_main,
        "resolve_model_config",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("config was resolved")),
    )
    with pytest.raises(ValueError, match="model_tier 'inherit' requires a fork-context file"):
        subagent_main.run_subagent_pipe_mode(
            subagent_type="worker",
            task_file=str(task_path),
            handoff=str(handoff_path),
            project=str(tmp_path),
            model=None,
            model_tier_override="inherit",
        )
