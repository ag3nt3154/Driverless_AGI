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
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env before config_loader reads API keys

import yaml

from agent import DAGI_ROOT
from agent.config_loader import load_raw_config, resolve_model_config
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
        expression_interval=w.expression_interval,
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
        expression_interval=a.expression_interval,
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
    if "<<TASK_END>>" in clean:
        return False, "Truncated final handoff text"
    if not required_sections:
        return True, ""
    expected = [_section_heading(section) for section in required_sections]
    expected_set = set(expected)
    headings = _handoff_headings(clean)
    if headings and clean[:headings[0][2]].strip():
        return False, "Unexpected preamble before first section"
    seen: set[str] = set()
    for index, (marks, title, _start, end) in enumerate(headings):
        heading = f"{marks} {title}"
        if marks != "##":
            if f"## {title}" in expected_set:
                return False, f"Expected level-2 heading for section: {title}"
            return False, f"Unknown section: {heading}"
        if heading not in expected_set:
            return False, f"Unknown section: {heading}"
        if heading in seen:
            return False, f"Duplicate section: {heading}"
        seen.add(heading)
        body_end = headings[index + 1][2] if index + 1 < len(headings) else len(clean)
        if not clean[end:body_end].strip():
            return False, f"Empty section: {heading}"
    missing = [heading for heading in expected if heading not in seen]
    if missing:
        return False, f"Missing required sections: {', '.join(missing)}"
    actual = [f"{marks} {title}" for marks, title, _start, _end in headings]
    if actual != expected:
        return False, f"Sections out of order: expected {', '.join(expected)}"
    return True, ""


def _section_heading(section: str) -> str:
    """Convert a configured section name to its exact level-two heading."""
    clean = section.strip()
    return clean if clean.startswith("## ") else f"## {clean.lstrip('#').strip()}"


