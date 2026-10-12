from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timezone

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QPushButton
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


def test_board_view_is_read_only(qtbot):
    view = _view(qtbot)
    assert view.findChildren(QPlainTextEdit) == []
    assert not any(button.text() == "Send" for button in view.findChildren(QPushButton))


def test_connect_menu_switch_action_follows_central_availability(qtbot):
    from PySide6.QtWidgets import QToolButton

    view = _view(qtbot)
    requested = []
    view.connect_requested.connect(lambda *args: requested.append(args))
    view.set_connection("http://127.0.0.1:8765", "http://central:8765")
    action = view._switch_central_action
    assert action.isVisible()
    assert not action.isEnabled()
    view.set_central_available("http://central:8765", True)
    assert action.isEnabled()
    action.trigger()
    assert requested == [("http://central:8765", None)]
    assert view._connect.popupMode() == QToolButton.ToolButtonPopupMode.InstantPopup


def test_connect_menu_another_board_uses_url_dialog(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    view = _view(qtbot)
    requested = []
    view.connect_requested.connect(lambda *args: requested.append(args))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("other:8765", True))
    view._connect_another_action.trigger()
    assert requested == [("http://other:8765", None)]


def test_badge_shows_temp_or_central(qtbot):
    view = _view(qtbot)
    view.set_connection("http://127.0.0.1:8765", "http://central:8765")
    assert view._fallback.text() == "temp"
    assert view._fallback.toolTip() == (
        "Temporary board — http://central:8765 is unreachable; posts here are discarded "
        "when DAGI closes"
    )
    view.set_connection("http://central:8765", None)
    assert view._fallback.text() == "central"
    assert not view._fallback.isHidden()


def test_posts_are_deduped_and_inserted_newest_first(qtbot):
    view = _view(qtbot)
    view.add_post(_post(1))
    view.add_post(_post(1))
    view.add_post(_post(2))
    assert view._posts_layout.count() == 3  # two cards + trailing stretch
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
    assert view._posts_layout.count() == 1  # only the trailing stretch


def test_file_chip_escapes_mnemonic_ampersand(qtbot):
    view = _view(qtbot)
    view.add_post(_post(1, attachments=[_attachment("file", "a&b.txt")]))
    chip = view._cards[1]()._attachments["att_123456789abc"]
    assert chip.text() == "📎 a&&b.txt (10 B)"


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


def test_save_as_copies_downloaded_bytes(qtbot, tmp_path, monkeypatch):
    from pyside_gui.sidebars import board_widgets

    source = tmp_path / "cache" / "notes.txt"
    source.parent.mkdir()
    source.write_bytes(b"attachment bytes")
    future = Future()
    view = _view(qtbot, future)
    attachment = _attachment("file", "notes.txt")
    view.add_post(_post(1, attachments=[attachment]))
    card = view._cards[1]()
    save = card._save_buttons[attachment["id"]]
    assert not save.isEnabled()
    future.set_result(source)
    qtbot.waitUntil(save.isEnabled)
    target = tmp_path / "out" / "copy.txt"
    target.parent.mkdir()
    asked = []

    def choose(parent, title, default):
        asked.append(default)
        return str(target), ""

    monkeypatch.setattr(board_widgets.QFileDialog, "getSaveFileName", choose)
    save.click()
    assert asked == ["notes.txt"]
    assert target.read_bytes() == b"attachment bytes"
    assert save.text().startswith("Saved")


def test_save_as_cancel_and_failed_download(qtbot, tmp_path, monkeypatch):
    from pyside_gui.sidebars import board_widgets

    source = tmp_path / "a.txt"
    source.write_bytes(b"x")
    ok, bad = Future(), Future()
    futures = iter([ok, bad])
    view = _view(qtbot)
    view.set_fetcher(lambda _attachment_id: next(futures))
    first = _attachment("file", "a.txt")
    second = {**_attachment(), "id": "att_222222222222"}
    view.add_post(_post(1, attachments=[first, second]))
    card = view._cards[1]()
    ok.set_result(source)
    bad.set_exception(OSError("disk full"))
    qtbot.waitUntil(lambda: card._save_buttons[first["id"]].isEnabled())
    qtbot.waitUntil(lambda: card._save_buttons[second["id"]].isHidden())
    monkeypatch.setattr(board_widgets.QFileDialog, "getSaveFileName",
                        lambda *args: ("", ""))
    card._save_buttons[first["id"]].click()
    assert card._save_buttons[first["id"]].text() == "Save as…"


def test_wrapped_post_text_grows_when_the_board_narrows(qtbot):
    view = MessageBoardView()
    qtbot.addWidget(view)
    view.resize(520, 900)
    view.show()
    view.add_post(_post(1, text="word " * 120))
    view.resize(300, 900)
    qtbot.wait(50)
    text = next(label for label in view._cards[1]().findChildren(QLabel) if label.wordWrap())
    assert text.height() >= text.heightForWidth(text.width())


def test_clear_posts_keeps_new_posts_at_the_top(qtbot):
    view = MessageBoardView()
    qtbot.addWidget(view)
    view.resize(400, 900)
    view.show()
    view.add_post(_post(1))
    view.clear_posts()
    view.add_post(_post(2, text="short"))
    qtbot.wait(50)
    assert view._cards[2]().y() < 50
