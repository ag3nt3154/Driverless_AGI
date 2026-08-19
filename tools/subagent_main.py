"""subagent_main.py — piped subagent entry point, spawned by tools/_subagent_runner.py.

Reads a task from --task-file, runs it through a typed subagent's tool
registry, emits newline-delimited JSON events to stdout, and writes a
handoff report. Not intended to be run interactively.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env before config_loader reads API keys

import yaml

from agent import DAGI_ROOT
from agent.config_loader import resolve_model_config
from agent.inherited_registry import build_inherited_registry
from agent.loop import AgentCallbacks, AgentConfig, AgentLoop
from agent.prompts import load_subagent_prompt
from agent.tools import build_subagent_registry

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
        on_token_update=lambda i, o, c, t, ca=0: None,  # silent in pipe mode
    )


def _load_optional_md(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def _build_subagent_system_prompt(subagent_type: str, project_path: Path) -> str:
    base = load_subagent_prompt(subagent_type)
    config_yaml = (
        project_path / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    )
    if not config_yaml.exists():
        config_yaml = DAGI_ROOT / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    agents_md_list: list[str] = []
    if config_yaml.exists():
        sa_cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        agents_md_list = sa_cfg.get("agents_md", [])

    parts = [base]
    if "dagi" in agents_md_list:
        md = _load_optional_md(DAGI_ROOT / "AGENTS.md")
        if md:
            parts.append(md)
    if "cwd" in agents_md_list:
        md = _load_optional_md(project_path / "AGENTS.md")
        if md:
            parts.append(md)
    return "\n\n---\n\n".join(parts)


def _resolve_inherited_model(
    fork_context: dict | None,
) -> tuple[str, str]:
    """Resolve model and base_url from a fork-context dict.

    Raises ValueError if fork_context is None (inherit without context).
    """
    if fork_context is None:
        raise ValueError(
            "model_tier 'inherit' requires a fork-context file"
        )
    req = fork_context["request"]
    return req["model"], req.get("base_url", "")


def _validate_compact_response(response) -> tuple[bool, str]:
    """Validate a compact model's response. Returns (ok, error_message)."""
    choice = response.choices[0]
    msg = choice.message
    if getattr(msg, "tool_calls", None):
        return False, "Tool-call response rejected for compact mode"
    finish = getattr(choice, "finish_reason", "stop")
    if finish == "length":
        return False, "Truncated response (finish_reason=length)"
    content = getattr(msg, "content", "") or ""
    if not content.strip():
        return False, "Empty response from compact model"
    return True, ""


def _validate_final_handoff(text: str, required_sections: list[str]) -> tuple[bool, str]:
    """Validate a generic inherited subagent's final assistant response."""
    clean = text.strip()
    if not clean:
        return False, "Empty final handoff text"
    if any(flag in clean for flag in ("<<END_OF_RESPONSE>>", "<<TASK_END>>")):
        return False, "Truncated final handoff text"
    headings = {line.strip() for line in clean.splitlines() if line.lstrip().startswith("#")}
    missing = []
    for section in required_sections:
        heading = section.strip()
        if not heading.startswith("#"):
            heading = f"## {heading}"
        if heading not in headings:
            missing.append(heading)
    if missing:
        return False, f"Missing required sections: {', '.join(missing)}"
    return True, ""


def _load_required_sections(subagent_type: str, project_path: Path) -> list[str]:
    """Read an optional final-handoff heading contract from the child preset."""
    for root in (project_path, DAGI_ROOT):
        config_path = root / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            return list(config.get("required_sections", []))
    return []


def _build_inherited_config(request: dict, project_path: Path) -> AgentConfig:
    """Resolve local credentials while retaining the inherited provider request identity."""
    local_config = resolve_model_config(None, project_path=project_path)
    return replace(
        local_config,
        model=request["model"],
        base_url=request.get("base_url") or local_config.base_url,
        project_path=project_path,
        worker_config=None,
        advanced_config=None,
    )


