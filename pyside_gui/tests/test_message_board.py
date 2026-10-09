from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel
from shiboken6 import isValid

from agent.board_client import BoardError
from pyside_gui.sidebars.board_widgets import PostCard
from pyside_gui.sidebars.message_board import MessageBoardView

_SHA = "ab" * 32
# 1x1 GIF89a, the smallest valid animated-format image.
_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x00\x00\x00"
    b"\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


def _post(post_id=1, *, attachments=None, **overrides):
    post = {
        "id": post_id,
        "author": "main_12345678",
        "text": "hello <b>world</b>",
        "mentions": [],
        "meme": None,
        "reply_to": None,
        "attachments": attachments or [],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    post.update(overrides)
    return post


def _attachment(kind="file", name="x.txt"):
    return {"id": "att_123456789abc", "name": name, "size": 10, "kind": kind,
            "sha256": _SHA}


def _view(qtbot, future=None):
    view = MessageBoardView()
    qtbot.addWidget(view)
    if future is not None:
        view.set_fetcher(lambda _attachment_id: future)
    return view


def test_composer_blocks_empty_and_overlong_text(qtbot):
    view = _view(qtbot)
    sent = []
    view.set_poster(lambda text, paths: sent.append((text, paths)) or True)
    assert not view._send_button.isEnabled()
    view._input.setText("x" * 701)
    assert view._count.text() == "701/700"
    assert not view._send_button.isEnabled()
    view._send()
    assert sent == []


def test_composer_ignores_whitespace_only_text(qtbot):
    view = _view(qtbot)
    sent = []
    view.set_poster(lambda text, paths: sent.append((text, paths)) or True)
    view._input.setText("   \t ")
    assert view._count.text() == "5/700"
    assert not view._send_button.isEnabled()
    view._send()
    assert sent == []


def test_composer_sends_and_clears_valid_files(qtbot, tmp_path):
    view = _view(qtbot)
    path = tmp_path / "note.txt"
    path.write_text("note", encoding="utf-8")
    sent = []
    view.set_poster(lambda text, paths: sent.append((text, paths)) or True)
    view.add_files([path])
    view._input.setText("hello")
    view._send()
    assert sent == [("hello", [path])]
    assert view._input.text() == ""
    assert view._paths == []


def test_attachment_count_and_size_are_refused(qtbot, tmp_path):
    view = _view(qtbot)
    paths = []
    for index in range(5):
        path = tmp_path / str(index)
        path.write_bytes(b"x")
        paths.append(path)
    view.add_files(paths)
    assert len(view._paths) == 4
    assert "at most 4" in view._status.text()
    large = tmp_path / "large"
    large.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    other = _view(qtbot)
    other.add_files([large])
    assert other._paths == []
    assert "10 MB" in other._status.text()


def test_add_files_uses_shared_file_checker(qtbot, tmp_path, monkeypatch):
    path = tmp_path / "ok.txt"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "pyside_gui.sidebars.message_board.check_user_file", lambda _path: "shared refusal",
    )
    view = _view(qtbot)
    view.add_files([path])
    assert view._paths == []
    assert view._status.text() == "shared refusal"


def test_posts_are_deduped_and_inserted_newest_first(qtbot):
    view = _view(qtbot)
    view.add_post(_post(1))
    view.add_post(_post(1))
    view.add_post(_post(2))
    assert view._posts_layout.count() == 2
    assert view._posts_layout.itemAt(0).widget() is view._cards[2]()


def test_malformed_post_still_renders_and_later_posts_work(qtbot):
    view = _view(qtbot)
    view.add_post(_post(1, created_at=None, text=123, author=None, meme=["x"]))
    view.add_post(_post(2, created_at="not a time"))
    view.add_post(_post(3))
    assert set(view._cards) == {1, 2, 3}
    for post_id in (1, 2):
        texts = [label.text() for label in view._cards[post_id]().findChildren(QLabel)]
        assert "unknown time" in texts


def test_invalid_attachment_metadata_is_dropped_without_crashing(qtbot):
    future = Future()
    view = _view(qtbot, future)
    bad = {**_attachment(), "sha256": "not-a-digest"}
    view.add_post(_post(1, attachments=[bad, "junk"]))
    assert view._cards[1]()._attachments == {}


def test_download_completion_updates_card_and_opens_image(qtbot, tmp_path):
    image_path = tmp_path / "sample.png"
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(0xFF00FF)
    assert image.save(str(image_path))
    future = Future()
    future.set_result(image_path)
    view = _view(qtbot, future)
    opened = []
    view.open_file_requested.connect(opened.append)
    attachment = _attachment("image", "sample.png")
    view.add_post(_post(1, attachments=[attachment]))
    label = view._cards[1]()._attachments[attachment["id"]]
    qtbot.waitUntil(lambda: not label.pixmap().isNull())
    assert label.pixmap().size() == QSize(4, 4)
    label.mousePressEvent(None)
    assert opened == [str(image_path)]


