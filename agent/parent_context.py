"""Version-2 parent-fork data contract for inherited subagents."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Literal


ForkMode = Literal["spawn", "stable"]


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


def build_fork_context_v2(
    fork: ParentFork,
    child_type: str,
    allowed_tools: list[str],
) -> dict[str, Any]:
    """Build a v2 fork context without exposing credentials to a child."""
    for field in ("api_key", "authorization", "credentials"):
        if field in fork.request:
            raise ValueError(f"Fork request must not contain secret field {field!r}")
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
