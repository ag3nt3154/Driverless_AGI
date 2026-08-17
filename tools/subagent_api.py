"""tools/subagent_api.py — Unified subagent execution function.

Public API for spawning subagents. Used by:
  - .dagi/subagents/<type>/main.py (auto-discovered BaseTool wrappers)
  - DAGI-authored workflow scripts (custom orchestration)

Wraps the low-level _subagent_runner subprocess machinery with preset
resolution, handoff auto-read, and a structured SubagentResult.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

import yaml

from agent import DAGI_ROOT as _DAGI_ROOT
from agent import session_events as sev
from tools import _subagent_runner as _runner
from tools._task_envelope import wrap_envelope

if TYPE_CHECKING:
    from agent.session_log import SessionLog


@dataclass
class SubagentResult:
    status: str
    handoff_text: str
    handoff_path: Path
    session_log_path: Path | None
    pid: int | None
    escalation: str | None
    branch_id: str | None = None

    @property
    def is_ok(self) -> bool:
        return self.status in ("ok", "ok_unverified")


def _load_preset(
    preset: str, project_path: Path,
) -> tuple[str, list[str], str, str, list[str]]:
    """Load preset config. Returns (prompt, tools, model_tier,
    default_handoff_spec, agents_md)."""
    for root in [project_path, _DAGI_ROOT]:
        base = root / ".dagi" / "subagents" / preset
        config_path = base / "subagent_config.yaml"
        prompt_path = base / "prompt.md"
        if config_path.exists() and prompt_path.exists():
            prompt = prompt_path.read_text(encoding="utf-8")
            cfg = yaml.safe_load(
                config_path.read_text(encoding="utf-8")
            ) or {}
            return (
                prompt,
                cfg.get("tools", ["read", "grep", "find"]),
                cfg.get("model_tier", "worker"),
                cfg.get("default_handoff_spec", ""),
                cfg.get("agents_md", []),
            )
    raise FileNotFoundError(
        f"Preset {preset!r} not found in {project_path} or {_DAGI_ROOT}"
    )


def _auto_read_handoff(path_str: str) -> str:
    try:
        return Path(path_str).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _build_result(raw: dict, handoff_path: Path) -> SubagentResult:
    status = raw["status"]
    if status in ("ok", "ok_unverified"):
        text = _auto_read_handoff(raw.get("handoff", ""))
    else:
        text = ""
    return SubagentResult(
        status=status,
        handoff_text=text,
        handoff_path=handoff_path,
        session_log_path=None,  # resolved by caller if tracker present
        pid=raw.get("pid"),
        escalation=raw.get("escalation"),
    )


def run_subagent(
    task: str,
    preset: str | None = None,
    prompt: str | None = None,
    custom_instructions: str = "",
    tools: list[str] | None = None,
    timeout: float = 1800.0,
    model_tier: str = "default",
    handoff_spec: str = "",
    project_path: Path | None = None,
    on_event: Callable[[str], None] | None = None,
    parent_log: "SessionLog | None" = None,
) -> SubagentResult:
    """Spawn a subagent and return its result with auto-read handoff."""
    if preset is None and prompt is None:
        raise ValueError("Either preset or prompt must be provided.")

    proj = (project_path or Path.cwd()).resolve()

    # Resolve from preset or explicit args
    if preset:
        p_prompt, p_tools, p_tier, p_hs, _agents = _load_preset(preset, proj)
        eff_prompt = prompt if prompt is not None else p_prompt
        eff_tools = tools if tools is not None else p_tools
        eff_tier = model_tier if model_tier != "default" else p_tier
        eff_hs = handoff_spec or p_hs
        subagent_type = preset
    else:
        eff_prompt = prompt or ""
        eff_tools = tools or ["read", "grep", "find"]
        eff_tier = model_tier
        eff_hs = handoff_spec
        subagent_type = "custom"

    # Build task envelope
    body = f"## Task\n{task}" if task else ""
    enveloped = wrap_envelope(body, custom_instructions, eff_hs)

    # Generate handoff path
    subagent_id = uuid4().hex[:8]
    handoffs_dir = proj / ".dagi" / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoffs_dir / f"{subagent_type}_{subagent_id}.md"

    # Log branch/start on parent log if a turn is open
    branch_id: str | None = None
    if parent_log is not None and parent_log.open_turn is not None:
        branch_id = f"{subagent_type}_{subagent_id}"
        parent_log.append(
            sev.BRANCH_START,
            {
                "branch": branch_id,
                "parent_branch": "main",
                "turn": parent_log.open_turn,
                "step": parent_log.open_step,
            },
        )

    # Build extra argv
    extra_argv: list[str] = []
    if tools is not None or preset is None:
        extra_argv.extend(["--tools", ",".join(eff_tools)])
    if eff_tier != "default":
        extra_argv.extend(["--model-tier", eff_tier])

    # Write effective prompt to a temp file and forward via --system-prompt-file.
    # This is the only way to deliver eff_prompt (preset or caller override) to the
    # subprocess — subagent_main.py reads it via --system-prompt-file and bypasses
    # load_subagent_prompt() when this arg is present.
    fd, prompt_tmp = tempfile.mkstemp(suffix=".md", prefix="dagi_prompt_")
    try:
        os.close(fd)
        Path(prompt_tmp).write_text(eff_prompt, encoding="utf-8")
        extra_argv.extend(["--system-prompt-file", prompt_tmp])

        raw = _runner.run_subagent(
            subagent_type=subagent_type,
            task=enveloped,
            project_path=proj,
            handoff_path=handoff_path,
            timeout=timeout,
            on_event=on_event,
            extra_argv=extra_argv if extra_argv else None,
        )
    finally:
        Path(prompt_tmp).unlink(missing_ok=True)

    result = _build_result(raw, handoff_path)
    result.branch_id = branch_id
    return result


def resume_subagent_by_pid(
    pid: int, extra_seconds: float = 120.0,
) -> SubagentResult:
    """Resume a timed-out subagent by PID."""
    raw = _runner.resume_subagent(pid, extra_seconds)
    handoff_path = Path(raw.get("handoff", ""))
    return _build_result(raw, handoff_path)
