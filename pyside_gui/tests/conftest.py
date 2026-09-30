from __future__ import annotations

import pytest

import pyside_gui  # noqa: F401 - must be imported before any PySide6 import


def pytest_configure(config) -> None:
    # pyproject.toml disables pytest-qt globally (`-p no:pytest-qt`) because
    # its eager QtCore import crashes with a Windows DLL load error when it
    # runs before the pyside_gui DLL bootstrap above. Register it here, after
    # the bootstrap, so the GUI tests still get `qtbot`/`qapp`.
    import pytestqt.plugin

    if not config.pluginmanager.is_registered(pytestqt.plugin):
        config.pluginmanager.register(pytestqt.plugin, "pytestqt-local")


@pytest.fixture(autouse=True)
def _isolated_recent_folders(tmp_path, monkeypatch):
    """Keep GUI tests from writing the real DAGI_ROOT/.dagi/recent_folders.json."""
    from pyside_gui import recent_folders

    monkeypatch.setattr(recent_folders, "_STORE", tmp_path / "recent_folders.json")
