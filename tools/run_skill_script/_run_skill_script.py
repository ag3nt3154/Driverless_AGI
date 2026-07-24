from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from agent.base_tool import BaseTool

_SCRIPT_EXTS = {".py", ".sh", ".bash", ".ps1", ".js", ".ts", ".rb", ".pl"}


class RunSkillScriptTool(BaseTool):
    name = "run_skill_script"
    description = (
        "Execute a script embedded in a skill's directory. "
        "Load the skill first with skill() to see available scripts under 'Scripts in this skill'. "
        "Python scripts run in the dagi conda environment. "
        "Works for both built-in and project skills."
    )
    _parameters = {
        "type": "object",
        "properties": {
            "skill_name": {
                "type": "string",
                "description": "Name of the skill whose directory contains the script",
            },
            "script_name": {
                "type": "string",
                "description": "Filename of the script (e.g. 'ingest.py', 'build.sh')",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments to pass to the script as a space-separated string",
                "default": "",
            },
        },
        "required": ["skill_name", "script_name"],
    }

    def __init__(self, skill_roots: list[Path], dagi_root: Path | None = None) -> None:
        self._skill_roots = skill_roots
        self._dagi_root = dagi_root

    def run(self, skill_name: str, script_name: str, args: str = "") -> str:
        from agent.skills import SkillLoader

        skills_map = {
            s.name: s
            for s in SkillLoader().load_all(self._skill_roots, dagi_root=self._dagi_root)
        }

        if skill_name not in skills_map:
            available = ", ".join(sorted(skills_map.keys())) or "none loaded"
            return f"Skill '{skill_name}' not found. Available skills: {available}"

        skill = skills_map[skill_name]
        skill_dir = Path(skill.file_path).parent
        script_path = (skill_dir / script_name).resolve()

        # Security: prevent path traversal out of the skill directory
        try:
            script_path.relative_to(skill_dir.resolve())
        except ValueError:
            return (
                f"Error: '{script_name}' resolves outside the skill directory. "
                "Only scripts within the skill's own folder may be executed."
            )

        if not script_path.exists():
            scripts = [p.name for p in skill_dir.iterdir() if p.suffix.lower() in _SCRIPT_EXTS]
            available_scripts = ", ".join(scripts) if scripts else "none"
            return (
                f"Script '{script_name}' not found in skill '{skill_name}'. "
                f"Available scripts: {available_scripts}"
            )

        ext = script_path.suffix.lower()
        extra_args = shlex.split(args) if args.strip() else []

        if ext == ".py":
            cmd = ["conda", "run", "-n", "dagi", "python", str(script_path)] + extra_args
        elif ext in (".sh", ".bash"):
            cmd = ["bash", str(script_path)] + extra_args
        elif ext in _SCRIPT_EXTS:
            cmd = [str(script_path)] + extra_args
        else:
            return (
                f"Cannot execute '{script_name}': unsupported extension '{ext}'. "
                f"Supported: {', '.join(sorted(_SCRIPT_EXTS))}"
            )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(skill_dir),
            )
        except FileNotFoundError as e:
            return f"Error: could not launch script — {e}"
        except subprocess.TimeoutExpired:
            return f"Error: script '{script_name}' timed out after 120 seconds."

        parts = []
        if result.stdout:
            parts.append(result.stdout.rstrip())
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr.rstrip()}")
        parts.append(f"[exit code {result.returncode}]")
        return "\n".join(parts)
