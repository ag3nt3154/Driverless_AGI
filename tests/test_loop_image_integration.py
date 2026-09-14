"""tests/test_loop_image_integration.py — Stage 2 wiring: UserSubmission through
AgentLoop.run()/inject_and_resume(), image storage, and provider-request
materialization.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agent import session_events as sev
from agent.image_assets import ImageAssetStore
from agent.loop import AgentLoop, AgentConfig
from agent.user_input import ImageAttachment, UserSubmission


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_attachment(name="pixel.png") -> ImageAttachment:
    return ImageAttachment(data=PNG_BYTES, mime_type="image/png", width=1, height=1, name=name)


def _end_response():
    """Minimal LLM response that ends the turn via write_handoff."""
    tc = SimpleNamespace(
        id="tc_end",
        function=SimpleNamespace(name="write_handoff", arguments=json.dumps({"content": "Done."})),
    )
    choice = MagicMock()
    choice.message.content = None
    choice.message.tool_calls = [tc]
    choice.message.reasoning_content = None
    choice.message.model_extra = {}
    response = MagicMock()
    response.choices = [choice]
    response.usage = SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, cost=None, completion_tokens_details=None,
    )
    return response


def _make_loop(tmp_path) -> AgentLoop:
    config = AgentConfig(
        model="test-model",
        api_key="fake",
        base_url="http://localhost:1234/v1",
        project_path=tmp_path,
    )
    fake_tracker = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("agent.loop.SessionTracker", MagicMock(return_value=fake_tracker))
        loop = AgentLoop(config)
    loop.tracker = fake_tracker
    loop.client = MagicMock()
    loop.client.chat.completions.create.return_value = _end_response()
    return loop


class TestRunBackwardCompat:
    def test_run_with_string_still_works(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        result = loop.run("Do the thing")
        assert result == "Done."
        loop.tracker.record_user.assert_called_once_with("Do the thing")


class TestRunWithUserSubmission:
    def test_stores_images_and_logs_structured_content(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        attachment = _make_attachment()
        submission = UserSubmission(text="What is this?", images=(attachment,))

        loop.run(submission)

        # Image bytes landed in the project's asset store.
        store = ImageAssetStore(tmp_path)
        import hashlib
        digest = hashlib.sha256(PNG_BYTES).hexdigest()
        stored_path = tmp_path / ".dagi" / "attachments" / f"{digest}.png"
        assert stored_path.is_file()
        assert stored_path.read_bytes() == PNG_BYTES

        # tracker.record_user received structured content (list), not a bare string.
        (content_arg,), _ = loop.tracker.record_user.call_args
        assert isinstance(content_arg, list)
        assert content_arg[0] == {"type": "text", "text": "What is this?"}
        assert content_arg[1]["type"] == "dagi_image"
        assert content_arg[1]["sha256"] == digest

    def test_image_only_no_synthetic_text(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock()
        submission = UserSubmission(text="", images=(_make_attachment(),))

        loop.run(submission)

        (content_arg,), _ = loop.tracker.record_user.call_args
        assert isinstance(content_arg, list)
        # No text part — only the image part.
        assert len(content_arg) == 1
        assert content_arg[0]["type"] == "dagi_image"


class TestSlugForImageOnlySubmission:
    def test_uses_image_conversation_fallback(self, tmp_path):
        loop = _make_loop(tmp_path)
        gen_mock = MagicMock(return_value="should_not_be_called")
        loop._generate_session_slug = gen_mock
        submission = UserSubmission(text="   ", images=(_make_attachment(),))

        loop.run(submission)

        gen_mock.assert_not_called()
        loop.tracker.rename_with_slug.assert_called_once_with("image-conversation")

    def test_text_present_uses_llm_slug(self, tmp_path):
        loop = _make_loop(tmp_path)
        gen_mock = MagicMock(return_value="a_real_slug")
        loop._generate_session_slug = gen_mock
        submission = UserSubmission(text="Describe this image", images=(_make_attachment(),))

        loop.run(submission)

        gen_mock.assert_called_once_with("Describe this image")
        loop.tracker.rename_with_slug.assert_called_once_with("a_real_slug")


class TestBuildRequestMessagesMaterializes:
    def test_dagi_image_parts_become_data_urls(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        submission = UserSubmission(text="look", images=(_make_attachment(),))
        loop.run(submission)

        messages = loop._build_request_messages()
        user_messages = [m for m in messages if m.get("role") == "user"]
        found_image_url = False
        for m in user_messages:
            content = m.get("content")
            if isinstance(content, list):
                for part in content:
                    assert part.get("type") != "dagi_image"
                    if part.get("type") == "image_url":
                        found_image_url = True
                        assert part["image_url"]["url"].startswith("data:image/png;base64,")
        assert found_image_url

    def test_returned_messages_are_independent_copies(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        submission = UserSubmission(text="look", images=(_make_attachment(),))
        loop.run(submission)

        first = loop._build_request_messages()
        first[0]["content"] = "MUTATED"
        second = loop._build_request_messages()
        assert second[0]["content"] != "MUTATED"


class TestInjectAndResume:
    """inject_and_resume() appends into an already-open turn (the paused-checkpoint
    injection path), so these tests open one first, matching real usage."""

    def test_string_still_works(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.log.append(sev.TURN_START, {"turn": loop.log.next_turn()})
        loop.inject_and_resume("hello")
        # inject_and_resume doesn't call tracker.record_user; verify via the log instead.
        messages = loop._messages
        assert any(m.get("role") == "user" and m.get("content") == "hello" for m in messages)

    def test_user_submission_with_images(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop.log.append(sev.TURN_START, {"turn": loop.log.next_turn()})
        submission = UserSubmission(text="context image", images=(_make_attachment(),))
        loop.inject_and_resume(submission)

        messages = loop._messages
        user_msgs = [m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)]
        assert user_msgs, "expected a structured user message with dagi_image content"
        parts = user_msgs[-1]["content"]
        assert any(p.get("type") == "dagi_image" for p in parts)


class TestWirePayloadDetails:
    """Section 10 'Wire payload' group: exact bytes, MIME, part order, multi-image,
    image-only, and text-only-unchanged shape — beyond the single-image happy path
    already covered by TestBuildRequestMessagesMaterializes."""

    def test_exact_png_bytes_round_trip_through_data_url(self, tmp_path):
        import base64

        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        submission = UserSubmission(text="look", images=(_make_attachment(),))
        loop.run(submission)

        messages = loop._build_request_messages()
        image_part = next(
            p for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url"
        )
        url = image_part["image_url"]["url"]
        header, encoded = url.split(",", 1)
        assert header == "data:image/png;base64"
        assert base64.b64decode(encoded) == PNG_BYTES

    def test_mime_type_matches_attachment(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"
        attachment = ImageAttachment(data=jpeg_bytes, mime_type="image/jpeg", width=2, height=2, name="p.jpg")
        submission = UserSubmission(text="look", images=(attachment,))
        loop.run(submission)

        messages = loop._build_request_messages()
        image_part = next(
            p for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url"
        )
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_text_part_precedes_image_parts_in_order(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        submission = UserSubmission(text="caption", images=(_make_attachment("a.png"),))
        loop.run(submission)

        messages = loop._build_request_messages()
        user_msg = next(
            m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
        )
        types = [p["type"] for p in user_msg["content"]]
        assert types == ["text", "image_url"]

    def test_multiple_images_all_materialize(self, tmp_path):
        import base64

        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        data_a = PNG_BYTES
        data_b = PNG_BYTES + b"\x00"  # distinct bytes -> distinct hash
        att_a = ImageAttachment(data=data_a, mime_type="image/png", width=1, height=1, name="a.png")
        att_b = ImageAttachment(data=data_b, mime_type="image/png", width=1, height=1, name="b.png")
        submission = UserSubmission(text="two images", images=(att_a, att_b))
        loop.run(submission)

        messages = loop._build_request_messages()
        user_msg = next(
            m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
        )
        image_urls = [p["image_url"]["url"] for p in user_msg["content"] if p["type"] == "image_url"]
        assert len(image_urls) == 2
        decoded = {base64.b64decode(u.split(",", 1)[1]) for u in image_urls}
        assert decoded == {data_a, data_b}

    def test_image_only_message_has_no_text_part(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock()
        submission = UserSubmission(text="", images=(_make_attachment(),))
        loop.run(submission)

        messages = loop._build_request_messages()
        user_msg = next(
            m for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
        )
        assert [p["type"] for p in user_msg["content"]] == ["image_url"]

    def test_text_only_message_shape_is_unchanged_string(self, tmp_path):
        loop = _make_loop(tmp_path)
        loop._generate_session_slug = MagicMock(return_value="a_slug")
        loop.run("just plain text, no images")

        messages = loop._build_request_messages()
        user_msg = next(m for m in messages if m.get("role") == "user")
        assert isinstance(user_msg["content"], str)
        assert user_msg["content"] == "just plain text, no images"


class TestPersistenceRoundTrip:
    """Section 10 'Persistence' group: store -> log -> reload -> materialize
    reproduces identical bytes, and the store does not depend on the original
    in-memory attachment surviving."""

    def test_round_trip_after_resume_yields_identical_bytes(self, tmp_path):
        import base64

        original_loop = _make_loop(tmp_path)
        original_loop._generate_session_slug = MagicMock(return_value="a_slug")
        submission = UserSubmission(text="remember this", images=(_make_attachment(),))
        original_loop.run(submission)

        # Simulate the "original source removed" case: nothing but the stored
        # copy in .dagi/attachments and the seeded messages is used below —
        # `submission`/`attachment` going out of scope models the clipboard
        # being cleared and the source file being deleted.
        seed_messages = [{"role": "system", "content": "sys"}] + list(original_loop._messages)
        del submission

        resumed_loop = _make_loop(tmp_path)
        resumed_loop._messages = []
        resumed_loop._seed_from_messages(seed_messages)
        resumed_loop._sync_messages()

        messages = resumed_loop._build_request_messages()
        image_part = next(
            p for m in messages if m.get("role") == "user" and isinstance(m.get("content"), list)
            for p in m["content"] if p.get("type") == "image_url"
        )
        encoded = image_part["image_url"]["url"].split(",", 1)[1]
        assert base64.b64decode(encoded) == PNG_BYTES

    def test_store_independent_of_original_attachment_object(self, tmp_path):
        store = ImageAssetStore(tmp_path)
        attachment = _make_attachment()
        ref = store.store(attachment)
        del attachment

        # A brand-new store instance (fresh process/session simulation) still
        # reads back identical bytes purely from disk.
        reloaded_store = ImageAssetStore(tmp_path)
        assert reloaded_store.load(ref) == PNG_BYTES


class TestRecordUserAcceptsStrOrList:
    def test_accepts_string(self, tmp_path):
        from agent.session import SessionTracker

        tracker = SessionTracker(model="m", logs_dir=tmp_path / "logs")
        tracker.record_user("plain text")
        assert tracker._messages[-1].content == "plain text"

    def test_accepts_list(self, tmp_path):
        from agent.session import SessionTracker

        tracker = SessionTracker(model="m", logs_dir=tmp_path / "logs")
        content = [{"type": "text", "text": "hi"}, {"type": "dagi_image", "sha256": "a" * 64}]
        tracker.record_user(content)
        assert tracker._messages[-1].content == content