def _handoff_headings(text: str) -> list[tuple[str, str, int, int]]:
    """Return Markdown heading lines and their body boundaries."""
    headings: list[tuple[str, str, int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("#"):
            marks, _, title = stripped.partition(" ")
            headings.append((marks, title.strip(), offset, offset + len(line)))
        offset += len(line)
    return headings


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
    requested_model = str(request["model"])
    inherited_url = str(request.get("base_url") or "")
    try:
        local_config = resolve_model_config(requested_model, project_path=project_path)
    except KeyError:
        model_id = _find_inherited_model_id(requested_model, inherited_url, project_path)
        local_config = resolve_model_config(model_id, project_path=project_path)
    if (
        local_config.model != requested_model
        or _normalise_provider_url(inherited_url)
        != _normalise_provider_url(str(local_config.base_url or ""))
    ):
        model_id = _find_inherited_model_id(requested_model, inherited_url, project_path)
        local_config = resolve_model_config(model_id, project_path=project_path)
    local_url = str(local_config.base_url or "")
    if not local_config.api_key:
        raise ValueError(
            "Inherited provider credentials unavailable: local provider has no API key"
        )
    if local_config.model != request["model"]:
        raise ValueError(
            "Inherited provider mismatch: local credentials are for a different model"
        )
    if _normalise_provider_url(inherited_url) != _normalise_provider_url(local_url):
        raise ValueError(
            "Inherited provider mismatch: parent base_url does not match the local "
            "credentials provider"
        )
    return replace(
        local_config,
        model=request["model"],
        base_url=inherited_url or local_url,
        project_path=project_path,
        worker_config=None,
        advanced_config=None,
    )


def _find_inherited_model_id(model: str, base_url: object, project_path: Path) -> str:
    """Find the local catalog ID matching a provider-facing model and endpoint."""
    raw = load_raw_config()
    project_config = project_path / ".dagi" / "config.yaml"
    project_raw = (
        yaml.safe_load(project_config.read_text(encoding="utf-8")) or {}
        if project_config.exists()
        else {}
    )
    catalog = {**(raw.get("models") or {}), **(project_raw.get("models") or {})}
    requested_url = _normalise_provider_url(str(base_url or ""))
    matches = [
        model_id
        for model_id, entry in catalog.items()
        if entry.get("model") == model
        and (
            not requested_url
            or _normalise_provider_url(str(entry.get("api_url") or "")) == requested_url
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            "Inherited provider mismatch: local catalog has a different model or "
            "base_url"
        )
    return matches[0]


def _normalise_provider_url(url: str) -> str:
    """Normalize harmless endpoint spelling differences before comparing providers."""
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/"),
            parsed.query,
            parsed.fragment,
        )
    )


def run_forked_subagent_mode(
    fork_context_path: str,
    task_file: str,
    handoff_path: str,
    project_path: str | None,
    system_prompt_file: str | None = None,
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
    allowed_tools = list(child.get("allowed_tools", []))
    implementation_registry = build_subagent_registry(
        subagent_type=subagent_type,
        config=config,
        project_path=project,
        callbacks=callbacks,
        memory_root=config.memory_root,
        handoff_path=Path(handoff_path),
        tool_names_override=allowed_tools,
    )
    effective_allowed_tools = _effective_allowed_tools(
        allowed_tools, implementation_registry, request.get("tools", [])
    )
    registry = build_inherited_registry(
        request.get("tools", []),
        implementation_registry,
        set(effective_allowed_tools),
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
    prompt = ""
    if system_prompt_file:
        prompt = Path(system_prompt_file).read_text(encoding="utf-8").strip()
    required_sections = _load_required_sections(subagent_type, project)
    task = _build_inherited_task(
        prompt,
        task,
        effective_allowed_tools,
        subagent_type,
        required_sections,
    )
    try:
        loop.run(task)
        text, error = _read_inherited_handoff(Path(handoff_path), required_sections)
        ok = not error
        if not ok:
            loop.run(
                f"Your handoff was not accepted: {error}. "
                "Call `write_handoff` now with the complete corrected report."
            )
            text, error = _read_inherited_handoff(Path(handoff_path), required_sections)
            ok = not error
        if not ok:
            print(json.dumps({"type": "error", "message": error}), flush=True)
            raise ValueError(error)
    finally:
        loop.finish()
    print(json.dumps({"type": "done"}), flush=True)


def _read_inherited_handoff(
    handoff_path: Path, required_sections: list[str]
) -> tuple[str, str]:
    """Read and validate the report produced by the child's final tool call."""
    if not handoff_path.exists():
        return "", "Missing handoff file"
    text = handoff_path.read_text(encoding="utf-8")
    ok, error = _validate_final_handoff(text, required_sections)
    return (text, "") if ok else (text, error)


def _build_inherited_task(
    prompt: str,
    task: str,
    effective_allowed_tools: list[str],
    subagent_type: str,
    required_sections: list[str],
) -> str:
    """Place the inherited execution contract between preset instructions and task."""
    allowed = ", ".join(effective_allowed_tools) or "none"
    sections = ", ".join(_section_heading(section) for section in required_sections)
    output = sections or "the handoff format requested by the task"
    contract = (
        "## Inherited Child Contract\n"
        f"- Effective allowed tools: {allowed}\n"
        "- Calls to any other provider-visible tool are blocked and return "
        f"`Error: Access blocked for tool '<name>' in subagent '{subagent_type}'. "
        f"Allowed tools: {allowed}`. Do not retry a blocked call.\n"
        "- Complete the task, then call `write_handoff` as your final action. "
        "The tool ends your turn; do not emit `END_OF_RESPONSE` afterward.\n"
        f"- Pass the complete report to `write_handoff`. Required format: {output}."
    )
    parts = [part for part in (prompt, contract, task) if part]
    return "\n\n---\n\n".join(parts)


def _effective_allowed_tools(
    allowed_tools: list[str], implementation_registry, schemas: list[dict]
) -> list[str]:
    """Return authorized tools that are both implemented and provider-visible."""
    visible_names = {
        schema.get("function", {}).get("name")
        for schema in schemas
        if isinstance(schema, dict)
    }
    authorized = list(allowed_tools)
    if "write_handoff" not in authorized:
        authorized.append("write_handoff")
    return [
        name
        for name in authorized
        if name in visible_names and implementation_registry.get(name) is not None
    ]


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
                system_prompt_file=args.system_prompt_file,
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
