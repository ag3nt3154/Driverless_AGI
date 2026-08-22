"""
agent/skills.py — Skill loading and discovery.

Skills are markdown files (SKILL.md) with optional YAML frontmatter.
They are injected into the system prompt and callable via SkillTool.

Discovery roots (in priority order — later roots override earlier ones):
  1. <dagi_root>/.dagi/skills/ — dagi's built-in skills
  2. <project>/.dagi/skills/  — project-specific skills (take precedence)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str]  # explicit keyword phrases that should invoke this skill
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
    meta: dict[str, str] = {}
    lines = fm_block.splitlines()
    i = 0
    while i < len(lines):
        kv = _KV_RE.match(lines[i])
        if kv:
            key, val = kv.group(1), kv.group(2)
            if val in (">-", "|-", ">", "|"):
                parts: list[str] = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
                    parts.append(lines[i].strip())
                    i += 1
                joiner = " " if val.startswith(">") else "\n"
                meta[key] = joiner.join(p for p in parts if p)
            else:
                meta[key] = val
                i += 1
        else:
            i += 1
    return meta, body


# ── SkillLoader ───────────────────────────────────────────────────────────────

class SkillLoader:
    """Discovers and loads SKILL.md files from the given root directories."""

    def load_all(self, roots: list[Path], dagi_root: Path | None = None) -> list[Skill]:
        """Load skills from all roots. Later roots override earlier ones by name."""
        seen: dict[str, Skill] = {}
        for root in roots:
            source = "builtin" if (dagi_root and root == dagi_root / ".dagi" / "skills") else "project"
            for skill in self._load_from_root(root, source):
                seen[skill.name] = skill  # project skills win: last root overwrites earlier
        return list(seen.values())

    def load_all_with_errors(
        self, roots: list[Path], dagi_root: Path | None = None
    ) -> tuple[list[Skill], list[tuple[str, str]]]:
        """Like load_all(), but also returns [(path, reason)] for files that failed."""
        seen: dict[str, Skill] = {}
        errors: list[tuple[str, str]] = []
        for root in roots:
            source = "builtin" if (dagi_root and root == dagi_root / ".dagi" / "skills") else "project"
            for skill_file in sorted(root.rglob("SKILL.md")) if root.exists() else []:
                skill, error = self._load_file_checked(skill_file, source)
                if skill:
                    seen[skill.name] = skill
                elif error:
                    errors.append((str(skill_file), error))
        return list(seen.values()), errors

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
        skill, _ = self._load_file_checked(path, source)
        return skill

    def _load_file_checked(self, path: Path, source: str) -> tuple["Skill | None", "str | None"]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            return None, f"cannot read file: {e}"

        meta, body = _parse_frontmatter(text)
        body = body.strip()

        name = meta.get("name") or path.parent.name
        name = name.strip().lower().replace(" ", "-")
        if not name:
            return None, "missing 'name' field and directory name is empty"

        description = meta.get("description", "").strip()
        raw_triggers = meta.get("triggers", "")
        triggers = [t.strip() for t in raw_triggers.split(",") if t.strip()]

        return Skill(
            name=name,
            description=description,
            triggers=triggers,
            file_path=str(path),
            content=body,
            source=source,
        ), None


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
        if s.triggers:
            quoted = ", ".join(f'"{t}"' for t in s.triggers)
            lines.append(f"  Triggers: {quoted}")
    return "\n".join(lines)
