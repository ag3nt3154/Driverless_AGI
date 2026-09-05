"""run_tests.py — DLL-safe pytest wrapper for the dagi conda environment.

Adds PySide6 to the DLL search path on Windows before pytest loads its
plugins (including pytestqt), which would otherwise crash with a DLL
load error. Accepts the same arguments as pytest.

Usage:
    python run_tests.py tests/test_subagent_runner.py -x -q
"""
from __future__ import annotations

import os
import sys

# Must happen before any imports that trigger DLL loading.
_pyside6 = os.path.join(os.path.dirname(os.__file__), "site-packages", "PySide6")
if os.path.isdir(_pyside6) and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(_pyside6)

import pytest  # noqa: E402

if __name__ == "__main__":
    sys.exit(pytest.main(sys.argv[1:]))