def run_forked_subagent_mode(
    fork_context_path: str,
    task_file: str,
    handoff_path: str,
    project_path: str | None,
) -> None:
    """Execute a v2 inherited child with its parent's exact provider prefix."""
    project = Path(project_path).resolve() if project_path else Path.cwd()
    context = json.loads(Path(fork_context_path).read_text(encoding="utf-8"))
    if context.get("version") != 2:
        raise ValueError(f"Unsupported fork-context version: {context.get('version')}")

    request = context["request"]
    child = context["child"]
    subagent_type = child["type"]
    messages = request["messages"]
    if not messages or messages[0].get("role") != "system":
        raise ValueError("Version-2 fork-context requires a leading system message")

    config = _build_inherited_config(request, project)
    callbacks = _build_pipe_callbacks()
    implementation_registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=config,
        project_path=project,
        callbacks=callbacks,
        memory_root=config.memory_root,
        handoff_path=None,
    )
    registry = build_inherited_registry(
        request.get("tools", []),
        implementation_registry,
        set(child.get("allowed_tools", [])),
        subagent_type,
    )
    loop = AgentLoop(
        config=config,
        callbacks=callbacks,
        initial_messages=messages,
        _registry=registry,
        _system_prompt_override=messages[0].get("content", ""),
        _preserve_request_prefix=True,
    )
    loop._extra_body = deepcopy(request.get("extra_body", {}))
    loop._parallel_tool_calls = bool(request.get("parallel_tool_calls", False))
    task = Path(task_file).read_text(encoding="utf-8")
    required_sections = _load_required_sections(subagent_type, project)
    try:
        text = loop.run(task)
        ok, error = _validate_final_handoff(text, required_sections)
        if not ok:
            text = loop.run(f"{task}\n\n{error}")
            ok, error = _validate_final_handoff(text, required_sections)
        if not ok:
            print(json.dumps({"type": "error", "message": error}), flush=True)
            raise ValueError(error)
        target = Path(handoff_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    finally:
        loop.finish()
    print(json.dumps({"type": "done"}), flush=True)


def _build_compact_task_message(
    prompt: str,
    handoff_spec: str,
) -> dict:
    """Build the compact task as a single user message."""
    content = (
        f"{prompt}\n\n---\n\n"
        f"Summarize the entire conversation above.\n\n"
        f"## Output\n{handoff_spec}"
    )
    return {"role": "user", "content": content}


def _compact_call_with_retry(client, create_kwargs: dict, emit_fn) -> object | None:
    """Make the compact API call with exponential-backoff retry. Returns response or None."""
    import openai
    import time

    max_retries = 3
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**create_kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError):
            if attempt == max_retries - 1:
                emit_fn({"type": "error", "message": "Exhausted retries for compact API call"})
                return None
            time.sleep(2 ** attempt)
    return None


def run_forked_compact_mode(
    fork_context_path: str,
    handoff_path: str,
    subagent_type: str,
    project_path: str | None,
) -> None:
    """Execute compact in forked mode: inherit prefix, single non-streaming API call."""
    import json
    import openai

    project = Path(project_path).resolve() if project_path else Path.cwd()
    hp = Path(handoff_path)
    fc = json.loads(Path(fork_context_path).read_text(encoding="utf-8"))

    if fc.get("version") != 1:
        raise ValueError(f"Unsupported fork-context version: {fc.get('version')}")

    req = fc["request"]
    model = req["model"]
    base_url = req.get("base_url", "")

    # Credentials come from environment, NOT from fork-context
    base_config = resolve_model_config(None, project_path=project)
    client = openai.OpenAI(
        api_key=base_config.api_key,
        base_url=base_url or base_config.base_url,
    )

    from tools.subagent_api import _load_preset
    prompt_text, _, _, handoff_spec, _ = _load_preset(subagent_type, project)

    messages = list(req["messages"])
    task_msg = _build_compact_task_message(prompt_text, handoff_spec)
    messages.append(task_msg)

    tools_list = req.get("tools", [])
    extra_body = req.get("extra_body", {})

    create_kwargs: dict = dict(
        model=model,
        messages=messages,
        parallel_tool_calls=req.get("parallel_tool_calls", False),
    )
    if tools_list:
        create_kwargs["tools"] = tools_list
    else:
        del create_kwargs["parallel_tool_calls"]
    if extra_body:
        create_kwargs["extra_body"] = extra_body

    _emit = lambda evt: print(json.dumps(evt), flush=True)
    response = _compact_call_with_retry(client, create_kwargs, _emit)

    if response is None:
        print(json.dumps({"type": "done"}), flush=True)
        return

    ok, error = _validate_compact_response(response)
    if not ok:
        _emit({"type": "error", "message": error})
        print(json.dumps({"type": "done"}), flush=True)
        return

    text = response.choices[0].message.content
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(text, encoding="utf-8")

    usage = getattr(response, "usage", None)
    if usage:
        cache_read = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details:
            cache_read = getattr(details, "cached_tokens", 0) or 0
        _emit({
            "type": "usage",
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "cache_read": cache_read,
        })

    print(json.dumps({"type": "done"}), flush=True)


