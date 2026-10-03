# R2 fix and implementation-session review — 2026-10-03

Reviewed `main` at `e382ad7b`, implementation commit `0f93469c`.
The working tree was clean at review start. No implementation edits were made.

## Fix verdict

No blocking correctness defect found in the scoped fix. Every END_TURN result is
bookkept in call order, the last output wins, and completion happens once after the
batch. Deferred reload/image messages follow all results. Keeping `on_handoff` before
the first handoff result matches the TUI and PySide rendering callbacks.

Verification performed for this review:

- 68 tests passed: `test_agent_loop`, `test_tool_dispatch_extract`, `test_tui_callbacks`.
- Offline probe: two handoffs, write events to disk, reload into a new SessionLog,
  attach it to a fresh loop, and run a second user turn. Both original call/result
  pairs survive in the second request. The final output remains `second`.
- The actual implementation session's durable event log reloads successfully into
  SessionLog and projects 230 messages.

### Coverage gap: the regression suite does not test restored continuation

`tests/test_agent_loop.py:562` labels its next-turn test as replay/persistence coverage,
but it runs both turns on the same loop. Its tracker is mocked and it does not write
or reload a session file. The separate event-pair test also checks live events only.
The manual disk probe passed, but add it as an automated regression: save events,
restore into a fresh loop, submit another user turn, and inspect the request pairs.
Add an image-plus-handoff ordering case as a useful companion to the reload case.

The dispatch size/complexity breach is already recorded and explicitly waived by the
user in the session. It is not a new blocker for this review.

## Session evidence

Latest modified root session containing the fix:
`.dagi/logs/session_2026-10-03_03-16-10.events.jsonl`, with its matching tracker JSONL.
It ran October 3, 11:16:10–11:32:06 Singapore time, about 15 minutes 56 seconds.
The later-started 03-23 sessions are reviewer sessions; they are not the root session.

The root contains 102 assistant steps and 126 tool calls/results. All 126 IDs pair
exactly once; no duplicate IDs, result-order violations, or intervening user/assistant
messages inside pending batches were found. Batch sizes: 82 singles, 16 doubles,
4 triples. This is correct sequential batch execution, not proof of parallel execution.
Only one real write_handoff occurred, so the session itself does not exercise the
duplicate-handoff fix. The tests and separate probe supply that evidence.

Positive evidence:

- Lines 276–277: five expected regression failures before implementation.
- Lines 321–327: seven new cases pass, then 167 related tests pass.
- Lines 346–353: independent review flags the size breach; user explicitly waives it.
- Lines 239–240: user approves implementation and commits on main. No Git-authority
  violation found. Lines 387–388 and 469–470 record the two commits.
- Lines 332–335: full suite reports 1457 passed, 2 skipped, 1 failed; the agent
  discloses the missing MarkItDown DOCX dependency rather than claiming a clean suite.

## Improvements and tool chains

1. **Use the supplied Windows environment immediately.** Lines 19–22 use Unix drive
   paths and fail twice. Lines 26–34 recover with cmd syntax. Shell/platform metadata
   should be part of the tool contract so exploration starts with valid commands.
2. **Scope memory search.** Line 40 searches the entire wiki for generic words such
   as `result` and `pending`. Search the project and its todos using END_TURN,
   deferred_end_turn, or write_handoff first; widen only if those miss.
3. **Preserve test exit status.** Pytest commands at lines 276, 321, 326, 331 and 474
   pipe into `more` or `findstr`. The full-suite result contains a real failure but
   its tool output has no nonzero-exit marker. A pager/filter can hide pytest's status.
   Invoke pytest directly or use a runner that returns the original status separately
   from formatted output. Text inspection caught this failure; automated gates must too.
4. **Stay within tool schemas.** Line 234 supplies unsupported `question_note` to
   ask_user, causing the line-235 TypeError. Reject unsupported arguments clearly;
   the model should use only advertised keys. The following call recovers correctly.
5. **Read before asserting.** The session later retracts a claim that TUI handoff
   state was not reset (line 502). Reading the on_done body first would avoid this.
6. **Reduce avoidable documentation retries.** Lines 399–410 repair a stale edit
   anchor. Lines 438–465 repeatedly shorten one TODO test reference. Read the current
   block, make one compact edit, then validate all changed lines once.

Candidate chains, preserving decision boundaries:

| Chain | Safe execution boundary |
| --- | --- |
| Git state + targeted memory grep + dispatch/caller reads | Batch independent reads; return for diagnosis. |
| Known callback bodies + focused test fixtures | Batch once file locations are known; inspect before writing. |
| Approved edits to separate code/test files | Apply all known edits; then run focused tests with an explicit status. |
| Green focused tests + broader related tests | Continue only after the focused command succeeds; stop on failure. |
| Cleanup + final diff/line-length checks | Run after accepted tests; return for review before any commit. |
| Known documentation edits + changed-file validation | Batch independent files; inspect actual diff and validation results. |

Do not combine inspection and an edit whose content depends on that inspection in
one fixed chain. Do not append commits to a test chain unless approval is already
recorded and every gate checks real command status. A failing test or reviewer
finding must return control for a decision.

The session already batches some independent reads well. Its 82 single-tool steps
show additional opportunities, but batching every step would be incorrect: user
answers, red/green transitions, and reviewer escalation are real decision boundaries.
No speedup or cost-saving percentage is claimed. Logged usage totals include repeated
context across requests; cost fields are null.

## Limits

This review reran focused tests and offline probes, not the full suite or live provider
requests. The full-suite and PySide totals above are session evidence, not new runs.
The production guarantee remains scoped to normally completed batches; existing
exception/crash recovery paths are separate from this fix.
