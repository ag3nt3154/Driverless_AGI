from pathlib import Path
from agent.tools import create_tool_registry
from agent.skills import SkillLoader

reg = create_tool_registry(cwd=Path('.'))
print('Tools:', [name for name, _ in reg.list_tools()])

skills = SkillLoader().load_all([Path('skills')])
print('Skills (builtin):', [s.name for s in skills])
print('OK')
