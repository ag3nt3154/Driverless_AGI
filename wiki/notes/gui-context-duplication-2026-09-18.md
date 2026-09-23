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

## Follow-up audit — 2026-09-18

An offline audit after commit `ce37e29a` checked related context and compaction paths with a
mocked provider. The commit is on `main` and has not been pushed. No implementation changes were
made by the audit, and no real provider API calls were used.

See the [context-overflow audit report](../../docs/context-overflow-audit-2026-09-18.md) for the
reproduction evidence, remedies, acceptance criteria, and verification limits. The report is
documentation only; it records the fixed C0 duplication and six open findings, C1–C6.

The audit confirmed these open findings:

1. **P1 pre-request cap is absent.** `agent/loop.py:615` sends messages before any budget check;
   the trigger at lines 824–833 runs only after a preceding successful non-handoff response, while
   handoff returns at lines 818–821. With `context_window=200000`, `reserve_tokens=16384`, and an
   840,000-character user prompt, the mocked API received the request and compaction calls stayed
   at zero. Character count divided by four is only an estimator, not an exact provider tokenizer.
2. **P1 output filtering fails open on cache errors.** `tools/output_filter.py:78-81` returns the
   full result after a cache `OSError`; bookkeeping warns only when the result identity changes.
   An injected disk-full `OSError` allowed a 4,800,000-character result into the second mocked
   provider request, with `warnings=[]`; the character estimator reported 1,200,000. This confirms
   a fail-open safety bug, not an actual remote disk incident.
3. **P1 GUI manual compaction command is broken.** `pyside_gui/app.py:360` assigns
   `loop.log.next_turn` without calling it, and line 361 appends outside the `try` block. The exact
   reproduction raises `InvariantError` because the event data contains a non-JSON-serialisable
   method; compaction does not begin. This present code path supersedes the prior generic R12
   idle-turn issue; broader concurrency questions remain separate.
4. **P2 usage is stale or missing after handoff.** `_last_prompt_tokens` starts at zero and is
   updated only after the handoff return path. A mocked fresh response reporting 210,000 prompt
   tokens left stored usage at zero; `compact(force=True)` returned `did_compact=False`. The
   force argument is unused for bypassing the zero-usage no-op in `_compaction.py`; the tail
   boundary retains everything when `prompt_tokens <= 0`.
5. **P2 step-zero history can silently abort compaction.** `_compaction.py:159` returns without
   compacting when `STEP_END` is absent. Resumed history plus one handoff produced steps
   `[(0,0),(1,0),(1,1)]`; even with last tokens explicitly set to 190,000, `keep_recent=20000`
   selected the last summarized `(1,0)` user-message pseudo-step, with no `STEP_END`, so
   `compact(force=True)` stayed false and summarizer calls stayed at zero. This affects early
   boundary decisions; later real steps can still become eligible. Seed history is also all
   `(0,0)` with no `STEP_END`.
6. **P2 tail token budget is estimated by step average.** `tools/compact/_tail_boundary.py:82-85`
   divides total tokens by step count. In a synthetic 100-step history with 90 steps of 100 tokens
   and 10 steps of 10,000 tokens (109,000 total), `keep_recent_tokens=20000` retained 18 steps
   totaling 100,800 tokens. This illustrates uneven-step over-retention and is not an exact live
   tokenizer measurement.

The audit also reviewed GUI restore: it loads `last session_end` raw messages from
`agent/history.py:89-98`, not the full tool audit records, and found no additional duplication
there. Inherited subagent prefixes remain unguarded through the common loop; no separate duplicate
bug was claimed. Priorities are preflight protection, fail-closed output filtering, and working
recovery compaction before tail tuning.

## BookWriter compaction report and implemented scope — 2026-09-23

A user reported repeated compaction in the BookWriter GUI with a zero summary and unchanged
context. The supplied matching log at `C:/Users/alexr/BookWriter/.dagi/handoffs/compact_fa0521d0.output.log`
shows the worker failing in `tools/subagent_main.py` during `run_forked_compact_mode` while
resolving `deepseek-flash`: the catalog identifier is `deepseek-v4-flash-deepseek`, so
`resolve_model_config` raises `KeyError`. This confirms the cause for matching failure logs;
it does not establish that every unchanged-context report has the same cause.

At the time of the report, the compaction worker did not reuse the existing
`_build_inherited_config` model and endpoint resolver. In `agent/_compaction.py`, a failed worker
was silently represented as `_NO_COMPACTION`, allowing the pre-request guard to continue after
unsuccessful compaction. No UI-only fix was indicated by this report.

