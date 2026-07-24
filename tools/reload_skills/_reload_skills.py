from __future__ import annotations

from agent.base_tool import BaseTool

RELOAD_SKILLS_SENTINEL = "__RELOAD_SKILLS__"


class ReloadSkillsTool(BaseTool):
    name = "reload_skills"
    description = (
        "Reload skills from disk. Call after creating or modifying a SKILL.md file "
        "to make the new or updated skill available in the current session without restarting."
    )
    _parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def run(self, **kwargs) -> str:
        return RELOAD_SKILLS_SENTINEL
