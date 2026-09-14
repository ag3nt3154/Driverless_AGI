from __future__ import annotations

import base64
import dataclasses
from pathlib import Path

import pytest

from agent.image_assets import AssetError, ImageAssetStore, ImageRef, materialize_messages
from agent.user_input import ImageAttachment, UserSubmission

# 1x1 transparent PNG.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _attachment(data: bytes = _TINY_PNG, name: str = "Screenshot 1") -> ImageAttachment:
    return ImageAttachment(data=data, mime_type="image/png", width=1, height=1, name=name)


# --- ImageAttachment / UserSubmission -------------------------------------------------


def test_image_attachment_is_frozen() -> None:
    attachment = _attachment()
    with pytest.raises(dataclasses.FrozenInstanceError):
        attachment.name = "other"  # type: ignore[misc]


def test_image_attachment_rejects_bad_mime_type() -> None:
    with pytest.raises(ValueError):
        ImageAttachment(data=_TINY_PNG, mime_type="image/gif", width=1, height=1, name="x")


def test_image_attachment_rejects_nonpositive_dimensions() -> None:
    with pytest.raises(ValueError):
        ImageAttachment(data=_TINY_PNG, mime_type="image/png", width=0, height=1, name="x")


def test_user_submission_text_only() -> None:
    submission = UserSubmission(text="hello")
    assert submission.text == "hello"
    assert submission.images == ()


def test_user_submission_images_only() -> None:
    submission = UserSubmission(text="", images=(_attachment(),))
    assert submission.text == ""
    assert len(submission.images) == 1


def test_user_submission_requires_text_or_images() -> None:
    with pytest.raises(ValueError):
        UserSubmission(text="")


def test_user_submission_is_frozen() -> None:
    submission = UserSubmission(text="hi")
    with pytest.raises(dataclasses.FrozenInstanceError):
        submission.text = "bye"  # type: ignore[misc]


# --- ImageRef round-trip ----------------------------------------------------------------


def test_image_ref_content_part_round_trip() -> None:
    ref = ImageRef(
        sha256="a" * 64,
        mime_type="image/png",
        byte_size=123,
        width=10,
        height=20,
        name="Screenshot 1",
    )
    part = ref.to_content_part()
    assert part["type"] == "dagi_image"
    assert "detail" not in part
    assert ImageRef.from_content_part(part) == ref


def test_image_ref_content_part_includes_detail_when_set() -> None:
    ref = ImageRef(
        sha256="b" * 64, mime_type="image/jpeg", byte_size=1, width=1, height=1,
        name="x", detail="high",
    )
    part = ref.to_content_part()
    assert part["detail"] == "high"
    assert ImageRef.from_content_part(part).detail == "high"


def test_image_ref_from_content_part_rejects_unknown_version() -> None:
    part = {
        "type": "dagi_image", "version": 2, "sha256": "a" * 64, "mime_type": "image/png",
        "byte_size": 1, "width": 1, "height": 1, "name": "x",
    }
    with pytest.raises(ValueError):
        ImageRef.from_content_part(part)


def test_image_ref_from_content_part_rejects_missing_fields() -> None:
    part = {"type": "dagi_image", "version": 1, "sha256": "a" * 64}
    with pytest.raises(ValueError):
        ImageRef.from_content_part(part)


# --- ImageAssetStore ----------------------------------------------------------------------