def test_failed_download_shows_plain_text_error(qtbot):
    image_future, file_future = Future(), Future()
    futures = iter([image_future, file_future])
    view = _view(qtbot)
    view.set_fetcher(lambda _attachment_id: next(futures))
    image = _attachment("image", "a.png")
    other = {**_attachment(), "id": "att_222222222222"}
    view.add_post(_post(1, attachments=[image, other]))
    image_future.set_exception(BoardError("NOT_FOUND", "<b>gone</b>"))
    file_future.set_exception(OSError("disk full"))
    card = view._cards[1]()
    qtbot.waitUntil(lambda: "Download failed" in card._attachments[image["id"]].text())
    assert card._attachments[image["id"]].text() == "Download failed — <b>gone</b>"
    qtbot.waitUntil(lambda: "Download failed" in card._attachments[other["id"]].text())
    assert card._attachments[other["id"]].text() == "Download failed — disk full"


def test_cancelled_download_stays_silent(qtbot, monkeypatch):
    future = Future()
    view = _view(qtbot, future)
    attachment = _attachment("image", "a.png")
    view.add_post(_post(1, attachments=[attachment]))
    calls = _record_card_updates(monkeypatch)
    future.cancel()
    qtbot.wait(20)
    assert calls == []


def test_download_failure_after_close_stays_silent(qtbot, monkeypatch):
    future = Future()
    view = _view(qtbot, future)
    attachment = _attachment("image", "a.png")
    view.add_post(_post(1, attachments=[attachment]))
    calls = _record_card_updates(monkeypatch)
    view.close_downloads()
    future.set_exception(OSError("cancelled by close"))
    qtbot.wait(20)
    assert calls == []


def test_non_dict_post_is_ignored(qtbot):
    view = _view(qtbot)
    for junk in ("x", None, 7, ["id", 1]):
        view.add_post(junk)
    assert view._cards == {}
    assert view._posts_layout.count() == 0


def test_file_chip_escapes_mnemonic_ampersand(qtbot):
    view = _view(qtbot)
    view.add_post(_post(1, attachments=[_attachment("file", "a&b.txt")]))
    chip = view._cards[1]()._attachments["att_123456789abc"]
    assert chip.text() == "📎 a&&b.txt (10 B)"


def test_send_keeps_text_and_chips_when_poster_refuses(qtbot, tmp_path):
    view = _view(qtbot)
    path = tmp_path / "note.txt"
    path.write_text("note", encoding="utf-8")
    sent = []

    def refuse(text, paths):
        sent.append((text, paths))
        return False

    view.set_poster(refuse)
    view.add_files([path])
    view._input.setText("hello")
    view._send()
    assert sent == [("hello", [path])]
    assert view._input.text() == "hello"
    assert view._paths == [path]


def _record_card_updates(monkeypatch) -> list:
    calls = []
    for name in ("attachment_ready", "attachment_failed"):
        monkeypatch.setattr(PostCard, name, lambda *args, n=name: calls.append(n))
    return calls


def test_late_download_after_card_destruction_is_ignored(qtbot, monkeypatch):
    future = Future()
    view = _view(qtbot, future)
    attachment = _attachment()
    view.add_post(_post(1, attachments=[attachment]))
    card = view._cards[1]()
    assert attachment["id"] in card._attachments
    calls = _record_card_updates(monkeypatch)
    card.deleteLater()  # keep the Python wrapper alive so only isValid() can tell
    qtbot.waitUntil(lambda: not isValid(card))
    assert view._cards[1]() is card
    future.set_result("x.txt")
    qtbot.wait(20)
    assert calls == []


def test_late_download_after_view_close_is_ignored(qtbot, monkeypatch):
    future = Future()
    view = _view(qtbot, future)
    attachment = _attachment()
    view.add_post(_post(1, attachments=[attachment]))
    assert attachment["id"] in view._cards[1]()._attachments
    calls = _record_card_updates(monkeypatch)
    view.close_downloads()
    future.set_result("x.txt")
    qtbot.wait(20)
    assert calls == []


def _meme_label(view, post_id=1) -> QLabel:
    return view._cards[post_id]().findChild(QLabel, "meme-placeholder")


def test_gif_meme_is_animated_and_scaled_to_fit(qtbot, tmp_path):
    gif = tmp_path / "wave.gif"
    gif.write_bytes(_GIF)
    view = _view(qtbot)
    view._memes = {"wave": gif}
    view.add_post(_post(1, meme="wave"))
    movie = _meme_label(view).movie()
    assert movie is not None
    assert movie.scaledSize() == QSize(140, 140)


def test_gif_meme_over_limits_is_not_animated(qtbot, tmp_path, monkeypatch):
    gif = tmp_path / "wave.gif"
    gif.write_bytes(_GIF)
    monkeypatch.setattr("pyside_gui.image_preview.MAX_IMAGE_BYTES", 8)
    view = _view(qtbot)
    view._memes = {"wave": gif}
    view.add_post(_post(1, meme="wave"))
    label = _meme_label(view)
    assert label.movie() is None
    assert label.text() == "[wave]"


def test_png_meme_uses_static_preview(qtbot, tmp_path):
    png = tmp_path / "wave.png"
    image = QImage(4, 2, QImage.Format.Format_RGB32)
    image.fill(0x00FF00)
    assert image.save(str(png))
    view = _view(qtbot)
    view._memes = {"wave": png}
    view.add_post(_post(1, meme="wave"))
    label = _meme_label(view)
    assert label.movie() is None
    assert not label.pixmap().isNull()
