"""Repro: does the 10s affect-drift fire during a turn vs while idle?"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.loop import AgentCallbacks, AgentConfig, AgentLoop, TASK_END_FLAG
from agent.registry import ToolRegistry


def _make_response(content):
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, cost=None,
                            completion_tokens_details=None)
    message = SimpleNamespace(content=content, tool_calls=[], model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


reasons: list[str] = []

tracker = MagicMock()
tracker.affect_controller = None
config = AgentConfig(
    model="test-model", api_key="k", system_prompt="s",
    project_path=Path("."), affect_drift_interval=0.5, _registry=None,
) if False else None

with (
    patch("agent.loop.SessionTracker", return_value=tracker),
    patch("openai.OpenAI"),
    patch.object(Path, "exists", return_value=False),
):
    config = AgentConfig(
        model="test-model", api_key="k", system_prompt="s",
        project_path=Path("."),
        affect_drift_interval=0.5,
    )
    loop = AgentLoop(config=config, _registry=ToolRegistry(), _tracker=tracker)

loop._skip_slug_generation = True


class _Ctl:
    def context_line(self):
        return "Affect: test"

    def drift_without_notify(self):
        reasons.append("drift_computed")
        return "snap"

    def emit(self, snap):
        reasons.append("drift_emitted")


loop.tracker.affect_controller = _Ctl()
loop.client = MagicMock()


def slow_response(**_kw):
    time.sleep(1.6)  # longer than two drift ticks
    return _make_response(f"done {TASK_END_FLAG}")


loop.client.chat.completions.create.side_effect = slow_response

print("idle window (3s, no run active):", flush=True)
time.sleep(3.0)
print("  events while idle:", reasons or "NONE", flush=True)

print("running run() (~1.6s provider call)...", flush=True)
loop.run("hello")
time.sleep(0.1)
print("  events total:", reasons or "NONE", flush=True)

print("post-run idle window (2s):", flush=True)
n_before = len(reasons)
time.sleep(2.0)
print("  new events after turn end:", reasons[n_before:] or "NONE", flush=True)
