from __future__ import annotations

from datetime import datetime

from agent import notepad_store as store


def test_read_missing_returns_empty(tmp_path):
    assert store.read_text(tmp_path / "nope") == ""


def test_write_then_read_preserves_bytes(tmp_path):
    text = "# t\n\n$e^{i\\pi}$\r\nline\n"
    store.write_text(text, tmp_path)
    assert store.read_text(tmp_path) == text
    assert store.notepad_path(tmp_path).read_bytes() == text.encode("utf-8")
    assert not list(tmp_path.glob(".*.tmp"))


def test_content_hash_is_stable_and_distinct():
    assert store.content_hash("a") == store.content_hash("a")
    assert store.content_hash("a") != store.content_hash("b")


def test_backup_conflict_names_are_unique(tmp_path):
    now = datetime(2026, 9, 30, 12, 0, 0)
    first = store.backup_conflict("one", tmp_path, now)
    second = store.backup_conflict("two", tmp_path, now)
    assert first.name == "conflict-20260930-120000.md"
    assert second.name == "conflict-20260930-120000-1.md"
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"


def test_state_round_trip_and_corruption(tmp_path):
    assert store.load_state(tmp_path) == {}
    store.save_state({"width": 400, "height": 500}, tmp_path)
    assert store.load_state(tmp_path) == {"width": 400, "height": 500}
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert store.load_state(tmp_path) == {}
    (tmp_path / "state.json").write_text("[1, 2]", encoding="utf-8")
    assert store.load_state(tmp_path) == {}


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch):
    real_replace = store.os.replace
    calls = []

    def flaky_replace(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("locked")
        real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky_replace)
    monkeypatch.setattr(store, "_REPLACE_DELAY_S", 0)
    store.write_text("ok", tmp_path)
    assert len(calls) == 3
    assert store.read_text(tmp_path) == "ok"
