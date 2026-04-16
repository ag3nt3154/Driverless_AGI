"""
agent/skills.py — Skill loading and discovery.

Skills are markdown files (SKILL.md) with optional YAML frontmatter.
They are injected into the system prompt and callable via SkillTool.

Discovery roots (in priority order — later roots override earlier ones):
  1. <dagi_root>/skills/   — dagi's own built-in skills
  2. <project>/.dagi/skills/  — project-specific skills
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    file_path: str
    content: str        # markdown body (after frontmatter)
    source: str         # "builtin" | "project"


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


# ── SkillLoader ───────────────────────────────────────────────────────────────

class SkillLoader:
    """Discovers and loads SKILL.md files from the given root directories."""

    def load_all(self, roots: list[Path]) -> list[Skill]:
        """Load skills from all roots. Later roots override earlier ones by name."""
        seen: dict[str, Skill] = {}
        for root in roots:
            source = "project" if root.name == "skills" and root.parent.name == ".dagi" else "builtin"
            for skill in self._load_from_root(root, source):
                seen[skill.name] = skill  # project skills win over built-ins
        return list(seen.values())

    def _load_from_root(self, root: Path, source: str) -> list[Skill]:
        if not root.exists():
            return []
        skills: list[Skill] = []
        for skill_file in sorted(root.rglob("SKILL.md")):
            skill = self._load_file(skill_file, source)
            if skill:
                skills.append(skill)
        return skills

    def _load_file(self, path: Path, source: str) -> Skill | None:
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

        return Skill(
            name=name,
            description=description,
            file_path=str(path),
            content=body,
            source=source,
        )


def format_skills_for_prompt(skills: list[Skill]) -> str:
    """Format the skills list as a system-prompt section."""
    if not skills:
        return ""
    lines = ["## Available Skills", ""]
    lines.append(
        "Use the `skill` tool to load any skill document for detailed guidance:"
    )
    lines.append("")
    for s in sorted(skills, key=lambda x: x.name):
        desc = f" — {s.description}" if s.description else ""
        lines.append(f"- **{s.name}**{desc}")
    return "\n".join(lines)
