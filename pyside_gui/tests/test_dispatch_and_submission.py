"""Non-Qt coverage for Stage 4: the _dispatch module's pure helpers and the
UserSubmission-building rules PromptInput relies on.

Qt-heavy behavior (actual clipboard paste, thumbnail strip rendering) needs a
running QApplication and is exercised manually / in a full GUI smoke test —
these tests cover what can be verified without one.
"""
from __future__ import annotations

from agent.user_input import ImageAttachment, UserSubmission


def test_dispatch_module_imports() -> None:
    from pyside_gui._dispatch import (
        agent_work,
        dispatch_agent,
        handle_special_command,
        on_input_submitted,
    )

    assert callable(on_input_submitted)
    assert callable(dispatch_agent)
    assert callable(agent_work)
    assert callable(handle_special_command)


def _make_attachment(name: str = "a.png") -> ImageAttachment:
    return ImageAttachment(
        data=b"\x89PNG\r\n\x1a\n" + b"0" * 16,
        mime_type="image/png",
        width=10,
        height=10,
        name=name,
    )


def test_as_submission_wraps_plain_text() -> None:
    from pyside_gui._dispatch import _as_submission

    result = _as_submission("hello")
    assert isinstance(result, UserSubmission)
    assert result.text == "hello"
    assert result.images == ()


def test_as_submission_passes_through_user_submission() -> None:
    from pyside_gui._dispatch import _as_submission

    submission = UserSubmission(text="hi", images=(_make_attachment(),))
    assert _as_submission(submission) is submission


def test_display_text_appends_single_image_suffix() -> None:
    from pyside_gui._dispatch import _display_text

    submission = UserSubmission(text="check this out", images=(_make_attachment(),))
    assert _display_text(submission) == "check this out [1 image]"


def test_display_text_pluralizes_multiple_images() -> None:
    from pyside_gui._dispatch import _display_text

    submission = UserSubmission(
        text="", images=(_make_attachment("a.png"), _make_attachment("b.png"))
    )
    assert _display_text(submission) == "[2 images]"


def test_display_text_plain_text_unchanged() -> None:
    from pyside_gui._dispatch import _display_text

    assert _display_text("just text") == "just text"


def test_user_submission_requires_text_or_images() -> None:
    import pytest

    with pytest.raises(ValueError):
        UserSubmission(text="")


def test_user_submission_accepts_images_only() -> None:
    submission = UserSubmission(text="", images=(_make_attachment(),))
    assert submission.is_valid
