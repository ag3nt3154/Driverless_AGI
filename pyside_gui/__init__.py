from __future__ import annotations

import ctypes
import importlib.util
import os
import sys
from pathlib import Path

# Windows: PySide6's .pyd files depend on shiboken6.abi3.dll → pyside6.abi3.dll
# and Qt6 DLLs, all in non-system directories. Python 3.8+ won't search them
# unless we (a) register each dir with os.add_dll_directory and (b) preload the
# key DLLs via ctypes so Windows pins them in the process DLL table before the
# import machinery tries to resolve transitive deps by short name.
if sys.platform == "win32":
    _pyside6_spec = importlib.util.find_spec("PySide6")
    _shiboken6_spec = importlib.util.find_spec("shiboken6")
    if _pyside6_spec and _pyside6_spec.submodule_search_locations:
        _pyside6_dir = Path(next(iter(_pyside6_spec.submodule_search_locations)))
        # Library/bin holds ICU and other conda Qt deps (three levels up from PySide6)
        _lib_bin = _pyside6_dir.parent.parent.parent / "Library" / "bin"
        _dirs_to_add = [_pyside6_dir, _lib_bin]
        if _shiboken6_spec and _shiboken6_spec.submodule_search_locations:
            _shiboken6_dir = Path(next(iter(_shiboken6_spec.submodule_search_locations)))
            _dirs_to_add.append(_shiboken6_dir)
        else:
            _shiboken6_dir = None
        for _d in _dirs_to_add:
            if _d.is_dir():
                os.add_dll_directory(str(_d))
        # Preload dependency chain so Windows has them pinned before .pyd import.
        # Order matters: Qt6Core → shiboken6.abi3 → pyside6.abi3.
        # Use kernel32.LoadLibraryW directly — ctypes.WinDLL uses restricted flags
        # that can miss os.add_dll_directory paths on Python 3.8+.
        _k32 = ctypes.windll.kernel32
        _preload = [
            _pyside6_dir / "Qt6Core.dll",
            *([_shiboken6_dir / "shiboken6.abi3.dll"] if _shiboken6_dir else []),
            _pyside6_dir / "pyside6.abi3.dll",
        ]
        for _dll in _preload:
            if _dll.exists():
                _k32.LoadLibraryW(str(_dll))