The user approved implementation on the current `main` branch, without commit or push. The fix
is implemented and remains uncommitted on `main`. `tools/subagent_main.py` now calls the existing
`_build_inherited_config(req, project)` in `run_forked_compact_mode`, so the API model and provider
endpoint resolve through the local catalog and credentials instead of treating the API model as a
catalog identifier. `agent/_compaction.py` now emits a visible warning containing the worker
message/status and output-log path when the handoff fails or is empty; the original conversation
is preserved and the existing nonfatal continuation policy is unchanged. This is a warning and
history-preservation fix, not a new hard context cap.

`tests/test_compact_integration.py` adds a real config-lookup to compaction-worker flow with a
mocked provider response, summary injection into the next request, reduced conversation-token
estimate, and failed/empty-handoff warning/history-preservation cases. All three new cases failed
before the fix. Existing `tests/test_subagent_main.py` fixtures now use an actual `AgentConfig` to
satisfy the resolver contract. Verification passed: 79 tests across
`test_compact_integration.py`, `test_compact_subagent.py`, `test_subagent_main.py`,
`test_compaction_extract.py`, and `test_tail_boundary.py`, using the dagi environment with
`--noconftest -p no:pytest-qt -p no:cacheprovider` and a dedicated workspace basetemp after an
initial default-temp sandbox `PermissionError`.

Read-only resolution against the actual BookWriter configuration confirmed that API model
`deepseek-flash` resolves to catalog `deepseek-v4-flash-deepseek` with matching endpoint and
credentials. No live model call or GUI restart was performed, so live GUI behavior remains
unverified. The existing session had no context/compaction event, so summary injection was not
observed there and the original raw history was not modified. These results do not change the
separate C1–C6 audit claims above; they record the later targeted implementation and tests.

### Explicit compaction policy approval and verified completion — 2026-09-23

The user explicitly approved the following follow-on behavior. It is implemented on the current
`main` branch and remains uncommitted:

- Context compaction always resolves the configured project `default_model` through the normal
  project-override path, rather than inheriting the active or explicitly selected parent model.
  The compaction request uses that model's default endpoint, credentials, and options as well.
- When compaction errors, the active model context removes exactly the chunk selected for
  summarization. The recent tail and append-only raw log remain; a small omission marker tells
  the model that history was removed without a summary.
- Before either a successful summary replacement or a fallback replacement, validation checks
  the unchanged surface generation and the exact original selected span. Stale context is not
  deleted. Once a selection exists, worker-preparation or invocation exceptions, non-OK or
  timeout results, and empty summaries each trigger the fallback once. The existing no-candidate
  no-op remains.

The implementation now resolves `default_model` through
`resolve_model_config(project_path=project)` without passing the parent model, then constructs
the compaction client and request options from that project default, including client script,
request kwargs, thinking, cache, and provider routing. Selected history and tool schemas remain
available to the worker. The compact preset's model tier now defaults appropriately. In
`agent/_compaction.py`, selection, worker preparation, outcome handling, and replacement are
separate stages. After a valid completed prefix is selected, preparation or invocation
exceptions, non-OK or timeout results, and empty summaries remove exactly the frozen source node
span using the existing `CONTEXT_COMPACTION` replacement, with a short `CONTEXT REMOVED` notice
when no summary is available. The recent tail and append-only raw log remain preserved; fallback
metadata and the reason are saved, and a warning plus the normal context-update callback are
emitted. A stale generation or changed selected span is rejected. `summarize_all` recovery is
covered too. With no candidate, compaction remains a no-op.

All seven initial policy cases failed against the previous behavior. Final verification passed
158 targeted tests across `test_compact_integration.py`, `test_compact_subagent.py`,
`test_subagent_main.py`, `test_compaction_extract.py`, `test_tail_boundary.py`,
`test_context_spec.py`, `test_session_surface.py`, and `test_session_log_shadow.py`, using the
dagi environment with `--noconftest -p no:pytest-qt -p no:cacheprovider` and a dedicated
workspace basetemp. The regression covers project-default routing differing from an explicit
parent model/provider, default thinking and options, summary injection and context reduction,
normal and `summarize_all` error/empty/timeout/exception/preparation fallback, exact tail and
raw-event preservation, replay of the same surface, and stale-selection rejection. `git diff
--check` passed.

No live API call, GUI verification, or restart was performed, so live GUI behavior remains
unverified. The earlier model-alias fix and the historical full-context-retained-on-error policy
are superseded for compaction; other inherited workers are unchanged.

This approval supersedes the same-day inherited-model and failure-preserves-full-active-context
policy choices. The earlier BookWriter worker-resolution fix and its verification remain
historical implementation context; they are not treated as a conflicting account.

[Project wiki](../index.md)
