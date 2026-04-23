from pathlib import Path

from agent.base_tool import BaseTool


class SkillTool(BaseTool):
    name = "skill"
    description = (
        "Load a skill document by name to get detailed instructions or techniques. "
        "Call this when you need guidance on a specific approach or workflow. "
        "Use the 'skill' tool with the exact skill name."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Name of the skill to load"},
        },
        "required": ["skill"],
    }

    def __init__(self, skill_roots: list[Path], dagi_root: Path | None = None):
        self._skill_roots = skill_roots
        self._dagi_root = dagi_root

    def run(self, skill: str) -> str:
        from agent.skills import SkillLoader
        skills_map = {
            s.name: s
            for s in SkillLoader().load_all(self._skill_roots, dagi_root=self._dagi_root)
        }
        if skill not in skills_map:
            available = ", ".join(sorted(skills_map.keys())) or "none loaded"
            return f"Skill '{skill}' not found. Available skills: {available}"
        s = skills_map[skill]
        result = f"# {s.name}\n\n{s.content}"

        skill_dir = Path(s.file_path).parent
        siblings = sorted(p for p in skill_dir.iterdir() if p.is_file() and p.name != "SKILL.md")
        if siblings:
            def _posix_bash(p: Path) -> str:
                resolved = p.resolve()
                drive = resolved.drive  # e.g. "C:"
                rest = resolved.as_posix()[len(drive):]  # e.g. "/Users/alexr/..."
                return "/" + drive[0].lower() + rest

            lines = [f"- Windows: {p.resolve()}  |  POSIX: {_posix_bash(p)}" for p in siblings]
            result += "\n\n## Associated Files\n\n" + "\n".join(lines)

        return result
