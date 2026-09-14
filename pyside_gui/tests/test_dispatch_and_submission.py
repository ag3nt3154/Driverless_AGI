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


# --- _append_user_with_images -----------------------------------------------------------


class _FakeConversation:
    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.image_calls: list[tuple[str, list[str]]] = []
        self.errors: list[str] = []

    def append_user_message(self, text: str) -> None:
        self.user_messages.append(text)

    def append_user_message_with_images(self, text: str, image_paths) -> None:
        self.image_calls.append((text, list(image_paths)))

    def append_error(self, text: str) -> None:
        self.errors.append(text)


class _FakeConfig:
    def __init__(self, project_path) -> None:
        self.project_path = project_path


class _FakeWin:
    def __init__(self, project_path) -> None:
        self._conversation = _FakeConversation()
        self._config = _FakeConfig(project_path)


def test_append_user_with_images_stores_and_generates_file_urls(tmp_path) -> None:
    from pyside_gui._dispatch import _append_user_with_images

    win = _FakeWin(tmp_path)
    submission = UserSubmission(text="here", images=(_make_attachment(),))

    _append_user_with_images(win, submission)

    assert not win._conversation.errors
    assert len(win._conversation.image_calls) == 1
    text, paths = win._conversation.image_calls[0]
    assert text == "here"
    assert len(paths) == 1
    assert paths[0].startswith("file:///")
    # The asset store actually persisted the bytes at the referenced path.
    from agent.image_assets import ImageAssetStore

    store = ImageAssetStore(tmp_path)
    stored_files = list((tmp_path / ".dagi" / "attachments").iterdir())
    assert len(stored_files) == 1
    assert stored_files[0].name in paths[0]


def test_append_user_with_images_falls_back_on_asset_error(tmp_path, monkeypatch) -> None:
    from agent.image_assets import AssetError
    from pyside_gui import _dispatch

    class _BrokenStore:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def store(self, *_a, **_kw):
            raise AssetError("disk full")

    monkeypatch.setattr(_dispatch, "ImageAssetStore", _BrokenStore)
    win = _FakeWin(tmp_path)
    submission = UserSubmission(text="here", images=(_make_attachment(),))

    _dispatch._append_user_with_images(win, submission)

    assert len(win._conversation.errors) == 1
    assert "disk full" in win._conversation.errors[0]
    assert not win._conversation.image_calls
    # Falls back to the plain text bubble with the "[N images]" suffix.
    assert win._conversation.user_messages == ["here [1 image]"]


def test_append_user_with_images_text_only_path_unchanged(tmp_path) -> None:
    from pyside_gui._dispatch import _append_user_with_images

    win = _FakeWin(tmp_path)
    submission = UserSubmission(text="just text")

    _append_user_with_images(win, submission)

    assert win._conversation.user_messages == ["just text"]
    assert not win._conversation.image_calls
    assert not win._conversation.errors
    # No asset store directory should be created for a text-only submission.
    assert not (tmp_path / ".dagi").exists()
