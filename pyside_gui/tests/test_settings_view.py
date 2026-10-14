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
    (models / "m2.yaml").write_text(
        f"name: m2\nmodel: m2\napi_url: https://x.test/v1\napi_key_env: {_KEY_ENV}\n",
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


# ── Form tab ──


def _form_view(qtbot, config_path, text: str) -> SettingsView:
    config_path.write_text(text, encoding="utf-8")
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    return w


def _select_data(combo, value) -> None:
    combo.setCurrentIndex(combo.findData(value))


def test_form_populates_from_doc_without_marking_dirty(config_path, qtbot):
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    assert w._spins["context_window"].value() == 1000
    assert w._model_combos["default_model"].currentData() == "m1"
    with qtbot.assertNotEmitted(w.dirty_changed):
        _open_raw(w)
        w._tabs.setCurrentIndex(w._form_index)
        w.reload()
    assert not w.is_dirty()
    assert w._doc.text() == _CONFIG


def test_absent_keys_show_loader_defaults_and_are_not_written(view):
    assert view._spins["reserve_tokens"].value() == 16_384
    assert view._spins["keep_recent_tokens"].value() == 20_000
    assert view._spins["null_response_retries"].value() == 3
    assert view._checks["code_mode"].isChecked()
    assert not view._checks["sandbox_mode"].isChecked()
    assert view._model_combos["worker_model"].currentIndex() == 0
    assert view._doc.text() == _CONFIG


def test_spinbox_writes_doc_and_marks_dirty(view):
    view._spins["context_window"].setValue(2000)
    assert "context_window: 2000\n" in view._doc.text()
    assert view.is_dirty()
    view._spins["api_error_retries"].setValue(5)
    assert view._doc.get("api_error_retries") == 5


def test_checkbox_writes_bool(view):
    view._checks["code_mode"].setChecked(False)
    assert "code_mode: false" in view._doc.text()
    assert view.is_dirty()


def test_default_model_combo_keeps_inline_comment(view):
    _select_data(view._model_combos["default_model"], "m2")
    assert "default_model: m2   # the model\n" in view._doc.text()
    assert view.is_dirty()


def test_same_as_default_deletes_worker_model(config_path, qtbot):
    w = _form_view(qtbot, config_path, _CONFIG + "worker_model: m2\n")
    combo = w._model_combos["worker_model"]
    assert combo.currentData() == "m2"
    combo.setCurrentIndex(0)
    assert w._doc.get("worker_model") is None
    assert "worker_model" not in w._doc.text()


def test_unknown_model_shown_as_missing(config_path, qtbot):
    w = _form_view(qtbot, config_path, _CONFIG.replace("default_model: m1", "default_model: ghost"))
    assert w._model_combos["default_model"].currentText() == "ghost (missing)"
    assert not w.is_dirty()


def test_unchecking_tool_comments_its_line(view):
    view._tool_checks["read"].setChecked(False)
    assert "  # - read\n" in view._doc.text()
    view._tool_checks["bash"].setChecked(True)
    assert "  - bash\n" in view._doc.text()
    assert view.is_dirty()


def test_tool_checklist_order_and_unknown_tag(config_path, qtbot):
    w = _form_view(qtbot, config_path, _CONFIG + "  - mystery\n")
    names = list(w._tool_checks)
    assert names[:3] == ["read", "bash", "mystery"]
    rest = names[3:]
    assert rest == sorted(rest) and "read" not in rest
    assert "unknown" in w._tool_checks["mystery"].text()
    assert "unknown" not in w._tool_checks["read"].text()


def test_tools_key_absent_unchecking_edits_disabled_tools(config_path, qtbot):
    w = _form_view(qtbot, config_path, "default_model: m1\n")
    assert "disabled_tools" in w._tools_note.text()
    assert not w._tools_note.isHidden()
    assert all(cb.isChecked() for cb in w._tool_checks.values())
    w._tool_checks["bash"].setChecked(False)
    text = w._doc.text()
    assert "tools:" not in text.replace("disabled_tools:", "")
    assert "disabled_tools:\n  - bash\n" in text
    assert w._disabled_checks["bash"].isChecked()
    assert w.is_dirty()
    w._tool_checks["bash"].setChecked(True)
    assert dict(w._doc.list_items("disabled_tools"))["bash"] is False
    assert not w._disabled_checks["bash"].isChecked()
    assert "tools:" not in w._doc.text().replace("disabled_tools:", "")


def test_tools_key_absent_reflects_and_follows_disabled_section(config_path, qtbot):
    w = _form_view(qtbot, config_path, "default_model: m1\ndisabled_tools:\n  - bash\n")
    assert not w._tool_checks["bash"].isChecked()
    assert w._tool_checks["read"].isChecked()
    w._disabled_checks["read"].setChecked(True)
    assert not w._tool_checks["read"].isChecked()
    assert "tools:" not in w._doc.text().replace("disabled_tools:", "")


def test_tools_null_shows_all_and_locks_checklist(config_path, qtbot):
    w = _form_view(qtbot, config_path, "default_model: m1\ntools:\n")
    assert "null" in w._tools_note.text()
    assert all(cb.isChecked() for cb in w._tool_checks.values())
    assert not w._tools_list.isEnabled()


def test_tools_all_commented_is_an_editable_list(config_path, qtbot):
    w = _form_view(qtbot, config_path, "default_model: m1\ntools:\n  # - read\n")
    assert w._tools_list.isEnabled()
    assert not w._tool_checks["read"].isChecked()
    w._tool_checks["read"].setChecked(True)
    assert "tools:\n  - read\n" in w._doc.text()


def test_spin_out_of_range_or_non_int_file_value_is_flagged(config_path, qtbot):
    text = _CONFIG.replace("context_window: 1000", "context_window: lots") + "reserve_tokens: 0\n"
    w = _form_view(qtbot, config_path, text)
    assert not w._spin_warnings["context_window"].isHidden()
    assert "lots" in w._spin_warnings["context_window"].text()
    assert "0" in w._spin_warnings["reserve_tokens"].text()
    assert not w._spin_warnings["reserve_tokens"].isHidden()
    assert w._spin_warnings["keep_recent_tokens"].isHidden()
    assert w._doc.text() == text
    assert not w.is_dirty()
    w._spins["context_window"].setValue(5000)
    assert w._doc.get("context_window") == 5000
    assert w._spin_warnings["context_window"].isHidden()


_CU_TOOL = "computer_use_list_windows"


def test_computer_use_tools_locked_while_computer_use_on(config_path, qtbot):
    w = _form_view(qtbot, config_path, _CONFIG + "computer_use: true\n")
    assert not w._tool_checks[_CU_TOOL].isEnabled()
    assert "computer_use" in w._tool_checks[_CU_TOOL].toolTip()
    assert w._tool_checks["read"].isEnabled()
    w._checks["computer_use"].setChecked(False)
    assert w._tool_checks[_CU_TOOL].isEnabled()
    w._checks["computer_use"].setChecked(True)
    assert not w._tool_checks[_CU_TOOL].isEnabled()


def test_computer_use_tools_editable_when_tools_absent(config_path, qtbot):
    w = _form_view(qtbot, config_path, "default_model: m1\ncomputer_use: true\n")
    assert w._tool_checks[_CU_TOOL].isEnabled()


def test_failed_text_commit_repopulates_field(config_path, qtbot):
    w = _form_view(qtbot, config_path, _CONFIG + "services: plain\n")
    url = w._text_fields["services.message_board.url"]
    url.setText("http://h:1")
    url.editingFinished.emit()
    assert not w._banner_wrap.isHidden()
    assert url.text() == ""
    assert not w.is_dirty()


def test_disabled_tools_collapsed_and_toggle(view):
    assert view._disabled_box.isHidden()
    view._disabled_toggle.click()
    assert not view._disabled_box.isHidden()
    view._disabled_checks["bash"].setChecked(True)
    assert "disabled_tools:\n  - bash\n" in view._doc.text()


def test_form_to_raw_shows_updated_text(view):
    view._spins["context_window"].setValue(4321)
    _open_raw(view)
    assert "context_window: 4321" in view._raw.toPlainText()


def test_memory_root_commits_on_editing_finished_and_clear_deletes(view, tmp_path):
    field = view._text_fields["memory_root"]
    field.setText(str(tmp_path))
    assert view._doc.get("memory_root") is None  # not written per keystroke
    field.editingFinished.emit()
    assert view._doc.get("memory_root") == str(tmp_path)
    field.setText("")
    field.editingFinished.emit()
    assert "memory_root" not in view._doc.text()


def test_memory_root_browse(view, tmp_path, monkeypatch):
    from pyside_gui.sidebars import settings_view as sv

    monkeypatch.setattr(
        sv.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    view._browse_btn.click()
    assert view._doc.get("memory_root") == str(tmp_path)
    assert view._text_fields["memory_root"].text() == str(tmp_path)
    assert view.is_dirty()


def test_board_fields_write_nested_keys(view):
    url = view._text_fields["services.message_board.url"]
    url.setText("http://h:1")
    url.editingFinished.emit()
    assert view._doc.get("services.message_board.url") == "http://h:1"
    url.setText("")
    url.editingFinished.emit()
    assert view._doc.get("services") is None


def test_unchanged_text_commit_does_not_mark_dirty(view):
    view._text_fields["services.message_board.bind"].editingFinished.emit()
    assert not view.is_dirty()


def test_form_disabled_while_unreadable(config_path, qtbot):
    config_path.write_bytes("default_model: m1  # caf\xe9\n".encode("cp1252"))
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    assert not w._form_body.isEnabled()
    config_path.write_text(_CONFIG, encoding="utf-8")
    w._revert_btn.click()
    assert w._form_body.isEnabled()


# ── File watcher / conflict banner ──


_EXTERNAL = _CONFIG + "reserve_tokens: 7\n"


def _count_reloads(view, monkeypatch) -> list[int]:
    calls: list[int] = []
    original = view.reload

    def counting() -> None:
        calls.append(1)
        original()

    monkeypatch.setattr(view, "reload", counting)
    return calls


def _conflict_shown(view) -> bool:
    return (
        not view._banner_wrap.isHidden()
        and "config.yaml changed on disk." in view._banner_label.text()
        and not view._reload_btn.isHidden()
        and not view._overwrite_btn.isHidden()
    )


def test_watcher_watches_config_path(view, config_path):
    assert str(config_path) in view._watcher.files()
    # The directory is watched only while the file is missing (a directory
    # watch next to the file makes os.replace fail intermittently on Windows).
    assert view._watcher.directories() == []


def test_directory_watched_only_while_file_missing(view, config_path):
    config_path.unlink()
    view._check_disk()
    assert str(config_path.parent) in view._watcher.directories()
    config_path.write_text(_CONFIG, encoding="utf-8")
    view._check_disk()
    assert str(config_path) in view._watcher.files()
    assert view._watcher.directories() == []


def test_missing_file_at_start_is_picked_up_when_created(tmp_path, qtbot):
    path = tmp_path / "config.yaml"
    w = SettingsView(path)
    qtbot.addWidget(w)
    assert str(tmp_path) in w._watcher.directories()
    path.write_text("context_window: 5\n", encoding="utf-8")
    qtbot.waitUntil(lambda: w._doc.get("context_window") == 5, timeout=5000)
    assert str(path) in w._watcher.files()
    assert w._watcher.directories() == []


def test_many_saves_with_real_watcher_all_succeed(view, config_path, qtbot):
    for i in range(30):
        edited = _CONFIG.replace("1000", str(2000 + i))
        _set_raw(view, edited)
        view._save_btn.click()
        assert not view.is_dirty(), view._banner_label.text()
        assert config_path.read_text(encoding="utf-8") == edited
        qtbot.wait(20)  # let watcher events run between saves
    qtbot.wait(400)
    assert view._banner_label.text() == "Saved."
    assert str(config_path) in view._watcher.files()


def test_pending_text_edit_makes_external_change_a_conflict(view, config_path):
    field = view._text_fields["services.message_board.url"]
    field.setText("http://h:1")  # typed, not yet committed (no editingFinished)
    assert not view.is_dirty()
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    assert view.is_dirty()
    assert _conflict_shown(view)
    assert view._doc.get("services.message_board.url") == "http://h:1"
    assert field.text() == "http://h:1"


def test_conflict_clears_when_disk_returns_to_loaded_content(view, config_path):
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    assert _conflict_shown(view)
    config_path.write_bytes(_CONFIG.encode("utf-8"))
    view._check_disk()
    assert view._banner_wrap.isHidden()
    assert view._reload_btn.isHidden()
    assert view.is_dirty()


def test_external_write_while_clean_reloads(view, config_path):
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    assert view._raw.toPlainText() == _EXTERNAL
    assert view._doc.get("reserve_tokens") == 7
    assert not view.is_dirty()
    assert view._banner_wrap.isHidden()


def test_external_write_while_dirty_shows_banner_and_keeps_edits(view, config_path):
    edited = _CONFIG.replace("1000", "3000")
    _set_raw(view, edited)
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    assert _conflict_shown(view)
    assert view.is_dirty()
    assert view._raw.toPlainText() == edited


def test_external_conflict_reload_discards_edits(view, config_path):
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    view._reload_btn.click()
    assert view._raw.toPlainText() == _EXTERNAL
    assert not view.is_dirty()
    assert view._banner_wrap.isHidden()


def test_external_conflict_overwrite_saves_edits(view, config_path):
    edited = _CONFIG.replace("1000", "3000")
    _set_raw(view, edited)
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    view._overwrite_btn.click()
    assert config_path.read_text(encoding="utf-8") == edited
    assert not view.is_dirty()
    assert view._overwrite_btn.isHidden()
    assert "Saved." in view._banner_label.text()


def test_unchanged_hash_is_ignored(view, monkeypatch):
    calls = _count_reloads(view, monkeypatch)
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    view._check_disk()
    assert calls == []
    assert view._banner_wrap.isHidden()
    assert view.is_dirty()


def test_missing_file_is_not_a_change(view, config_path, monkeypatch):
    calls = _count_reloads(view, monkeypatch)
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    config_path.unlink()
    view._check_disk()
    assert calls == []
    assert view._banner_wrap.isHidden()
    assert view.is_dirty()
    # When the file reappears with new content, it is a change again.
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    assert _conflict_shown(view)
    assert str(config_path) in view._watcher.files()


def test_own_save_does_not_reload_or_banner(view, config_path, qtbot, monkeypatch):
    calls = _count_reloads(view, monkeypatch)
    _set_raw(view, _CONFIG.replace("1000", "2000"))
    view._save_btn.click()
    qtbot.wait(600)  # let any watcher event + debounce fire
    view._check_disk()
    assert calls == []
    assert view._banner_label.text() == "Saved."
    assert view._reload_btn.isHidden()


def test_watcher_keeps_path_after_save(view, config_path, qtbot):
    _set_raw(view, _CONFIG.replace("1000", "2000"))
    view._save_btn.click()
    assert str(config_path) in view._watcher.files()
    qtbot.wait(600)
    assert str(config_path) in view._watcher.files()


def test_conflict_banner_survives_raw_to_form_switch(view, config_path):
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    # Raw edited again, then a successful Raw->Form switch must not clear it.
    view._raw.setPlainText(_CONFIG.replace("1000", "4000"))
    view._tabs.setCurrentIndex(view._form_index)
    assert view._tabs.currentIndex() == view._form_index
    assert _conflict_shown(view)


def test_conflict_banner_survives_other_errors(view, config_path):
    _set_raw(view, _CONFIG.replace("1000", "3000"))
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    view._check_disk()
    view._raw.setPlainText("a: [broken\n")
    view._tabs.setCurrentIndex(view._form_index)  # blocked, shows parse error
    assert "line" in view._banner_label.text().lower()
    assert _conflict_shown(view)
    view._raw.setPlainText(_CONFIG.replace("1000", "4000"))
    view._tabs.setCurrentIndex(view._form_index)
    assert _conflict_shown(view)
    assert "line" not in view._banner_label.text().lower()


def test_save_conflict_uses_same_banner_and_revert_clears(view, config_path):
    _make_conflict(view, config_path)
    assert _conflict_shown(view)
    view._revert_btn.click()
    assert view._banner_wrap.isHidden()
    assert not view.is_dirty()


def test_unreadable_view_reloads_when_file_fixed(config_path, qtbot):
    config_path.write_bytes("default_model: m1  # caf\xe9\n".encode("cp1252"))
    w = SettingsView(config_path)
    qtbot.addWidget(w)
    assert not w._save_btn.isEnabled()
    config_path.write_text(_CONFIG, encoding="utf-8")
    w._check_disk()
    assert w._save_btn.isEnabled()
    assert w._raw.toPlainText() == _CONFIG
    assert w._banner_wrap.isHidden()


def test_debounce_coalesces_bursts(view, config_path, qtbot, monkeypatch):
    calls = _count_reloads(view, monkeypatch)
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    for _ in range(5):
        view._watcher.fileChanged.emit(str(config_path))
    assert calls == []  # nothing until the debounce elapses
    assert view._watch_timer.isActive()
    qtbot.waitUntil(lambda: not view._watch_timer.isActive(), timeout=2000)
    qtbot.wait(300)  # real watcher events for the same write also coalesce
    assert len(calls) == 1
    assert view._doc.get("reserve_tokens") == 7


def test_real_watcher_reloads_clean_view(view, config_path, qtbot):
    config_path.write_text(_EXTERNAL, encoding="utf-8")
    qtbot.waitUntil(lambda: view._raw.toPlainText() == _EXTERNAL, timeout=5000)
    assert not view.is_dirty()


def test_real_watcher_sees_atomic_replace(view, config_path, qtbot):
    import os

    tmp = config_path.with_suffix(".yaml.ext")
    tmp.write_text(_EXTERNAL, encoding="utf-8")
    os.replace(tmp, config_path)
    qtbot.waitUntil(lambda: view._raw.toPlainText() == _EXTERNAL, timeout=5000)
    second = _EXTERNAL + "keep_recent_tokens: 9\n"
    tmp.write_text(second, encoding="utf-8")
    os.replace(tmp, config_path)
    qtbot.waitUntil(lambda: view._raw.toPlainText() == second, timeout=5000)
