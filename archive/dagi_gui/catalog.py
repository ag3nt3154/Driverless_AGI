"""Bootstrap and catalog queries for the GUI sidecar.

All functions return JSON-safe dicts. TypeScript must not parse Python
configuration or frontmatter — these functions do that work server-side.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from dagi_gui.protocol import PROTOCOL_VERSION

if TYPE_CHECKING:
    from agent.config_loader import AgentConfig


def build_bootstrap(config: "AgentConfig") -> dict:
    """Return the full bootstrap payload sent on initialize."""
    from agent.config_loader import list_model_ids, resolve_model_config
    from agent.skills import SkillLoader
    from agent.workflows import WorkflowLoader
    from agent.loop import DAGI_ROOT

    skill_roots = [
        DAGI_ROOT / ".dagi" / "skills",
        config.project_path / ".dagi" / "skills",
    ]
    skills = [s.name for s in SkillLoader().load_all(skill_roots, dagi_root=DAGI_ROOT)]

    workflow_roots = [
        DAGI_ROOT / ".dagi" / "workflows",
        config.project_path / ".dagi" / "workflows",
    ]
    workflows = [w.name for w in WorkflowLoader().load_all(workflow_roots)]

    resolved = resolve_model_config(config.project_path)

    return {
        "protocol_version": PROTOCOL_VERSION,
        "model_id": resolved.model,
        "model_display": _model_display(resolved.model),
        "context_window": resolved.context_window,
        "reserve_tokens": resolved.reserve_tokens,
        "project_path": str(config.project_path),
        "app_path": str(DAGI_ROOT),
        "models": list_model_ids(),
        "skills": skills,
        "workflows": workflows,
    }


def _model_display(model_id: str) -> str:
    """Return a short display name for a model ID."""
    parts = model_id.split("/")
    return parts[-1] if parts else model_id
