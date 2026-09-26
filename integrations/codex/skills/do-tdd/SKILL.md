---
name: do-tdd
description: Implement approved behavior and bug fixes with meaningful red/green/refactor evidence; use a passing baseline for pure refactors and honest alternative checks when tests are unsuitable.
---

# Test-driven implementation

Use during approved implementation. The main agent includes these full instructions in
worker assignments; the main implementer follows the same process for direct work.

1. Red: write a focused test of required observable behavior and confirm failure for the
   expected reason. Broken setup or an unavailable dependency is not behavioral red.
2. Green: implement the smallest change that passes; run relevant existing tests too.
3. Refactor: improve changed code without adding behavior; keep checks passing.
4. Repeat for the next behavior.

For bug fixes, reproduce the bug first. For pure refactors, establish passing behavior
coverage before changing code. Explain which incorrect production behavior each test catches.
Prefer real code; isolate dependencies with mocks only where needed. Cover relevant boundaries
and failures. An immediately passing new test may mean the behavior exists or the test misses it.

For documentation or other changes without meaningful automated tests, explain the limitation
and use appropriate inspection, scenario review, or other observable verification. Do not
fabricate tests to satisfy ceremony. If code preceded a test, disclose the deviation and add
regression coverage; do not discard existing work automatically.

Report changed files, actual red/green evidence, unrun checks, and unresolved issues in the
worker's native handoff. `deliver` owns architectural task review/acceptance and integrated
verification; `enter-workflow` owns bounded-task review. This skill does not delegate, commit,
or advance the lifecycle.
