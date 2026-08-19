"""Version-2 parent-fork data contract for inherited subagents."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal


ForkMode = Literal["spawn", "stable"]


_SECRET_FIELD_NAMES = frozenset(
    {
        "apikey",
        "authorization",
        "credentials",
        "accesstoken",
        "refreshtoken",
        "clientid",
        "clientsecret",
        "apisecret",
        "secretkey",
        "privatekey",
        "xapikey",
        "password",
        "passwd",
        "passphrase",
        "secret",
        "token",
        "secrets",
    }
)


@dataclass(frozen=True, slots=True)
class ParentFork:
    branch_id: str
    parent_cut_seq: int
    parent_surface_generation: int
    request: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParentContextProvider:
    capture_fork: Callable[[str, ForkMode], ParentFork]
    get_surface_generation: Callable[[], int]


def _normalise_field_name(name: str) -> str:
    """Compare common credential keys across snake/camel/kebab case."""
    return "".join(char for char in name.casefold() if char.isalnum())


def _find_secret_field(value: Any, path: str = "request") -> tuple[str, str] | None:
    """Return the first nested credential key and its path, if present."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and _normalise_field_name(key) in _SECRET_FIELD_NAMES:
                return path, key
            found = _find_secret_field(nested, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _find_secret_field(nested, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def build_fork_context_v2(
    fork: ParentFork,
    child_type: str,
    allowed_tools: list[str],
) -> dict[str, Any]:
    """Build a v2 fork context without exposing credentials to a child."""
    credential_metadata = {
        key: value for key, value in fork.request.items() if key != "tools"
    }
    secret = _find_secret_field(credential_metadata)
    if secret is not None:
        path, field = secret
        location = repr(field) if path == "request" else f"{path}.{field!r}"
        raise ValueError(f"Fork request must not contain secret field {location}")
    return {
        "version": 2,
        "branch": {
            "id": fork.branch_id,
            "parent_cut_seq": fork.parent_cut_seq,
            "parent_surface_generation": fork.parent_surface_generation,
        },
        "request": deepcopy(fork.request),
        "child": {"type": child_type, "allowed_tools": deepcopy(allowed_tools)},
    }
