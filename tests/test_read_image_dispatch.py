"""tests/test_read_image_dispatch.py — read on an image through AgentLoop.

The tool message stays text-only; the image rides in a user message logged
after every tool result of the step, and only for a model configured with
``supports_images: true``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent.loop import AgentConfig, AgentLoop

pytest.importorskip("PIL")


def _response(*calls):
    tool_calls = [
        SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        for cid, name, args in calls
    ]
    choice = MagicMock()
    choice.message.content = None
    choice.message.tool_calls = tool_calls
    choice.message.reasoning_content = None
    choice.message.model_extra = {}
    response = MagicMock()
    response.choices = [choice]
    response.usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, cost=None, completion_tokens_details=None,
    )
    return response


def _run_reading(tmp_path, supports_images, *extra_calls):
    from PIL import Image
    Image.new("RGB", (4, 3), "blue").save(tmp_path / "shot.png")
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")

    config = AgentConfig(
        model="test-model", api_key="fake", base_url="http://localhost:1234/v1",
        project_path=tmp_path, supports_images=supports_images,
    )
    fake_tracker = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agent.loop.SessionTracker", MagicMock(return_value=fake_tracker))
        loop = AgentLoop(config)
    loop.tracker = fake_tracker
    loop._generate_session_slug = MagicMock(return_value="a_slug")
    loop.client = MagicMock()
    loop.client.chat.completions.create.side_effect = [
        _response(("tc_read", "read", {"path": "shot.png"}), *extra_calls),
        _response(("tc_end", "write_handoff", {"content": "Done."})),
    ]
    loop.run("look at the screenshot")
    second = loop.client.chat.completions.create.call_args_list[1]
    return second.kwargs["messages"]


def _tool_result(messages, call_id):
    return next(m for m in messages if m.get("tool_call_id") == call_id)


def test_multimodal_model_gets_image_after_tool_results(tmp_path):
    messages = _run_reading(
        tmp_path, True, ("tc_txt", "read", {"path": "notes.txt"}),
    )

    tool_msg = _tool_result(messages, "tc_read")
    assert isinstance(tool_msg["content"], str)
    assert "[Image: shot.png | 4x3 | image/png]" in tool_msg["content"]

    # Image message comes after BOTH tool results, keeping assistant→tool pairing.
    roles = [m["role"] for m in messages]
    last_tool = max(i for i, r in enumerate(roles) if r == "tool")
    image_msg = messages[last_tool + 1]
    assert image_msg["role"] == "user"
    text_part, image_part = image_msg["content"]
    assert "shot.png" in text_part["text"]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert list((tmp_path / ".dagi" / "attachments").glob("*.png"))


@pytest.mark.parametrize("supports_images", [False, None])
def test_non_multimodal_model_gets_cannot_process(tmp_path, supports_images):
    messages = _run_reading(tmp_path, supports_images)

    tool_msg = _tool_result(messages, "tc_read")
    assert tool_msg["content"].startswith("Error (DAGI_CANNOT_PROCESS):")
    assert "supports_images" in tool_msg["content"]
    assert not any(
        isinstance(m.get("content"), list) for m in messages if m["role"] == "user"
    )


def test_current_supports_images_follows_active_tier():
    from agent._model_switch import current_supports_images

    worker = SimpleNamespace(supports_images=True)
    config = SimpleNamespace(supports_images=False, worker_config=worker, advanced_config=None)
    loop = SimpleNamespace(config=config, _current_tier="default")
    assert current_supports_images(loop) is False
    loop._current_tier = "worker"
    assert current_supports_images(loop) is True
    loop._current_tier = "plan"  # not configured → falls back to the base config
    assert current_supports_images(loop) is False
