"""
agent/subagent_tools.py — Subagent tool-registry construction.

Helpers for reading .dagi/subagents/<type>/subagent_config.yaml, instantiating
the tools it declares, discovering predefined subagent types, and assembling
the restricted ToolRegistry used by typed terminal subagents (called by the
subprocess entrypoint at tools/subagent_main.py).

Split out of agent/tools.py, which re-exports build_subagent_registry for
backwards compatibility with existing call sites.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from agent.base_tool import BaseTool
from agent.registry import ToolRegistry
from tools.bash import BashTool
from tools.edit import EditTool
from tools.find import FindTool
from tools.grep import GrepTool
from tools.read import ReadTool
from tools.copy import CopyTool
from tools.write import WriteTool

if TYPE_CHECKING:
    from agent.loop import AgentCallbacks, AgentConfig
    from agent.session import SessionTracker

from agent import DAGI_ROOT as _DAGI_ROOT


def _load_subagent_config(subagent_type: str, project_path: Path) -> dict:
    """Read and return .dagi/subagents/<type>/subagent_config.yaml as a dict."""
    for root in [project_path, _DAGI_ROOT]:
        config_path = root / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
        if config_path.exists():
            return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raise FileNotFoundError(
        f"No subagent_config.yaml found for subagent_type={subagent_type!r}. "
        f"Searched: {project_path / '.dagi' / 'subagents' / subagent_type} "
        f"and {_DAGI_ROOT / '.dagi' / 'subagents' / subagent_type}"
    )


def _tools_from_list(
    tool_names: list[str],
    cwd: Path,
    allowed_roots: list[Path] | None,
    handoff_path: Path | None = None,
) -> list[BaseTool]:
    """Instantiate tools by name for a subagent registry."""
    from tools.web_fetch import WebFetchTool
    from tools.web_search import WebSearchTool
    from tools.escalate_issue import EscalateIssueTool
    from tools.write_handoff import WriteHandoffTool

    registry_map: dict[str, BaseTool] = {
        "read":       ReadTool(cwd=cwd, allowed_roots=allowed_roots),
        "grep":       GrepTool(cwd=cwd, allowed_roots=allowed_roots),
        "find":       FindTool(cwd=cwd, allowed_roots=allowed_roots),
        "write":      WriteTool(cwd=cwd, allowed_roots=allowed_roots),
        "edit":       EditTool(cwd=cwd, allowed_roots=allowed_roots),
        "copy":       CopyTool(cwd=cwd, allowed_roots=allowed_roots),
        "bash":       BashTool(cwd=cwd),
        "web_search": WebSearchTool(),
        "web_fetch":  WebFetchTool(),
    }
    if handoff_path is not None:
        registry_map["escalate_issue"] = EscalateIssueTool(handoff_path=handoff_path)
    result: list[BaseTool] = []
    for name in tool_names:
        tool = registry_map.get(name)
        if tool is not None:
            result.append(tool)
        elif name == "escalate_issue" and handoff_path is None:
            # Not actually "unknown" — escalate_issue requires a handoff_path to
            # construct, which this caller didn't provide.
            print(
                "[tools] Warning: 'escalate_issue' requires handoff_path, which "
                "was not provided; skipping",
                file=sys.stderr,
            )
        else:
            print(
                f"[tools] Warning: unknown tool name {name!r} in subagent_config.yaml",
                file=sys.stderr,
            )
    # write_handoff is always available when a handoff_path is supplied, regardless
    # of whether the subagent's declared `tools:` list names it. It exposes exactly
    # one narrow capability (write this one file) so subagents that lack a general
    # `write` tool can still submit their final report.
    if handoff_path is not None:
        result.append(WriteHandoffTool(handoff_path=handoff_path))
    return result


def _discover_subagent_tools(
    cwd: Path,
    config: "AgentConfig",
    callbacks: "AgentCallbacks | None",
    tracker: "SessionTracker | None",
) -> list["BaseTool"]:
    """Scan .dagi/subagents/ for main.py; import and instantiate each BaseTool subclass.

    DAGI_ROOT types are scanned first; project types (cwd) override by name.
    Directories without main.py are silently skipped.
    """
    import importlib.util
    import inspect

    dagi_root_str = str(_DAGI_ROOT)
    if dagi_root_str not in sys.path:
        sys.path.insert(0, dagi_root_str)

    scan_dirs = [_DAGI_ROOT / ".dagi" / "subagents"]
    if cwd != _DAGI_ROOT:
        scan_dirs.append(cwd / ".dagi" / "subagents")

    tools_by_name: dict[str, BaseTool] = {}
    for subagents_dir in scan_dirs:
        if not subagents_dir.exists():
            continue
        for type_dir in sorted(subagents_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            main_py = type_dir / "main.py"
            if not main_py.exists():
                continue
            type_name = type_dir.name
            mod_name = f"_dagi_subagent_{type_name}"
            try:
                spec = importlib.util.spec_from_file_location(mod_name, main_py)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BaseTool)
                        and obj is not BaseTool
                        and obj.__module__ == mod_name
                    ):
                        tools_by_name[type_name] = obj(
                            config=config,
                            callbacks=callbacks,
                            tracker=tracker,
                        )
                        break
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[tools] Warning: failed to load subagent {type_name!r}: {exc}",
                    file=sys.stderr,
                )
    return list(tools_by_name.values())


def build_subagent_registry(
    subagent_type: str,
    config: "AgentConfig",
    project_path: Path,
    plan_file: Path | None = None,
    callbacks: "AgentCallbacks | None" = None,
    tracker: "SessionTracker | None" = None,
    memory_root: Path | None = None,
    handoff_path: Path | None = None,
    tool_names_override: list[str] | None = None,
) -> ToolRegistry:
    """Build a restricted ToolRegistry for a typed terminal subagent.

    Called by the subprocess (subagent_main.py) to reconstruct the tool scope
    defined in .dagi/subagents/<type>/subagent_config.yaml, with an optional
    override for the tool list.

    Args:
        subagent_type:      Type name matching a .dagi/subagents/<type>/ directory.
        config:             Resolved AgentConfig for this subagent.
        project_path:       Project root; used for cwd and allowed_roots.
        plan_file:          Unused; kept for signature compatibility.
        callbacks:          Subprocess-side callbacks.
        tracker:            Optional session tracker.
        memory_root:        Resolved memory root; used when subagent_config.yaml sets
                            `root: memory_root` to restrict file access to the wiki only.
        handoff_path:       Path where this subagent must write its handoff report.
        tool_names_override: When present, replaces the config-derived tool list.
    """
    default_roots: list[Path] | None = None if config.sandbox_mode else [_DAGI_ROOT, project_path]
    reg = ToolRegistry()

    # ── Config-driven: read tools list from subagent_config.yaml ─────────────
    try:
        cfg = _load_subagent_config(subagent_type, project_path)
    except FileNotFoundError:
        cfg = {}

    # Subagents with `root: memory_root` are restricted to the wiki directory only.
    root_override = cfg.get("root")
    if root_override == "memory_root":
        if memory_root is not None:
            wiki_root = memory_root
        else:
            wiki_root = (project_path / "dagi-memory").resolve()
        cwd_for_tools = wiki_root
        effective_roots: list[Path] | None = [wiki_root]
    else:
        cwd_for_tools = project_path
        effective_roots = default_roots

    tool_names: list[str] = (
        tool_names_override if tool_names_override is not None
        else cfg.get("tools", ["read", "grep", "find"])
    )
    for tool in _tools_from_list(
        tool_names, cwd_for_tools, effective_roots, handoff_path=handoff_path
    ):
        reg.register(tool)
    return reg