def run_subagent_pipe_mode(
    subagent_type: str,
    task_file: str,
    handoff: str,
    project: Optional[str],
    model: Optional[str],
    system_prompt_file: Optional[str] = None,
    tool_names: Optional[list[str]] = None,
    model_tier_override: Optional[str] = None,
) -> None:
    project_path = Path(project).resolve() if project else Path.cwd()
    handoff_path = Path(handoff)
    task = Path(task_file).read_text(encoding="utf-8")

    config_yaml = (
        project_path / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    )
    if not config_yaml.exists():
        config_yaml = DAGI_ROOT / ".dagi" / "subagents" / subagent_type / "subagent_config.yaml"
    model_tier = model_tier_override or "worker"
    if config_yaml.exists():
        sa_cfg = yaml.safe_load(config_yaml.read_text(encoding="utf-8")) or {}
        model_tier = model_tier_override or sa_cfg.get("model_tier", "worker")
    if model_tier == "inherit":
        raise ValueError("model_tier 'inherit' requires a fork-context file")

    base_config = resolve_model_config(model, project_path=project_path)
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
        tool_names_override=tool_names,
    )

    # --system-prompt-file is the coupling point with tools/subagent_api.py:
    # run_subagent() writes eff_prompt (preset or caller override) to a temp file
    # and passes its path here via --system-prompt-file.  When present, it takes
    # precedence over _build_subagent_system_prompt() so the caller's resolved
    # prompt (including any caller-supplied override) is always honoured.
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
    parser.add_argument("--tools", dest="tools", default=None,
                        help="Comma-separated tool names to override preset")
    parser.add_argument("--model-tier", dest="model_tier", default=None)
    parser.add_argument("--fork-context", dest="fork_context", default=None)
    args = parser.parse_args()

    if args.fork_context:
        fork_context = json.loads(Path(args.fork_context).read_text(encoding="utf-8"))
        version = fork_context.get("version")
        if version == 1:
            run_forked_compact_mode(
                fork_context_path=args.fork_context,
                handoff_path=args.handoff,
                subagent_type=args.subagent_type,
                project_path=args.project,
            )
        elif version == 2:
            run_forked_subagent_mode(
                fork_context_path=args.fork_context,
                task_file=args.task_file,
                handoff_path=args.handoff,
                project_path=args.project,
            )
        else:
            raise ValueError(f"Unsupported fork-context version: {version}")
        return

    if args.model_tier == "inherit":
        raise ValueError("model_tier 'inherit' requires a fork-context file")

    run_subagent_pipe_mode(
        subagent_type=args.subagent_type,
        task_file=args.task_file,
        handoff=args.handoff,
        project=args.project,
        model=args.model,
        system_prompt_file=args.system_prompt_file,
        tool_names=args.tools.split(",") if args.tools else None,
        model_tier_override=args.model_tier,
    )


if __name__ == "__main__":
    main()
