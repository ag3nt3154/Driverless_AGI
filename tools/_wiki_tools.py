"""Shared project-wiki delegation and semantic handoff validation."""
from pathlib import Path, PureWindowsPath
import re

from agent import DAGI_ROOT
from tools import subagent_api
from tools._handoff_format import format_error_result


SECTIONS = {
    "query": ["Outcome", "Findings", "Wiki sources", "Conflicts", "Gaps", "Failure details"],
    "add": ["Outcome", "Created/updated paths", "Change summary", "Dated conflicts",
            "Partial writes", "Failure details"],
}


def _normalise_heading(heading):
    """Canonical form: first word capitalised, rest lowercase."""
    return heading.strip().capitalize()


_CANONICAL = {_normalise_heading(s): s for sections in SECTIONS.values() for s in sections}


def _validate_handoff(text, operation):
    parts = re.split(r"^## ([^\r\n]+)\r?\n?", text, flags=re.MULTILINE)
    raw_headings = parts[1::2]
    bodies = [b.strip() for b in parts[2::2]]
    # Map headings to canonical names, case-insensitive
    headings = [_CANONICAL.get(_normalise_heading(h), h) for h in raw_headings]
    if len(headings) != len(set(headings)):
        raise ValueError("Duplicate handoff sections")
    sections = dict(zip(headings, bodies))
    if any(not sections.get(name) for name in SECTIONS[operation]):
        raise ValueError("Missing or empty required handoff sections")
    outcome = sections["Outcome"].lower().strip().rstrip(".")
    allowed = {"success", "error", "no_results", "no results"}
    if operation == "query":
        pass  # all allowed values valid
    else:
        allowed -= {"no_results", "no results"}
    if outcome not in allowed:
        raise ValueError(f"Invalid handoff outcome: {sections['Outcome']}")
    if outcome == "error":
        raise ValueError("Child reported an error")
    if sections["Failure details"].lower().strip().rstrip(".") != "none":
        raise ValueError("Handoff reports failures despite a non-error outcome")
    if operation == "add" and sections["Partial writes"].lower().strip().rstrip(".") != "none":
        raise ValueError("Partial writes do not establish completed persistence")


def _scope_path(root, scope):
    relative = Path(scope)
    if relative.is_absolute() or PureWindowsPath(scope).drive or scope.startswith("\\"):
        raise ValueError("Scope must be wiki-relative")
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("Scope cannot escape the project wiki")
    return target


def _protocol(project, operation):
    for source in [project, DAGI_ROOT]:
        path = source / ".dagi" / "skills" / f"wiki-{operation}" / "SKILL.md"
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            marker = "## Child protocol"
            if marker not in text:
                raise ValueError(f"Missing child protocol in {path}")
            return text[text.index(marker):]
    raise ValueError(f"Missing wiki-{operation} skill protocol")


def _failure(result, operation, message):
    text = format_error_result({
        "message": f"{message}; status={result.status}; {result.message}",
        "exit_code": result.exit_code, "output_tail": result.output_tail,
    }, f"wiki-{operation}")
    if result.output_log_path:
        text += f"\nFull process log: {result.output_log_path}"
    if result.pid:
        text += f"\nProcess pid: {result.pid}"
    if result.handoff_text:
        text += f"\n--- Failed handoff (not success evidence) ---\n{result.handoff_text}"
    return text


def run_wiki(owner, operation, task, scope=""):
    """Spawn without inherited context; instructions confine file operations to wiki."""
    try:
        project = Path(owner._config.project_path).resolve()
        root = project / "wiki"
        if not root.is_dir():
            raise ValueError(f"Wiki missing or inaccessible: {root}. Run /init for this project.")
        target = _scope_path(root, scope)
        protocol = _protocol(project, operation)
        on_event = None
        if owner._callbacks and owner._callbacks.on_subagent_event_factory:
            on_event = owner._callbacks.on_subagent_event_factory(f"wiki-{operation}")
        result = subagent_api.run_subagent(
            task=task, preset=f"wiki-{operation}", prompt=protocol,
            custom_instructions=(
                f"Resolved wiki_root: {root}\nSearch scope first: {target}\n"
                f"All grep and find calls must use {root} (or a subdirectory of it) "
                f"as their path. Never search from the project root or outside the wiki."
            ),
            tools=["read", "grep", "find"] + (["write", "edit"] if operation == "add" else []),
            project_path=project, on_event=on_event, parent_log=owner._session_log,
        )
    except (OSError, ValueError) as exc:
        return f"[wiki-{operation} error] {exc}"
    if result.status != "ok" or result.exit_code not in (None, 0):
        return _failure(result, operation, "Verified process completion required")
    try:
        _validate_handoff(result.handoff_text, operation)
    except ValueError as exc:
        return _failure(result, operation, str(exc))
    return result.handoff_text
