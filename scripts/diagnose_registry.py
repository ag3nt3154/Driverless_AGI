"""
scripts/diagnose_registry.py — Trace every tool registration in create_tool_registry
and report memory after each one, using the same call as the failing test.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent))


def ram_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 ** 2)


def _config():
    cfg = MagicMock()
    cfg.tools = None
    cfg.bash_backend = "subprocess"
    cfg.sandbox_mode = False
    cfg.advanced_config = None
    cfg.worker_config = None
    cfg.autonomous = False
    return cfg


# ── Monkey-patch ToolRegistry.register to log each call ──────────────────────
from agent.registry import ToolRegistry

_original_register = ToolRegistry.register


def _traced_register(self, tool):
    before = ram_mb()
    _original_register(self, tool)
    after = ram_mb()
    delta = after - before
    flag = "  *** SPIKE ***" if delta > 100 else ""
    print(f"  [{after:>8.1f} MB | Δ{delta:>+8.1f} MB]  registered: {tool.name}{flag}")


ToolRegistry.register = _traced_register

# ── Also patch importlib dynamic loading to trace _load_project_tools ─────────
import importlib.util as _ilu
_orig_exec = None

# ── Run ───────────────────────────────────────────────────────────────────────
from agent.tools import create_tool_registry

print(f"\n{'='*65}")
print(f"  Process RAM at start: {ram_mb():.1f} MB")
print(f"{'='*65}\n")

print("Calling create_tool_registry(cwd=Path('.'), config=<mock>)...\n")

try:
    reg = create_tool_registry(cwd=Path("."), config=_config())
except Exception as exc:
    print(f"\n!!! Exception during create_tool_registry: {type(exc).__name__}: {exc}")

print(f"\n{'='*65}")
print(f"  Process RAM at end: {ram_mb():.1f} MB")
print(f"  Tools registered: {[n for n, _ in reg.list_tools()]}")
print(f"{'='*65}\n")
