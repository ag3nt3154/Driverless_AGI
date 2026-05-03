"""
agent/workflows.py — Workflow loading and discovery.

Workflows are markdown files (workflow.md) with optional YAML frontmatter.
Unlike skills, they are NOT injected into the system prompt and are NOT
autonomously discoverable by the agent. They are invoked only by the user
via slash commands (e.g. /workflow-name).

Discovery roots are project-local only:
  <project>/.dagi/workflow/
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Workflow:
    name: str
    description: str
    file_path: str
    content: str    # markdown body (after frontmatter)
    source: str     # always "project"


# ── YAML frontmatter parser (no external deps) ────────────────────────────────

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*):\s*[\"']?(.*?)[\"']?\s*$", re.MULTILINE)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (metadata_dict, body_text) from a markdown file."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    fm_block = m.group(1)
    body = text[m.end():]
    meta = {k: v for k, v in _KV_RE.findall(fm_block)}
    return meta, body


# ── WorkflowLoader ────────────────────────────────────────────────────────────

class WorkflowLoader:
    """Discovers and loads workflow.md files from the given root directories."""

    def load_all(self, roots: list[Path]) -> list[Workflow]:
        """Load workflows from all roots. Later roots override earlier ones by name."""
        seen: dict[str, Workflow] = {}
        for root in roots:
            for workflow in self._load_from_root(root):
                seen[workflow.name] = workflow
        return list(seen.values())

    def _load_from_root(self, root: Path) -> list[Workflow]:
        if not root.exists():
            return []
        workflows: list[Workflow] = []
        for wf_file in sorted(root.rglob("workflow.md")):
            workflow = self._load_file(wf_file)
            if workflow:
                workflows.append(workflow)
        return workflows

    def _load_file(self, path: Path) -> Workflow | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        meta, body = _parse_frontmatter(text)
        body = body.strip()

        # Derive name: frontmatter > parent directory name
        name = meta.get("name") or path.parent.name
        name = name.strip().lower().replace(" ", "-")
        if not name:
            return None

        description = meta.get("description", "").strip()

        return Workflow(
            name=name,
            description=description,
            file_path=str(path),
            content=body,
            source="project",
        )
