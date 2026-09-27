"""Project briefing and task-artifact folder; initialization never overwrites files."""
from pathlib import Path

from agent._loop_helpers import project_slug


def _agents_template(project_name: str, today: str) -> str:
    slug = project_slug(Path(project_name))
    return f"""# AGENTS.md

> Last updated: {today}

## Overview
_1–2 sentences: what {project_name} is and why it exists._

## Rules
- _Standing, project-specific instructions only._

## Commands & Environment
- _Verified run / test / build commands and the Python environment._

## Memory
- Project wiki: `G:\\My Drive\\black_grimoire\\wiki\\projects\\{slug}\\`
- Search with memory-query at task start and before debugging; file with memory-add.
- Task specs and plans: `wiki/tasks/YYYY-MM-DD_<task>/` (this repo).
"""


_TASKS_README = """# wiki/tasks

Task specs and plans only (`YYYY-MM-DD_<task>/spec.md`, `plan.md`), written by the workflow.
Project knowledge (decisions, errors, notes, todos) lives in the central memory wiki at
`G:\\My Drive\\black_grimoire\\wiki` — use memory-query / memory-add, not files here.
"""


def build_init_files(project_name: str, today: str) -> dict[str, str]:
    """Return the project-relative files /init creates when missing."""
    return {
        "AGENTS.md": _agents_template(project_name, today),
        "wiki/tasks/README.md": _TASKS_README,
    }
