# Task 1 Report: Version-2 Parent-Fork Contract

## Scope

Implemented the parent-fork data contract required by inherited-subagent tasks:

- Added `agent.parent_context.ParentFork` and `ParentContextProvider` dataclasses.
- Added `ForkMode = Literal["spawn", "stable"]`.
- Added `build_fork_context_v2()` with the exact version-2 branch/request/child shape.
- Deep-copied request and allowed-tool data to prevent caller mutation.
- Rejected top-level `api_key`, `authorization`, and `credentials` request fields with clear
  `ValueError` messages.
- Re-exported `build_fork_context_v2` from `tools.subagent_api` without changing version-1
  `build_fork_context()`.

## TDD Evidence

1. Wrote `tests/test_parent_context.py` first.
2. Ran the focused test before implementation: RED during collection with
   `ModuleNotFoundError: No module named 'agent.parent_context'`.
3. Implemented the minimal contract module and re-export.
4. Ran focused and existing API tests with a workspace-local pytest temp directory:
   `conda run -n dagi python -m pytest tests/test_parent_context.py tests/test_subagent_api.py --basetemp .pytest-tmp -q`
5. Result: `34 passed`.

## Verification Concern

Pytest's default temp root (`C:\Users\alexr\AppData\Local\Temp\pytest-of-alexr`) is not
scannable under this environment and caused setup errors. Using `--basetemp .pytest-tmp`
avoids that unrelated environment permission issue.
