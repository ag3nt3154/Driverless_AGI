"""rpa/ — RPA + computer-use package.

Isolation rule (D11): this package and everything under it must never import
`agent`, `tools`, `pyside_gui`, `tui` or `tg`, so `python -m rpa run` works with
no agent. Enforced by tests/rpa/test_isolation.py (AST scan).
"""
from __future__ import annotations

RPA_HOME_DIRNAME = ".dagi/rpa"


class RpaError(Exception):
    """Base class for all rpa errors."""
