---
name: do-TDD
description: Draft sample for test-driven implementation of one approved behavior during delivery.
---

# do-TDD

Draft for discussion. This is a minimal sample; detailed policy remains undecided.
Dagi currently normalizes skill names to lowercase: invoke with `skill("do-tdd")`.

## Place in the workflow

The implementer uses this inside `deliver`, once per behavior in an approved task.
With delegated implementation, the worker runs this cycle and returns evidence to
the main agent. This skill does not delegate or restart the planning workflow.

## Simple sample

1. Read the approved behavior, acceptance criteria, and relevant existing tests.
2. Write a focused test of observable behavior. Run it and confirm that it fails
   because the behavior is missing or wrong, rather than because the setup is broken.
3. Make the smallest implementation change that passes the test.
4. Refactor where useful, keeping the test and relevant existing tests passing.
5. Return the changes, test commands/results, and any unresolved issues to the caller.
   Delivery owns independent review, task acceptance, and overall verification for planned
   delivery; enter-workflow owns those steps and closure for bounded implementation.

Example: for a bug accepting an invalid value, first demonstrate rejection is missing,
then implement rejection, and verify valid values still work.

## Still to decide

- Exceptions for documentation, configuration, and other changes without meaningful tests.
- Test selection, mocks, regression scope, and evidence expected in worker handoffs.
- How repair cycles and authorized commits fit around independent review.
