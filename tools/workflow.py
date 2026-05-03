"""
tools/workflow.py — CLI helpers for the workflow system.

These are NOT BaseTool subclasses and are NOT registered in the ToolRegistry.
Workflows are user-directed only; the agent has no autonomous awareness of them.
"""
from __future__ import annotations

from pathlib import Path


def _posix_bash(p: Path) -> str:
    """Convert a Windows path to a POSIX path suitable for bash."""
    resolved = p.resolve()
    drive = resolved.drive  # e.g. "C:"
    rest = resolved.as_posix()[len(drive):]  # e.g. "/Users/alexr/..."
    return "/" + drive[0].lower() + rest


_SCRIPT_EXTS = {".py", ".sh", ".bash", ".ps1", ".js", ".ts", ".rb", ".pl"}


def load_workflow_content(name: str, roots: list[Path]) -> str:
    """
    Return the full task-message string to inject when a workflow slash command fires.

    Includes the workflow body plus a listing of any sibling scripts/data files
    in the workflow directory (mirrors SkillTool behaviour for helper scripts).
    Returns an error string if the workflow is not found.
    """
    from agent.workflows import WorkflowLoader

    workflows_map = {w.name: w for w in WorkflowLoader().load_all(roots)}
    if name not in workflows_map:
        available = ", ".join(sorted(workflows_map.keys())) or "none loaded"
        return f"Workflow '{name}' not found. Available workflows: {available}"

    w = workflows_map[name]
    result = w.content

    workflow_dir = Path(w.file_path).parent
    siblings = sorted(
        p for p in workflow_dir.iterdir()
        if p.is_file() and p.name != "workflow.md"
    )

    if siblings:
        scripts = [p for p in siblings if p.suffix.lower() in _SCRIPT_EXTS]
        data_files = [p for p in siblings if p.suffix.lower() not in _SCRIPT_EXTS]

        if scripts:
            script_lines = [
                f"- `{p.name}` — path: {_posix_bash(p)}"
                for p in scripts
            ]
            result += "\n\n## Scripts in this workflow\n\n" + "\n".join(script_lines)

        if data_files:
            data_lines = [
                f"- Windows: {p.resolve()}  |  POSIX: {_posix_bash(p)}"
                for p in data_files
            ]
            result += "\n\n## Associated Files\n\n" + "\n".join(data_lines)

    return result


def list_workflows(roots: list[Path]) -> list:
    """Return all Workflow objects discovered under the given roots."""
    from agent.workflows import WorkflowLoader
    return WorkflowLoader().load_all(roots)
