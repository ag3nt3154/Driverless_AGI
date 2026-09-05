"""agent/_plan_mode.py — plan-mode lifecycle handlers.

Extracted verbatim from AgentLoop methods in agent/loop.py (`self` became the
explicit `loop` parameter) so the loop orchestrator stays under the 500-line
cap. Only agent/loop.py imports from this module.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from agent import DAGI_ROOT
from agent._git_branch import create_task_branch, get_current_branch
from agent.skills import SkillLoader

if TYPE_CHECKING:
    from agent.loop import AgentLoop


def _is_plan_empty(path: Path) -> bool:
    """Return True if the plan file has no meaningful content beyond scaffold boilerplate."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return True
    meaningful = [
        line for line in text.splitlines()
        if line.strip()
        and not line.strip().startswith("#")
        and line.strip() not in ("- [ ]", "- [ ] ", "- [x]")
    ]
    return len(meaningful) == 0


def handle_enter_plan_mode(loop, args: dict) -> str:
        mode = args.get("mode", "interactive")
        task_summary = (args.get("task_summary") or "").strip()
        if not task_summary:
            return "Error: task_summary is required when entering plan mode."

        interactive = mode != "autonomous"
        dagi_root = DAGI_ROOT
        plans_dir = loop.config.project_path / ".dagi" / "plans"
        plans_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        plan_dir = plans_dir / f"plan_{ts}"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_file = plan_dir / "plan.md"
        plan_file.write_text(
            f"# Plan: {task_summary}\n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Subtasks\n\n"
            "### Subtask 1: [ ] \n"
            "**Goal:** \n"
            "**Requirements:**\n"
            "- \n"
            "**Acceptance Criteria:**\n"
            "- \n"
            "#### Tests\n\n"
            "## Notes\n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )

        loop.config.previous_branch = get_current_branch(loop.config.project_path)

        branch_name: str | None = None
        branch_creation_failed = False
        try:
            branch_name = create_task_branch(loop.config.project_path, task_summary, plan_dir.name)
        except RuntimeError as e:
            branch_creation_failed = True
            loop.callbacks.on_assistant_text(f"[git] Could not create task branch: {e}")

        if branch_name:
            branch_note = f"**Branch:** `{branch_name}`"
        elif branch_creation_failed:
            branch_note = (
                "**Branch:** (branch creation failed — see notice above — "
                "continuing without a git workflow)"
            )
        else:
            branch_note = "**Branch:** (no git repository detected — skipping git workflow)"

        loop._handle_switch_model("plan", {"reason": "entering plan mode"})
        to_name = loop.config.display_name or loop.config.model

        loop.callbacks.on_assistant_text(
            f"Entering plan mode — switching to advanced model ({to_name}).\n\n"
            f"**Plan file:** `{plan_file}`\n\n**Mode:** {mode}\n\n{branch_note}"
        )

        loop._rebuild_for_plan_mode(dagi_root, plan_file, interactive=interactive)

        return (
            f"Plan mode activated ({mode} mode). Advanced model: {to_name}.\n\n"
            f"Plan file: {plan_file}\n\n"
            f"{branch_note}\n\n"
            f"Tools restricted to: read, grep, find, write/edit (plan file only), "
            f"web_research, skill, run_skill_script, ask_user, show_plan, exit_plan_mode."
        )


def handle_exit_plan_mode(loop, args: dict) -> str:
        saved_plan = loop.config.plan_file
        summary = (args.get("summary") or "").strip().lower()
        cancelled = summary == "cancelled"
        dagi_root = DAGI_ROOT
        loop._handle_switch_model("default", {"reason": "plan complete, returning to normal mode"})
        if not cancelled and saved_plan:
            loop.config.active_plan_file = saved_plan
            _persist_active_plan(loop, Path(saved_plan))
        loop._rebuild_for_normal_mode(dagi_root)
        if cancelled:
            return "Plan mode cancelled. Full tools restored. No active plan set."
        if saved_plan and _is_plan_empty(Path(saved_plan)):
            return (
                "The plan document is empty. "
                "Stop immediately and ask the user for further directions "
                "before doing anything else."
            )
        try:
            plan_contents = Path(saved_plan).read_text(encoding="utf-8")
        except Exception:
            plan_contents = "(plan file could not be read)"
        return (
            f"Plan mode exited. Full tools restored. Plan file: {saved_plan}\n\n"
            f"{plan_contents}"
        )


def _persist_active_plan(loop, plan_path: Path) -> None:
        """Write the sidecar so the active-plan association survives across sessions."""
        from tools.active_plan._active_plan import _sidecar_path, _thread_id, _write_atomic
        tid = _thread_id(loop.config, loop.tracker)
        sidecar = _sidecar_path(Path(loop.config.project_path), tid)
        branch = get_current_branch(loop.config.project_path)
        _write_atomic(sidecar, {
            "version": 1,
            "repo_root": str(loop.config.project_path),
            "plan_path": str(plan_path),
            "expected_branch": branch,
        })


def handle_all_tasks_resolved(loop) -> str:
        plan = loop.config.active_plan_file
        return (
            f"All tasks resolved. Active plan remains associated: {plan}\n\n"
            "Next: run integrated verification and a final review before accepting delivery. "
            "Call set_active_plan(null) to detach explicitly after the final review is accepted."
        )


def rebuild_for_normal_mode(loop, dagi_root: Path) -> None:
        from agent.tools import create_tool_registry

        loop.config.plan_mode = False
        loop.config.plan_file = None
        loop.config.plan_mode_initiated_by = "user"

        skill_roots = [
            dagi_root / ".dagi" / "skills",
            loop.config.project_path / ".dagi" / "skills",
        ]
        loop.registry = create_tool_registry(
            cwd=loop.config.project_path,
            allowed_roots=[dagi_root, loop.config.project_path, loop._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=False,
            plan_file=None,
            plan_mode_initiated_by="user",
            config=loop.config,
            callbacks=loop.callbacks,
            tracker=loop.tracker,
            memory_root=loop._effective_memory_root,
            bash_tool=loop._injected_bash_tool,
            session_log=loop.log,
            parent_context=loop.parent_context_provider,
            expression_controller=loop.tracker.expression_controller,
        )

        _system = loop._assemble_system_string(dagi_root)
        loop._emit_header(_system, "change")
        loop._sync_messages()


def rebuild_for_plan_mode(loop, dagi_root: Path, plan_file: Path, interactive: bool = True) -> None:
        from agent.tools import create_tool_registry

        initiated_by = "user" if interactive else "dagi"
        loop.config.plan_mode = True
        loop.config.plan_file = str(plan_file)
        loop.config.plan_mode_initiated_by = initiated_by

        skill_roots = [
            dagi_root / ".dagi" / "skills",
            loop.config.project_path / ".dagi" / "skills",
        ]
        loop.registry = create_tool_registry(
            cwd=loop.config.project_path,
            allowed_roots=[dagi_root, loop.config.project_path, loop._effective_memory_root],
            skill_roots=skill_roots,
            plan_mode=True,
            plan_file=plan_file,
            plan_mode_initiated_by=initiated_by,
            config=loop.config,
            callbacks=loop.callbacks,
            tracker=loop.tracker,
            memory_root=loop._effective_memory_root,
            session_log=loop.log,
            parent_context=loop.parent_context_provider,
        )
        _system = loop._assemble_system_string(dagi_root)
        loop._emit_header(_system, "change")
        loop._sync_messages()


def rebuild_for_reload(loop) -> tuple[set[str], set[str], list[tuple[str, str]]]:
        """Hot-reload skills from disk, rebuild registry + system prompt preserving current mode.

        Returns (added_names, removed_names, errors) for notification formatting.
        """
        dagi_root = DAGI_ROOT
        skill_roots = [
            dagi_root / ".dagi" / "skills",
            loop.config.project_path / ".dagi" / "skills",
        ]

        before_names = {s.name for s in loop.skills}
        new_skills, errors = SkillLoader().load_all_with_errors(skill_roots, dagi_root=dagi_root)
        loop.skills = new_skills
        after_names = {s.name for s in loop.skills}

        if loop.config.plan_mode and loop.config.plan_file:
            interactive = loop.config.plan_mode_initiated_by == "user"
            loop._rebuild_for_plan_mode(dagi_root, Path(loop.config.plan_file), interactive=interactive)
        else:
            loop._rebuild_for_normal_mode(dagi_root)

        return after_names - before_names, before_names - after_names, errors
