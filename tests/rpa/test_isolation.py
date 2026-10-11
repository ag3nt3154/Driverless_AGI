"""tests/rpa/test_isolation.py — rpa/ must never import dagi's agent layers (D11)."""
from __future__ import annotations

import ast
import pathlib

import pytest

FORBIDDEN = {"agent", "tools", "pyside_gui", "tui", "tg"}
RPA_DIR = pathlib.Path(__file__).resolve().parents[2] / "rpa"


def test_rpa_does_not_import_dagi_agent_layers():
    bad = []
    for path in RPA_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            bad += [f"{path}: {n}" for n in names if n.split(".")[0] in FORBIDDEN]
    assert (RPA_DIR / "__init__.py").exists() and bad == []


@pytest.mark.desktop
def test_desktop_marker_dummy():
    """Trivial marker check: only runs when DAGI_DESKTOP_TESTS=1 (see conftest)."""
    assert True
