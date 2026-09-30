from __future__ import annotations

from pathlib import Path

from pyside_gui import recent_folders


def _dirs(tmp_path: Path, n: int) -> list[Path]:
    out = []
    for i in range(n):
        d = tmp_path / f"proj{i}"
        d.mkdir()
        out.append(d)
    return out


def test_load_missing_file_returns_empty(tmp_path: Path):
    assert recent_folders.load(tmp_path / "nope.json") == []


def test_load_corrupt_file_returns_empty(tmp_path: Path):
    store = tmp_path / "recent.json"
    store.write_text("{not json", encoding="utf-8")
    assert recent_folders.load(store) == []


def test_push_puts_newest_first_and_persists(tmp_path: Path):
    store = tmp_path / "recent.json"
    a, b = _dirs(tmp_path, 2)
    recent_folders.push(a, store)
    recent_folders.push(b, store)
    assert recent_folders.load(store) == [b, a]


def test_push_moves_existing_entry_to_front_without_duplicating(tmp_path: Path):
    store = tmp_path / "recent.json"
    a, b = _dirs(tmp_path, 2)
    for p in (a, b, a):
        recent_folders.push(p, store)
    assert recent_folders.load(store) == [a, b]


def test_push_treats_case_variants_as_same_folder_on_windows(tmp_path: Path, monkeypatch):
    # Windows paths are case-insensitive; C:\Foo and c:\foo must not both appear.
    monkeypatch.setattr(recent_folders.os.path, "normcase", str.lower)
    store = tmp_path / "recent.json"
    (a,) = _dirs(tmp_path, 1)
    recent_folders.push(a, store)
    recent_folders.push(Path(str(a).upper()), store)
    assert len(recent_folders.load(store)) == 1


def test_push_caps_at_five(tmp_path: Path):
    store = tmp_path / "recent.json"
    dirs = _dirs(tmp_path, 7)
    for d in dirs:
        recent_folders.push(d, store)
    assert recent_folders.load(store) == list(reversed(dirs))[:5]


def test_load_keeps_missing_folders(tmp_path: Path):
    # Missing folders are greyed out in the menu, not dropped from the store.
    store = tmp_path / "recent.json"
    gone = tmp_path / "gone"
    recent_folders.push(gone, store)
    assert recent_folders.load(store) == [gone]


def test_clear_empties_store(tmp_path: Path):
    store = tmp_path / "recent.json"
    (a,) = _dirs(tmp_path, 1)
    recent_folders.push(a, store)
    recent_folders.clear(store)
    assert recent_folders.load(store) == []


def test_push_survives_unwritable_store(tmp_path: Path):
    # A failed recents write must not break the folder switch that triggered it.
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    (a,) = _dirs(tmp_path, 1)
    assert recent_folders.push(a, blocker / "recent.json") == [a]
