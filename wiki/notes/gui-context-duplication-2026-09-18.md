# GUI Context Duplication — 2026-09-18

## Observed symptom

On another machine, a user reported that context jumped to approximately 1.2 million on the next
GUI prompt after a successful edit and `write_handoff`. The provider limit was reported as 1m.
No logs are available, so exact incident attribution is unconfirmed. The sidebar showed 300% total
and 200% tools; those percentages are based on request-message estimates using characters divided
by four and are not exact provider token counts.

## Confirmed code cause

`pyside_gui/_dispatch.py` supplied both `previous._messages` and `previous.log` to a new
`AgentLoop` for each prompt. The `agent/loop.py` constructor unconditionally seeded
`initial_messages` into a supplied log, duplicating the complete existing conversation, including
tool outputs. A regression reproduction grew seven conversation messages to fourteen on the first
rebuild.

## Fix and verification

The constructor now seeds `initial_messages` only when `_session_log` is absent, preserving a
supplied log as the authority. Message-only resume still seeds and refreshes its header.
`tests/test_session_log_shadow.py::TestResumeSeeding::test_gui_continuation_preserves_history_once_after_handoff`
verifies three repeated rebuild/run cycles, unchanged surface nodes during rebuild, exact provider
history, and one new user prompt. Isolated verification of
`tests/test_session_log_shadow.py` and `tests/test_agent_loop.py` passed 79 tests.

Four existing failures were reproduced with the original behavior:
`reload_notice_reaches_the_log`, `large_handoff_result_gets_filtered`,
`deferred_system_messages_land_after_all_tool_results`, and
`pause_during_tool_suppresses_post_tool_thinking`. The last leaves a live thread requiring
interruption.

## Remaining open issue

The duplication fix does not deduplicate already polluted sessions and was not deployed to the
other machine. Context hardening remains open: the compaction trigger runs after a successful
non-handoff tool step using preceding response usage, while handoff short-circuits it; there is no
pre-request size enforcement. Configured `context_window` is a compaction trigger, not a hard
provider cap. Reported configuration was `context_window=200000`, `keep_recent_tokens=20000`,
`max_iterations=20`, and `reserve_tokens=16384`.

[Project wiki](../index.md)
