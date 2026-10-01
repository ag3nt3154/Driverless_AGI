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


def _flush_deferred_deletes() -> None:
    from PySide6.QtCore import QCoreApplication, QEvent

    if QCoreApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def _process_deferred_deletes():
    """Actually destroy widgets that tests ``deleteLater()``.

    Tests never run a top-level event loop, and ``processEvents()`` skips
    DeferredDelete at loop level 0, so discarded windows used to live on.
    Each leaked QWebEngineView kept loading its page (Vditor is heavy), so
    later web-view tests competed with every earlier one and timed out
    under machine load. Flush before (module-fixture leftovers) and after.
    """
    _flush_deferred_deletes()
    yield
    _flush_deferred_deletes()


@pytest.fixture(autouse=True)
def _isolated_recent_folders(tmp_path, monkeypatch):
    """Keep GUI tests from writing the real DAGI_ROOT/.dagi/recent_folders.json."""
    from pyside_gui import recent_folders

    monkeypatch.setattr(recent_folders, "_STORE", tmp_path / "recent_folders.json")
