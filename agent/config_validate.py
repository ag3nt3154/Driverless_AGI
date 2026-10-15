"""
agent/config_validate.py — strict pre-save checks for {DAGI_ROOT}/.dagi/config.yaml.

`tool_catalog()` lists the tool names a config may refer to and `validate()`
checks an `agent.config_editor.ConfigDocument` before it is saved. Errors block
the save; warnings do not.

This module is UI-agnostic (no GUI toolkit imports).
"""
from __future__ import annotations

import ast
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from agent import DAGI_ROOT

if TYPE_CHECKING:
    from agent.config_editor import ConfigDocument


# ── Tool catalog ───────────────────────────────────────────────────────────


def _class_tool_names(main_py: Path) -> list[str]:
    """Literal class-level ``name = "..."`` values in `main_py`, parsed with
    `ast` (the file is never imported or executed). Unreadable files yield []."""
    try:
        tree = ast.parse(main_py.read_text(encoding="utf-8"), filename=str(main_py))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return []
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                targets, value = stmt.targets, stmt.value
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
                targets, value = [stmt.target], stmt.value
            else:
                continue
            if (any(isinstance(t, ast.Name) and t.id == "name" for t in targets)
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                names.append(value.value)
    return names


def tool_catalog(dagi_root: Path = DAGI_ROOT) -> list[str]:
    """Tool names a config may refer to: built-ins (`agent.tools.KNOWN_TOOL_NAMES`)
    then subagent tools from ``{dagi_root}/.dagi/subagents/*/main.py``.

    De-duplicated, order preserved. Project tools are not included.
    """
    from agent.tools import KNOWN_TOOL_NAMES

    names = list(KNOWN_TOOL_NAMES)
    seen = set(names)
    subagents = Path(dagi_root) / ".dagi" / "subagents"
    if subagents.is_dir():
        for main_py in sorted(subagents.glob("*/main.py")):
            for name in _class_tool_names(main_py):
                if name not in seen:
                    seen.add(name)
                    names.append(name)
    return names


# ── Validation ─────────────────────────────────────────────────────────────

_POSITIVE_INT_KEYS = (
    "context_window", "keep_recent_tokens", "reserve_tokens", "max_output_tokens",
    "max_continuations", "truncate_edge_chars",
)
_NON_NEGATIVE_INT_KEYS = ("null_response_retries", "api_error_retries")
_NULLABLE_KEYS = {"max_output_tokens"}  # null = no output cap (loader default)
_BOOL_KEYS = ("sandbox_mode", "code_mode", "computer_use")
_MODEL_KEYS = ("default_model", "worker_model", "advanced_model")
_TOOL_LIST_KEYS = ("tools", "disabled_tools")
_BOARD_URL_KEY = "services.message_board.url"
_VALIDATE_PREFIX = ".config.validate."
_MISSING: Any = object()


@dataclass
class ValidationResult:
    """Errors block a save; warnings are shown but do not."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_scalars(doc: ConfigDocument, errors: list[str]) -> None:
    for key in (*_POSITIVE_INT_KEYS, *_NON_NEGATIVE_INT_KEYS):
        value = doc.get(key, _MISSING)
        if value is _MISSING or (value is None and key in _NULLABLE_KEYS):
            continue
        minimum, kind = (0, "a non-negative") if key in _NON_NEGATIVE_INT_KEYS else (1, "a positive")
        if not _is_int(value) or value < minimum:
            errors.append(f"{key} must be {kind} integer (got {value!r}).")
    for key in _BOOL_KEYS:
        value = doc.get(key)  # null = absent: the loader reads bool(None) as False
        if value is not None and not isinstance(value, bool):
            errors.append(f"{key} must be true or false (got {value!r}).")


def _is_http_url(value: Any) -> bool:
    """`http(s)://host[:port]`, optionally with a trailing slash."""
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    try:
        parts = urlsplit(value)
        port = parts.port  # raises ValueError for a non-numeric / out-of-range port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and port != 0
    )


def _check_paths_and_services(doc: ConfigDocument, errors: list[str]) -> None:
    memory_root = doc.get("memory_root")
    if memory_root not in (None, ""):
        if not isinstance(memory_root, str) or not Path(memory_root).expanduser().is_dir():
            errors.append(f"memory_root is not an existing directory: {memory_root!r}.")
    url = doc.get(_BOARD_URL_KEY)
    if url not in (None, "") and not _is_http_url(url):
        errors.append(f"{_BOARD_URL_KEY} must look like http(s)://host[:port] (got {url!r}).")


def _check_tools(
    doc: ConfigDocument, errors: list[str], warnings: list[str], catalog: list[str],
) -> None:
    known = set(catalog)
    for key in _TOOL_LIST_KEYS:
        value = doc.get(key, _MISSING)
        if value is _MISSING:
            continue  # absent `tools` = all tools
        if value is not None and not isinstance(value, list):
            errors.append(f"{key} must be a list of tool names (got {value!r}).")
            continue
        items = doc.list_items(key)
        # The loader reads an empty/null `tools` as ALL tools, so a present key
        # with nothing enabled (e.g. every entry commented out) is refused; to
        # mean "all tools", remove the key. An explicit `tools: null` cannot be
        # told apart: ruamel serializes it as a bare `tools:`.
        if key == "tools" and not value and not any(on for _, on in items):
            errors.append("At least one tool must be enabled.")
        for name, enabled in items:
            message = f"Unknown tool: {name}"
            if enabled and name not in known and message not in warnings:
                warnings.append(message)


def _check_api_key(model_id: str, entry: Any, warnings: list[str]) -> None:
    """Missing API key env var: an environment problem, not a config error."""
    if not isinstance(entry, dict) or entry.get("api_key") or entry.get("client_script"):
        return
    env = entry.get("api_key_env", "OPENAI_API_KEY")
    if not os.environ.get(str(env), ""):
        warnings.append(
            f"Environment variable {env} is not set (API key for model '{model_id}')."
        )


def _check_with_loader(doc: ConfigDocument, errors: list[str], warnings: list[str]) -> None:
    """Model IDs and a full `resolve_model_config` run against the document text.

    The text is written to a uniquely named temp file next to the config so
    the loader reads the model catalog from the same `.dagi/` directory and
    concurrent validations never share (or delete) each other's file. The
    resolve step is skipped when earlier checks already failed: it would mostly
    repeat those errors, and it executes the default model's client script.

    Every exception from the loader is an error, OSError included (e.g. a
    missing client script): `resolve_model_config` does not raise for a
    missing API key — `_check_api_key` warns about that instead.
    """
    from agent import config_loader

    try:
        fd, name = tempfile.mkstemp(
            prefix=_VALIDATE_PREFIX, suffix=".yaml", dir=doc.path.parent,
        )
    except OSError as exc:
        errors.append(f"Could not write validation file in {doc.path.parent}: {exc}")
        return
    tmp = Path(name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(doc.text())
        except OSError as exc:
            errors.append(f"Could not write validation file {tmp}: {exc}")
            return
        try:
            raw = config_loader.load_raw_config(config_path=tmp)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Could not load the config: {exc}")
            return
        models = raw.get("models") or {}
        if not isinstance(models, dict):
            errors.append("models must be a mapping of model IDs.")
            return
        for key in _MODEL_KEYS:
            model_id = doc.get(key)
            if model_id in (None, ""):
                continue
            if not isinstance(model_id, str) or model_id not in models:
                errors.append(f"{key}: unknown model {model_id!r}.")
            else:
                _check_api_key(model_id, models[model_id], warnings)
        if errors:
            return
        try:
            config_loader.resolve_model_config(config_path=tmp)
        except KeyError as exc:
            errors.append(str(exc.args[0]) if exc.args else repr(exc))
        except Exception as exc:  # noqa: BLE001 — ValueError, OSError, anything else
            errors.append(str(exc) or type(exc).__name__)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def validate(
    doc: ConfigDocument,
    *,
    dagi_root: Path | None = None,
    catalog: list[str] | None = None,
) -> ValidationResult:
    """Strict pre-save checks of `doc`; nothing should be saved unless `.ok`.

    Errors: malformed numeric/boolean settings, unknown model IDs (catalog read
    from ``doc.path.parent / "model_config"`` plus inline ``models:``), a missing
    `memory_root` directory, a `tools` list with nothing enabled, a malformed
    message-board URL, and anything `resolve_model_config` rejects.
    Warnings: tool names outside `catalog` (default: `tool_catalog(dagi_root)`)
    and missing API key environment variables.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if catalog is None:
        catalog = tool_catalog(dagi_root if dagi_root is not None else DAGI_ROOT)
    _check_scalars(doc, errors)
    _check_paths_and_services(doc, errors)
    _check_tools(doc, errors, warnings, catalog)
    _check_with_loader(doc, errors, warnings)
    return ValidationResult(errors, warnings)
