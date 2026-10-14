from __future__ import annotations

import pytest

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import

from pyside_gui.sidebars.settings_view import SettingsView

_KEY_ENV = "DAGI_TEST_SETTINGS_KEY"
_CONFIG = (
    "# Main config\n"
    "default_model: m1   # the model\n"
    "context_window: 1000\n"
    "tools:\n"
    "  - read\n"
    "  # - bash\n"
)


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    models = tmp_path / "model_config"
    models.mkdir()
    (models / "m1.yaml").write_text(
        f"name: m1\nmodel: m1\napi_url: https://x.test/v1\napi_key_env: {_KEY_ENV}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(_KEY_ENV, "secret")
    path = tmp_path / "config.yaml"
    path.write_bytes(_CONFIG.encode("utf-8"))
    return path


@pytest.fixture
def view(qtbot, config_path):
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    return w


def _open_raw(view) -> None:
    view._tabs.setCurrentIndex(view._raw_index)


def _set_raw(view, text: str) -> None:
    _open_raw(view)
    view._raw.setPlainText(text)


def test_loads_disk_text_clean(view):
    assert view._raw.toPlainText() == _CONFIG
    assert not view.is_dirty()
    assert not view._dirty_dot.isVisibleTo(view)
    assert view._banner_wrap.isHidden()


def test_editing_raw_marks_dirty_and_emits(view, qtbot):
    with qtbot.waitSignal(view.dirty_changed) as blocker:
        _set_raw(view, _CONFIG + "reserve_tokens: 5\n")
    assert blocker.args == [True]
    assert view.is_dirty()
    assert view._dirty_dot.isVisibleTo(view)


def test_invalid_yaml_blocks_tab_switch(view):
    _set_raw(view, "default_model: [unclosed\n")
    view._tabs.setCurrentIndex(view._form_index)
    assert view._tabs.currentIndex() == view._raw_index
    assert not view._banner_wrap.isHidden()
    assert "line" in view._banner_label.text().lower()


def test_valid_raw_switch_updates_document(view):
    _set_raw(view, _CONFIG.replace("1000", "2000"))
    view._tabs.setCurrentIndex(view._form_index)
    assert view._tabs.currentIndex() == view._form_index
    assert view._doc.get("context_window") == 2000
    assert view.is_dirty()


def test_invalid_yaml_blocks_save(view, config_path):
    _set_raw(view, "default_model: [unclosed\n")
    view._save_btn.click()
    assert config_path.read_text(encoding="utf-8") == _CONFIG
    assert view.is_dirty()
    assert "line" in view._banner_label.text().lower()


def test_validation_error_writes_nothing(view, config_path):
    _set_raw(view, _CONFIG.replace("default_model: m1", "default_model: nope"))
    view._save_btn.click()
    assert config_path.read_text(encoding="utf-8") == _CONFIG
    assert view.is_dirty()
    assert "nope" in view._banner_label.text()


def test_valid_save_writes_and_clears_dirty(view, config_path, qtbot):
    edited = _CONFIG.replace("1000", "2000")
    _set_raw(view, edited)
    with qtbot.waitSignal(view.dirty_changed) as blocker:
        view._save_btn.click()
    assert blocker.args == [False]
    assert config_path.read_text(encoding="utf-8") == edited
    assert not view.is_dirty()
    assert "Saved." in view._banner_label.text()
    view._banner_timer.timeout.emit()
    assert view._banner_wrap.isHidden()


def test_save_preserves_crlf(tmp_path, config_path, qtbot):
    config_path.write_bytes(_CONFIG.replace("\n", "\r\n").encode("utf-8"))
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    _set_raw(w, _CONFIG.replace("1000", "2000"))
    w._save_btn.click()
    assert config_path.read_bytes() == _CONFIG.replace("1000", "2000").replace(
        "\n", "\r\n").encode("utf-8")


def test_warnings_do_not_block_save(view, config_path):
    edited = _CONFIG.replace("  - read\n", "  - read\n  - no_such_tool\n")
    _set_raw(view, edited)
    view._save_btn.click()
    assert config_path.read_text(encoding="utf-8") == edited
    assert not view.is_dirty()
    assert "Unknown tool: no_such_tool" in view._banner_label.text()


def test_revert_restores_disk_text(view):
    _set_raw(view, "context_window: 5\n")
    view._revert_btn.click()
    assert view._raw.toPlainText() == _CONFIG
    assert not view.is_dirty()
    assert view._doc.get("context_window") == 1000


def test_reload_does_not_mark_dirty(view, config_path, qtbot):
    config_path.write_text(_CONFIG + "reserve_tokens: 7\n", encoding="utf-8")
    view.reload()
    assert "reserve_tokens: 7" in view._raw.toPlainText()
    assert not view.is_dirty()


def _make_conflict(view, config_path) -> str:
    external = _CONFIG + "# external edit\n"
    config_path.write_text(external, encoding="utf-8")
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    view._save_btn.click()
    return external


def test_conflict_shows_reload_and_overwrite(view, config_path):
    external = _make_conflict(view, config_path)
    assert config_path.read_text(encoding="utf-8") == external
    assert view.is_dirty()
    assert not view._reload_btn.isHidden()
    assert not view._overwrite_btn.isHidden()


def test_conflict_reload_discards_edits(view, config_path):
    external = _make_conflict(view, config_path)
    view._reload_btn.click()
    assert view._raw.toPlainText() == external
    assert not view.is_dirty()
    assert view._reload_btn.isHidden()


def test_conflict_overwrite_forces_save(view, config_path):
    _make_conflict(view, config_path)
    view._overwrite_btn.click()
    assert config_path.read_text(encoding="utf-8") == _CONFIG.replace("1000", "3000")
    assert not view.is_dirty()
    assert view._overwrite_btn.isHidden()


def test_invalid_disk_file_opens_raw_with_error(config_path, qtbot):
    config_path.write_text("a: [broken\n", encoding="utf-8")
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    assert w._raw.toPlainText() == "a: [broken\n"
    assert w._tabs.currentIndex() == w._raw_index
    assert not w._banner_wrap.isHidden()
    assert not w.is_dirty()


def test_invalid_disk_file_save_and_form_switch_leave_disk_unchanged(config_path, qtbot):
    original = b"a: [broken\r\n# note\r\n"
    config_path.write_bytes(original)
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    w._save_btn.click()
    assert config_path.read_bytes() == original
    w._tabs.setCurrentIndex(w._form_index)
    assert w._tabs.currentIndex() == w._raw_index
    w._save_btn.click()
    assert config_path.read_bytes() == original
    assert "line" in w._banner_label.text().lower()


def test_fixed_invalid_disk_file_saves_with_its_line_endings(config_path, qtbot):
    config_path.write_bytes(_CONFIG.replace("m1", "[m1").replace("\n", "\r\n").encode())
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    _set_raw(w, _CONFIG)
    w._save_btn.click()
    assert config_path.read_bytes() == _CONFIG.replace("\n", "\r\n").encode()
    assert not w.is_dirty()


def test_undecodable_file_shows_error_and_never_writes(config_path, qtbot):
    original = "default_model: m1  # café\n".encode("cp1252")
    config_path.write_bytes(original)
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    assert not w._banner_wrap.isHidden()
    assert "Could not read" in w._banner_label.text()
    assert not w._save_btn.isEnabled()
    assert w._raw.isReadOnly()
    w._save(force=False)
    w._save(force=True)  # the Overwrite path
    w._tabs.setCurrentIndex(w._form_index)
    w._save(force=False)
    assert config_path.read_bytes() == original
    # Once the file is fixed, Revert unlocks the view.
    config_path.write_text(_CONFIG, encoding="utf-8")
    w._revert_btn.click()
    assert w._save_btn.isEnabled()
    assert not w._raw.isReadOnly()
    assert w._raw.toPlainText() == _CONFIG


def test_overwrite_with_validation_error_writes_nothing(view, config_path):
    external = _make_conflict(view, config_path)
    _set_raw(view, _CONFIG.replace("default_model: m1", "default_model: nope"))
    view._overwrite_btn.click()
    assert config_path.read_text(encoding="utf-8") == external
    assert view.is_dirty()
    assert "nope" in view._banner_label.text()


def test_tab_round_trip_without_edits_stays_clean(view, qtbot):
    with qtbot.assertNotEmitted(view.dirty_changed):
        _open_raw(view)
        view._tabs.setCurrentIndex(view._form_index)
        _open_raw(view)
    assert not view.is_dirty()
    assert view._raw.toPlainText() == _CONFIG


def test_missing_file_loads_empty(tmp_path, qtbot):
    w = SettingsView(tmp_path / "absent.yaml")
    qtbot.addWidget(w)
    assert w._raw.toPlainText() == ""
    assert not w.is_dirty()