def test_store_load_exists_round_trip(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    attachment = _attachment()

    ref = store.store(attachment)

    assert ref.byte_size == len(_TINY_PNG)
    assert store.exists(ref)
    assert store.load(ref) == _TINY_PNG
    assert (tmp_path / ".dagi" / "attachments" / f"{ref.sha256}.png").is_file()


def test_store_is_idempotent_for_same_bytes(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    attachment = _attachment()

    ref1 = store.store(attachment)
    ref2 = store.store(attachment)

    assert ref1 == ref2
    files = list((tmp_path / ".dagi" / "attachments").iterdir())
    assert len(files) == 1


def test_materialize_data_url(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = store.store(_attachment())

    url = store.materialize_data_url(ref)

    assert url.startswith("data:image/png;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == _TINY_PNG


def test_load_missing_asset_raises(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = ImageRef(sha256="c" * 64, mime_type="image/png", byte_size=3, width=1, height=1, name="x")

    with pytest.raises(AssetError):
        store.load(ref)


def test_load_detects_hash_mismatch(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = store.store(_attachment())
    # Corrupt the stored bytes without touching the ref metadata.
    path = store.resolve_path(ref)
    path.write_bytes(b"corrupted-data-not-matching-hash")

    with pytest.raises(AssetError):
        store.load(ref)


def test_load_detects_byte_size_mismatch(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = store.store(_attachment())
    tampered = dataclasses.replace(ref, byte_size=ref.byte_size + 100)

    with pytest.raises(AssetError):
        store.load(tampered)


def test_resolve_path_rejects_path_traversal(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    malicious = ImageRef(
        sha256="../../../../etc/passwd", mime_type="image/png", byte_size=1, width=1, height=1, name="x",
    )

    with pytest.raises(AssetError):
        store.resolve_path(malicious)


def test_resolve_path_rejects_malformed_sha256(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    bad = ImageRef(sha256="not-a-hash", mime_type="image/png", byte_size=1, width=1, height=1, name="x")

    with pytest.raises(AssetError):
        store.resolve_path(bad)


def test_exists_false_for_unknown_ref(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = ImageRef(sha256="d" * 64, mime_type="image/png", byte_size=1, width=1, height=1, name="x")

    assert store.exists(ref) is False


# --- materialize_messages ------------------------------------------------------------------


def test_materialize_messages_replaces_dagi_image_parts(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    ref = store.store(_attachment())
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                ref.to_content_part(),
            ],
        }
    ]

    result = materialize_messages(messages, store)

    content = result[0]["content"]
    assert content[0] == {"type": "text", "text": "look at this"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    # Original input is untouched (deep copy).
    assert messages[0]["content"][1]["type"] == "dagi_image"


def test_materialize_messages_preserves_detail(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    attachment = _attachment()
    ref = store.store(attachment)
    ref_with_detail = dataclasses.replace(ref, detail="high")
    messages = [{"role": "user", "content": [ref_with_detail.to_content_part()]}]

    result = materialize_messages(messages, store)

    assert result[0]["content"][0]["image_url"]["detail"] == "high"


def test_materialize_messages_preserves_unrelated_fields(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    messages = [
        {"role": "system", "content": "be helpful"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "foo", "arguments": "{}"}}],
            "reasoning": "thinking hard",
        },
        {"role": "user", "content": "plain text only"},
    ]

    result = materialize_messages(messages, store)

    assert result == messages


def test_store_concurrent_identical_writes(tmp_path: Path) -> None:
    """Multiple threads storing the same bytes concurrently must never leave a
    corrupted or partial file on disk, even though true concurrent-write
    safety (locking/CAS) is explicitly deferred per the module docstring —
    the real-world usage is a single GUI thread, so a losing writer racing on
    the atomic os.replace may raise rather than silently corrupt data.
    Every writer that *does* succeed must agree on the same ref/bytes."""
    import threading

    store = ImageAssetStore(tmp_path)
    attachment = _attachment()
    results: list = []
    errors: list = []

    def _write() -> None:
        try:
            results.append(store.store(attachment))
        except OSError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_write) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) + len(errors) == 8
    assert results, "at least one concurrent writer must succeed"
    assert len(set(results)) == 1  # every successful writer got an identical ImageRef
    files = list((tmp_path / ".dagi" / "attachments").glob("*.png"))
    assert len(files) == 1
    assert files[0].read_bytes() == _TINY_PNG  # never partial/corrupted


def test_load_rejects_symlinked_asset(tmp_path: Path) -> None:
    """load() must refuse a symlink even if it happens to point at valid
    bytes — a symlink at the digest path could otherwise be used to read an
    arbitrary file outside the store."""
    store = ImageAssetStore(tmp_path)
    ref = store.store(_attachment())
    real_path = store.resolve_path(ref)
    outside = tmp_path / "outside.png"
    outside.write_bytes(_TINY_PNG)
    real_path.unlink()
    try:
        real_path.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation not permitted in this environment")

    with pytest.raises(AssetError):
        store.load(ref)


def test_materialize_messages_raises_on_unknown_version(tmp_path: Path) -> None:
    store = ImageAssetStore(tmp_path)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "dagi_image", "version": 99, "sha256": "a" * 64,
                    "mime_type": "image/png", "byte_size": 1, "width": 1, "height": 1, "name": "x",
                }
            ],
        }
    ]

    with pytest.raises(AssetError):
        materialize_messages(messages, store)
