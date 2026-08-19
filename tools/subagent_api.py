"""tools/subagent_api.py — Unified subagent execution function.

Public API for spawning subagents. Used by:
  - .dagi/subagents/<type>/main.py (auto-discovered BaseTool wrappers)
  - DAGI-authored workflow scripts (custom orchestration)

Wraps the low-level _subagent_runner subprocess machinery with preset
resolution, handoff auto-read, and a structured SubagentResult.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

import yaml

from agent import DAGI_ROOT as _DAGI_ROOT
from agent import session_events as sev
from agent.parent_context import ForkMode, ParentContextProvider, ParentFork, build_fork_context_v2
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


def build_fork_context(
    branch_id: str,
    parent_cut_seq: int,
    parent_surface_generation: int,
    request_snapshot: dict,
) -> dict:
    """Build a version-1 fork-context dict for the compact subprocess.

    The result is JSON-serializable and must NOT contain API keys or
    credentials. The child resolves credentials through its own
    configuration/environment path.
    """
    return {
        "version": 1,
        "branch": {
            "id": branch_id,
            "parent_cut_seq": parent_cut_seq,
            "parent_surface_generation": parent_surface_generation,
        },
        "request": {
            "model": request_snapshot["model"],
            "messages": request_snapshot["messages"],
            "tools": request_snapshot.get("tools", []),
            "parallel_tool_calls": request_snapshot.get("parallel_tool_calls", False),
            "extra_body": request_snapshot.get("extra_body", {}),
            "base_url": request_snapshot.get("base_url", ""),
        },
    }


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


def _write_fork_context_file(
    fork: ParentFork,
    subagent_type: str,
    tools: list[str],
) -> Path:
    """Write a v2 fork context whose lifecycle transfers to the runner."""
    fd, path_str = tempfile.mkstemp(suffix=".json", prefix="dagi_fork_context_")
    os.close(fd)
    path = Path(path_str)
    try:
        path.write_text(
            json.dumps(build_fork_context_v2(fork, subagent_type, tools)),
            encoding="utf-8",
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _extra_fork_context_path(extra_argv: list[str] | None) -> str | None:
    """Return the sole valid caller-supplied fork context path, if present."""
    if not extra_argv:
        return None
    paths: list[str] = []
    for index, arg in enumerate(extra_argv):
        if arg != "--fork-context":
            continue
        if index + 1 == len(extra_argv) or extra_argv[index + 1].startswith("--"):
            raise ValueError("--fork-context requires a path")
        paths.append(extra_argv[index + 1])
    if len(paths) > 1:
        raise ValueError("multiple --fork-context values are not allowed")
    return paths[0] if paths else None


def _resolve_subagent_options(
    preset: str | None,
    prompt: str | None,
    tools: list[str] | None,
    model_tier: str,
    handoff_spec: str,
    project_path: Path,
) -> tuple[str, list[str], str, str, str]:
    """Resolve preset defaults and explicit subagent execution options."""
    if preset:
        p_prompt, p_tools, p_tier, p_hs, _agents = _load_preset(preset, project_path)
        return (
            prompt if prompt is not None else p_prompt,
            tools if tools is not None else p_tools,
            model_tier if model_tier != "default" else p_tier,
            handoff_spec or p_hs,
            preset,
        )
    return prompt or "", tools or ["read", "grep", "find"], model_tier, handoff_spec, "custom"


def _invoke_runner(
    subagent_type: str,
    task: str,
    project_path: Path,
    handoff_path: Path,
    timeout: float,
    on_event: Callable[[str], None] | None,
    extra_argv: list[str],
    prompt: str,
    inherited_context_path: Path | None,
) -> dict:
    """Forward prompt and execution data, retaining cleanup before registration fails."""
    fd, prompt_tmp = tempfile.mkstemp(suffix=".md", prefix="dagi_prompt_")
    try:
        os.close(fd)
        Path(prompt_tmp).write_text(prompt, encoding="utf-8")
        extra_argv.extend(["--system-prompt-file", prompt_tmp])
        return _runner.run_subagent(
            subagent_type=subagent_type,
            task=task,
            project_path=project_path,
            handoff_path=handoff_path,
            timeout=timeout,
            on_event=on_event,
            extra_argv=extra_argv or None,
        )
    except Exception:
        if (
            inherited_context_path is not None
            and not _runner.owns_fork_context_path(inherited_context_path)
        ):
            inherited_context_path.unlink(missing_ok=True)
        raise
    finally:
        Path(prompt_tmp).unlink(missing_ok=True)


def _prepare_inherited_context(
    subagent_type: str,
    subagent_id: str,
    parent_log: "SessionLog | None",
    parent_context: ParentContextProvider | None,
    fork_mode: ForkMode,
    tools: list[str],
) -> tuple[str | None, ParentFork | None, Path | None]:
    """Create an inherited fork or preserve legacy parent-log branch recording."""
    branch_id = f"{subagent_type}_{subagent_id}" if parent_context is not None else None
    if parent_context is not None:
        fork = parent_context.capture_fork(branch_id, fork_mode)
        return branch_id, fork, _write_fork_context_file(fork, subagent_type, tools)
    if (
        parent_log is not None
        and parent_log.open_turn is not None
        and parent_log.open_step is not None
    ):
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
    return branch_id, None, None


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
    extra_argv: list[str] | None = None,
    fork_context_path: Path | str | None = None,
    parent_context: ParentContextProvider | None = None,
    fork_mode: ForkMode = "spawn",
    handoff_dir: Path | str | None = None,
) -> SubagentResult:
    """Spawn a subagent and return its result with auto-read handoff."""
    if preset is None and prompt is None:
        raise ValueError("Either preset or prompt must be provided.")
    extra_fork_context = _extra_fork_context_path(extra_argv)
    if parent_context is not None and (
        fork_context_path is not None or extra_fork_context is not None
    ):
        raise ValueError(
            "parent_context cannot be combined with fork_context_path or --fork-context"
        )
    if fork_context_path is not None and extra_fork_context is not None:
        if str(fork_context_path) != extra_fork_context:
            raise ValueError("Conflicting fork_context_path and --fork-context values")

    proj = (project_path or Path.cwd()).resolve()

    eff_prompt, eff_tools, eff_tier, eff_hs, subagent_type = _resolve_subagent_options(
        preset, prompt, tools, model_tier, handoff_spec, proj,
    )

    # Build task envelope
    body = f"## Task\n{task}" if task else ""
    enveloped = wrap_envelope(body, custom_instructions, eff_hs)

    # Generate handoff path
    subagent_id = uuid4().hex[:8]
    handoffs_dir = Path(handoff_dir) if handoff_dir is not None else proj / ".dagi" / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = handoffs_dir / f"{subagent_type}_{subagent_id}.md"

    branch_id, fork, inherited_context_path = _prepare_inherited_context(
        subagent_type,
        subagent_id,
        parent_log,
        parent_context,
        fork_mode,
        eff_tools,
    )

    # Build extra argv (merge caller-supplied args with internally-built ones)
    _extra_argv: list[str] = []
    if tools is not None or preset is None:
        _extra_argv.extend(["--tools", ",".join(eff_tools)])
    if eff_tier != "default":
        _extra_argv.extend(["--model-tier", eff_tier])
    if extra_argv:
        _extra_argv.extend(extra_argv)
    selected_fork_context = inherited_context_path or fork_context_path
    if selected_fork_context is not None and extra_fork_context is None:
        _extra_argv.extend(["--fork-context", str(selected_fork_context)])

    raw = _invoke_runner(
        subagent_type, enveloped, proj, handoff_path, timeout, on_event,
        _extra_argv, eff_prompt, inherited_context_path,
    )

    result = _build_result(raw, handoff_path)
    result.branch_id = branch_id
    if fork is not None and result.is_ok:
        if parent_context.get_surface_generation() != fork.parent_surface_generation:
            return SubagentResult(
                status="stale",
                handoff_text="",
                handoff_path=handoff_path,
                session_log_path=result.session_log_path,
                pid=result.pid,
                escalation=None,
                branch_id=branch_id,
            )
    return result


def resume_subagent_by_pid(
    pid: int, extra_seconds: float = 120.0,
) -> SubagentResult:
    """Resume a timed-out subagent by PID."""
    raw = _runner.resume_subagent(pid, extra_seconds)
    handoff_path = Path(raw.get("handoff", ""))
    return _build_result(raw, handoff_path)
