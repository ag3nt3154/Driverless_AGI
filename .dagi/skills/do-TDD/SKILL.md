---
name: do-TDD
description: Test-driven implementation of approved behaviors and bug fixes, with evidence returned to delivery.
---

# do-TDD

Use during approved implementation. Dagi loads this name as `do-tdd`.
Inside `deliver`, the main agent loads the skill and includes its instructions in worker
assignments; workers follow those instructions without delegating or loading another tool.
The main implementer follows the same cycle when implementing directly.

## Cycle

1. **Red:** Write a focused test of the required behavior. Run it and confirm it fails
   for the expected reason, not broken setup.
2. **Green:** Implement the smallest change that passes. Run relevant existing tests too.
3. **Refactor:** Improve the changed code without adding behavior. Keep tests passing.
4. Repeat for the next behavior.

For bug fixes, first reproduce the bug in a failing test. For pure refactoring,
establish passing behavior tests before changing the implementation.

## Test quality

- Test observable behavior; explain which incorrect production behavior would fail the test.
- Prefer real code; use mocks where isolation is necessary.
- Cover relevant boundaries and failure cases.
- If a new test immediately passes, check whether the behavior already exists or the
  test misses the requirement.

For changes without meaningful automated tests, explain the limitation and proposed
verification to the caller. Do not fabricate tests merely to satisfy the process.
If implementation preceded its test, disclose that deviation and establish regression
coverage; do not discard existing work automatically.

## Return

Report changes, failing/passing test evidence, and unresolved issues. Never hide failures
or unrun checks. Workers include this in their existing Checks and Results handoff.
`deliver` owns independent review, task acceptance, and full verification for planned
delivery; `enter-workflow` owns those steps and closure for bounded implementation.
This skill does not delegate, commit, or advance the workflow.
