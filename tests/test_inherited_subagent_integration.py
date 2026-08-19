"""End-to-end request inheritance for typed subagent tools."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.base_tool import BaseTool
from agent.loop import AgentConfig, AgentLoop, TASK_END_FLAG
from agent.registry import ToolRegistry
from tools.subagent_main import run_forked_subagent_mode


HANDOFF = """# Exploration: inherited request

## Summary
The child received the parent request prefix unchanged.

## Citations
agent/loop.py:1-2 — test fixture citation.

## Notes
- Complete handoff body must reach the parent tool result.
"""

WTF_HANDOFF = """## Description
The diagnostic completed after a blocked attempt.

## Error Report
The child tried a disallowed write before reading the requested file.

## Suggested Fix
Keep the diagnostic tools read-only.
"""


class _SiblingTool(BaseTool):
    """A completed sibling call makes the parent response a multi-tool turn."""

    name = "sibling"
    description = "A harmless sibling tool."
    _parameters = {"type": "object", "properties": {}, "required": []}

    def run(self) -> str:
        return "sibling completed"


class _AllowedReadTool(BaseTool):
    """A real child implementation used to prove allowlisted recovery."""

    name = "read"
    description = "Read a file."
    _parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return "allowed read content"


def _response(
    content: str | None,
    tool_calls: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        cost=None,
        completion_tokens_details=None,
        prompt_tokens_details=None,
    )
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls or [],
        model_extra={},
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _tool_call(call_id: str, name: str, arguments: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _explore_files_tool() -> type[BaseTool]:
    """Load the auto-discovered typed wrapper exactly as production discovery does."""
    path = Path(__file__).parents[1] / ".dagi" / "subagents" / "explore_files" / "main.py"
    spec = importlib.util.spec_from_file_location("task7_explore_files", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ExploreFilesTool


def test_typed_subagent_inherits_triggering_prefix_and_returns_full_handoff(tmp_path: Path) -> None:
    """Dropping the parent snapshot or returning only a handoff path breaks this flow."""
    ExploreFilesTool = _explore_files_tool()

    parent_client = MagicMock()
    child_client = MagicMock()
    parent_client.chat.completions.create.side_effect = [
        _response(
            None,
            [
                _tool_call("explore-call", "explore_files", '{"task": "map the loop"}'),
                _tool_call("sibling-call", "sibling", "{}"),
            ],
        ),
        _response(f"Complete. {TASK_END_FLAG}"),
    ]
    child_client.chat.completions.create.return_value = _response(HANDOFF)

    config = AgentConfig(
        model="parent-model",
        base_url="https://provider.example/v1",
        api_key="parent-key",
        system_prompt="Parent system instruction.",
        project_path=tmp_path,
        thinking="low",
        cache_prompt=True,
        provider_order=["preferred-provider"],
    )
    registry = ToolRegistry()
    captured_contexts: list[dict] = []
    child_errors: list[str] = []
    openai_factory = MagicMock(side_effect=[parent_client, child_client])

    with patch("openai.OpenAI", openai_factory):
        loop = AgentLoop(config=config, _registry=registry)
        loop._skip_slug_generation = True
        loop._parallel_tool_calls = True
        registry.register(
            ExploreFilesTool(
                config=config,
                session_log=loop.log,
                parent_context=loop.parent_context_provider,
            )
        )
        registry.register(_SiblingTool())

        def run_child(*, task: str, handoff_path: Path, extra_argv: list[str], **_kwargs) -> dict:
            fork_path = Path(extra_argv[extra_argv.index("--fork-context") + 1])
            captured_contexts.append(json.loads(fork_path.read_text(encoding="utf-8")))
            task_path = tmp_path / "child-task.md"
            task_path.write_text(task, encoding="utf-8")
            try:
                run_forked_subagent_mode(
                    str(fork_path),
                    str(task_path),
                    str(handoff_path),
                    str(tmp_path),
                )
            except Exception as exc:  # The parent registry reports runner errors as tool results.
                child_errors.append(f"{type(exc).__name__}: {exc}")
                raise
            finally:
                fork_path.unlink(missing_ok=True)
            return {"status": "ok", "handoff": str(handoff_path)}

        local_child_config = AgentConfig(
            model="parent-model",
            base_url="https://provider.example/v1",
            api_key="child-key",
            project_path=tmp_path,
            max_continuations=0,
        )
        with (
            patch("tools.subagent_api._runner.run_subagent", side_effect=run_child),
            patch("tools.subagent_main.resolve_model_config", return_value=local_child_config),
        ):
            loop.run("Delegate exploration.")

    assert child_errors == []
    parent_request = parent_client.chat.completions.create.call_args_list[0].kwargs
    child_request = child_client.chat.completions.create.call_args.kwargs
    context = captured_contexts[0]

    assert context["request"] == {
        "model": parent_request["model"],
        "messages": parent_request["messages"],
        "tools": parent_request["tools"],
        "parallel_tool_calls": parent_request["parallel_tool_calls"],
        "extra_body": parent_request["extra_body"],
        "base_url": config.base_url,
    }
    assert child_request["model"] == parent_request["model"]
    assert child_request["messages"][:-1] == parent_request["messages"]
    assert child_request["messages"][-1] == {
        "role": "user",
        "content": "## Task\nmap the loop\n\n---\n\n## Output\n"
        "A structured exploration report with a summary, file:line citations for every "
        "finding, and notable caveats.",
    }
    assert child_request["tools"] == parent_request["tools"]
    assert child_request["parallel_tool_calls"] is True
    assert child_request["extra_body"] == parent_request["extra_body"]
    assert child_client.chat.completions.create.call_count == 1
    assert openai_factory.call_args_list[1].kwargs == {
        "api_key": "child-key",
        "base_url": config.base_url,
    }

    branch_events = [event for event in loop.log.events if event.type == "branch/start"]
    assert len(branch_events) == 1
    assert context["branch"] == {
        "id": branch_events[0].data["branch"],
        "parent_cut_seq": branch_events[0].data["parent_cut_seq"],
        "parent_surface_generation": branch_events[0].data["parent_surface_generation"],
    }
    assert context["branch"]["parent_surface_generation"] == 0
    expected_cut = next(
        event.seq
        for event in loop.log.events
        if event.type == "user/message" and event.data["content"] == "Delegate exploration."
    )
    assert context["branch"]["parent_cut_seq"] == expected_cut

    parent_tool_results = [
        event.data["content"]
        for event in loop.log.events
        if event.type == "tool/result" and event.data["call_id"] == "explore-call"
    ]
    assert parent_tool_results == [
        "Subagent completed. Handoff written to: "
        + str(next((tmp_path / ".dagi" / "handoffs").glob("explore_files_*.md")))
        + "\n\n--- Handoff content ---\n"
        + HANDOFF
    ]


def test_inherited_child_blocks_write_then_recovers_with_allowed_read(tmp_path: Path) -> None:
    """A blocked child call must be an ordinary tool result, not a terminal failure."""
    child_client = MagicMock()
    child_client.chat.completions.create.side_effect = [
        _response(None, [_tool_call("blocked", "write", '{"path":"forbidden.txt"}')]),
        _response(None, [_tool_call("allowed", "read", '{"path":"README.md"}')]),
        _response(WTF_HANDOFF),
    ]
    read_tool = _AllowedReadTool()
    implementation_registry = ToolRegistry()
    implementation_registry.register(read_tool)
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "write",
                "description": "Write a file.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file.",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        },
    ]
    context = {
        "version": 2,
        "branch": {"id": "wtf_1234", "parent_cut_seq": 4, "parent_surface_generation": 0},
        "request": {
            "model": "parent-model",
            "messages": [
                {"role": "system", "content": "Parent system instruction."},
                {"role": "user", "content": "The parent observed a failure."},
            ],
            "tools": schemas,
            "parallel_tool_calls": False,
            "extra_body": {},
            "base_url": "https://provider.example/v1",
        },
        "child": {"type": "wtf", "allowed_tools": ["read"]},
    }
    fork_path = tmp_path / "fork.json"
    task_path = tmp_path / "task.md"
    handoff_path = tmp_path / ".dagi" / "errors" / "wtf_1234.md"
    fork_path.write_text(json.dumps(context), encoding="utf-8")
    task_path.write_text("Investigate the failure.", encoding="utf-8")
    config = AgentConfig(
        model="parent-model",
        api_key="child-key",
        base_url="https://provider.example/v1",
        project_path=tmp_path,
        max_continuations=0,
    )

    with (
        patch("openai.OpenAI", return_value=child_client),
        patch("tools.subagent_main.resolve_model_config", return_value=config),
        patch(
            "tools.subagent_main.build_subagent_registry",
            return_value=implementation_registry,
        ),
    ):
        run_forked_subagent_mode(
            str(fork_path), str(task_path), str(handoff_path), str(tmp_path)
        )

    assert handoff_path.read_text(encoding="utf-8") == WTF_HANDOFF
    assert read_tool.calls == [{"path": "README.md"}]
    blocked_results = [
        message["content"]
        for call in child_client.chat.completions.create.call_args_list
        for message in call.kwargs["messages"]
        if message.get("role") == "tool" and message.get("tool_call_id") == "blocked"
    ]
    assert blocked_results
    assert set(blocked_results) == {
        "Error: Access blocked for tool 'write' in subagent 'wtf'. Allowed tools: read"
    }
    read_results = [
        message["content"]
        for call in child_client.chat.completions.create.call_args_list
        for message in call.kwargs["messages"]
        if message.get("role") == "tool" and message.get("tool_call_id") == "allowed"
    ]
    assert read_results
    assert set(read_results) == {"allowed read content"}
