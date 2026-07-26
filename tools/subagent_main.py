"""subagent_main.py — piped subagent entry point, spawned by tools/_subagent_runner.py.

Reads a task from --task-file, runs it through a typed subagent's tool
registry, emits newline-delimited JSON events to stdout, and writes a
handoff report. Not intended to be run interactively.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env before config_loader reads API keys

import yaml

from agent import DAGI_ROOT
from agent.config_loader import resolve_model_config
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from agent.prompts import load_subagent_prompt
from agent.tools import build_subagent_registry

_AGENTS_MD_TYPES = {
    "explore_files": ["cwd"],
    "worker": ["dagi", "cwd"],
    "review": ["dagi", "cwd"],
}

_HANDOFF_RETRY_PROMPT = (
    "You ended without calling `write_handoff`. Call it now with your complete report."
)


def _apply_worker_config(config: AgentConfig) -> AgentConfig:
    """Return a flattened config that uses worker_model (falls back to default)."""
    w = config.worker_config or config
    return replace(
        config,
        model=w.model,
        base_url=w.base_url,
        api_key=w.api_key,
        thinking=w.thinking,
        context_window=w.context_window,
        reserve_tokens=w.reserve_tokens,
        keep_recent_tokens=w.keep_recent_tokens,
        plan_mode=False,
        plan_file=None,
        worker_config=None,
        advanced_config=None,
    )


def _apply_advanced_config(config: AgentConfig) -> AgentConfig:
    """Return a flattened config that uses advanced_model (falls back to default)."""
    a = config.advanced_config or config
    return replace(
        config,
        model=a.model,
        base_url=a.base_url,
        api_key=a.api_key,
        thinking=a.thinking,
        context_window=a.context_window,
        reserve_tokens=a.reserve_tokens,
        keep_recent_tokens=a.keep_recent_tokens,
        plan_mode=False,
        plan_file=None,
        worker_config=None,
        advanced_config=None,
    )


def _extract_final_assistant_text(messages: list) -> str:
    """Return the last non-empty assistant text from a message list."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [
                    blk.get("text", "")
                    for blk in content
                    if isinstance(blk, dict) and blk.get("type") == "text"
                ]
                text = "\n".join(parts).strip()
            else:
                text = (content or "").strip()
            if text:
                return text
    return ""


def _ensure_handoff(loop: AgentLoop, handoff_path: Path) -> None:
    """Ensure a handoff report exists, retrying once, then scraping with an unverified flag.

    If `handoff_path` is missing after the initial `loop.run()` call, gives the subagent
    one corrective retry naming `write_handoff` explicitly. If it's still missing after
    that, scrapes the final assistant text into a minimal handoff and writes a sidecar
    `_unverified.flag` file so the caller can report degraded status.
    """
    if handoff_path.exists():
        return

    try:
        loop.run(_HANDOFF_RETRY_PROMPT)
    except Exception as exc:
        print(
            json.dumps({"type": "error", "phase": "handoff_retry", "message": str(exc)}),
            flush=True,
        )

    if handoff_path.exists():
        return

    from tools._handoff_format import unverified_flag_path

    final_text = _extract_final_assistant_text(loop._messages)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(
        f"# Handoff\n\n{final_text or '(subagent produced no output)'}",
        encoding="utf-8",
    )
    unverified_flag_path(handoff_path).write_text("1", encoding="utf-8")


def _build_pipe_callbacks() -> AgentCallbacks:
    """Build callbacks that emit newline-delimited JSON events to stdout."""

    def _emit(evt: dict) -> None:
        print(json.dumps(evt), flush=True)

    return AgentCallbacks(
        on_tool_start=lambda name, _d, args: _emit({
            "type": "tool_call", "name": name, "args": args[:200],
        }),
        on_tool_end=lambda name, result: _emit({
            "type": "tool_result", "name": name, "chars": len(result),
        }),
        on_assistant_text=lambda text: (
            _emit({"type": "message", "content": text}) if text.strip() else None
        ),
        on_reasoning=lambda text: (
            _emit({"type": "reasoning", "content": text[:120]}) if text.strip() else None
        ),
        on_model_switch=lambda _f, to: _emit({"type": "status", "text": f"→ {to}"}),
        on_error=lambda e: _emit({"type": "error", "message": str(e)}),
        on_compaction=lambda kept, removed: _emit({
            "type": "status", "text": f"compacted ({removed} msgs removed, {kept} kept)",
        }),
        on_token_update=lambda i, o, c, t: None,  # silent in pipe mode
    )


def _load_optional_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _build_subagent_system_prompt(subagent_type: str, project_path: Path) -> str:
    base = load_subagent_prompt(subagent_type)
    which = _AGENTS_MD_TYPES.get(subagent_type, [])
    parts = [base]
    if "dagi" in which:
        md = _load_optional_md(DAGI_ROOT / "AGENTS.md")
        if md:
            parts.append(md)
    if "cwd" in which:
        md = _load_optional_md(project_path / "AGENTS.md")
        if md:
            parts.append(md)
    return "\n\n---\n\n".join(parts)


def run_subagent_pipe_mode(
    subagent_type: str,
    task_file: str,
    handoff: str,
    project: Optional[str],
    model: Optional[str],
    system_prompt_file: Optional[str] = None,
) -> None:
    project_path = Path(project).resolve() if project else Path.cwd()
    handoff_path = Path(handoff)
    task = Path(task_file).read_text(encoding="utf-8")

    base_config = resolve_model_config(model, project_path=project_path)

    config_yaml = (
        project_path / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    )
    if config_yaml.exists():
        sa_cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        model_tier = sa_cfg.get("model_tier", "worker")
    elif subagent_type == "custom":
        model_tier = "advanced"
    else:
        model_tier = "worker"

    typed_config = (
        _apply_advanced_config(base_config)
        if model_tier == "advanced"
        else _apply_worker_config(base_config)
    )
    typed_config.project_path = project_path

    callbacks = _build_pipe_callbacks()
    registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=typed_config,
        project_path=project_path,
        callbacks=callbacks,
        memory_root=typed_config.memory_root,
        handoff_path=handoff_path,
    )

    if system_prompt_file:
        system_prompt = Path(system_prompt_file).read_text(encoding="utf-8")
    else:
        system_prompt = _build_subagent_system_prompt(subagent_type, project_path)

    loop = AgentLoop(
        config=typed_config,
        callbacks=callbacks,
        initial_messages=[{"role": "system", "content": system_prompt}],
        _registry=registry,
    )

    try:
        try:
            loop.run(task)
        except Exception as exc:
            print(json.dumps({"type": "error", "message": str(exc)}), flush=True)
        _ensure_handoff(loop, handoff_path)
    finally:
        loop.finish()

    print(json.dumps({"type": "done"}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Driverless AGI piped subagent runner")
    parser.add_argument("--subagent-type", dest="subagent_type", required=True)
    parser.add_argument("--task-file", dest="task_file", required=True)
    parser.add_argument("--handoff", dest="handoff", required=True)
    parser.add_argument("--project", dest="project", default=None)
    parser.add_argument("--model", dest="model", default=None)
    parser.add_argument("--system-prompt-file", dest="system_prompt_file", default=None)
    args = parser.parse_args()

    run_subagent_pipe_mode(
        subagent_type=args.subagent_type,
        task_file=args.task_file,
        handoff=args.handoff,
        project=args.project,
        model=args.model,
        system_prompt_file=args.system_prompt_file,
    )


if __name__ == "__main__":
    main()
