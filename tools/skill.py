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

    def __init__(self, skills: list):
        # skills: list[agent.skills.Skill]
        self._skills = {s.name: s for s in skills}

    def run(self, skill: str) -> str:
        if skill not in self._skills:
            available = ", ".join(sorted(self._skills.keys())) or "none loaded"
            return f"Skill '{skill}' not found. Available skills: {available}"
        s = self._skills[skill]
        return f"# {s.name}\n\n{s.content}"
