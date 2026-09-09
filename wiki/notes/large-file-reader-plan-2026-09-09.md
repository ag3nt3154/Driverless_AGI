# Plan: large-file-reader-redesign

Status: PLAN ONLY, reviewed with amendments; no implementation approval or
implementation work.
Prepared 2026-09-09 against the saved, dirty `main` checkout.
Reviewed 2026-09-09; six amendments (A1–A6) integrated into body.

## Objective and acceptance

Replace line-count auto-delegation with a deterministic, size-aware large-result
reader. An oversized actual read result launches exactly one normal reader
subprocess. That reader visits every selected source span in order, produces a
new summary for each chunk, and lets code append it once to a canonical digest.
Query relevance changes emphasis, never coverage. The complete returned result,
including source references and handoff/signpost wrappers, must satisfy the
parent's actual output-filter estimator strictly below its threshold. The reader
retains its accumulated conversation and refuses unsupported context sizes; it
never silently compacts away source or claims success on partial coverage.

Acceptance requires deterministic coverage, budget and event tests below, plus a
real GUI smoke check. No tests were implemented or run for this plan. Chonkie was
not installed.

## Scope and decisions

User-selected: Chonkie RecursiveChunker (preferred) with pure-Python stdlib
fallback (A1); hierarchical structural splitting; explicit size estimation and
source offsets; one sequential reader; append-only section summaries; full
requested-source coverage; one accumulated conversation; same-reader final
condensation; two distinct budgets derived from `.dagi/config.yaml`; existing GUI
lifecycle.

Excluded: embedding/LLM boundary selection, parallel readers, persistent
section-digest store, retrieval index, two-component summary, cross-invocation
cache, production edits now. Temporary source/job transport is necessary for a
subprocess and is not a digest store. Existing document conversion cache remains
the converter's responsibility.

Recommended range decision: preserve `read`'s documented first-2000-lines
default, but remove the surprising default-only full-file promotion. Select the
requested range first and summarize all of that selection when large. A
20,000-line file with a small selected window stays inline. Explicit full-file
reading belongs in structured `read_large_text`. This is a visible change from
the old automatic whole-file delegation and needs approval with the plan. Omitted
and explicitly supplied default values remain equivalent.

**Behavior change — converted documents (A3):** converted documents (PDF, DOCX,
XLSX, PPTX) were previously excluded from delegation regardless of size. Under
the new size-based trigger, converted output that exceeds the parent threshold is
eligible for reader delegation. The `load_selection` path handles this via the
existing `convert_document` + `cache_path_for` pipeline; conversion happens once,
and the reader operates on the cached Markdown. Test converted-document
delegation explicitly in subtask 2.

## Subtask sequencing contract (A2)

Subtasks 1–2 are independently shippable and testable without Chonkie or the
stdlib fallback chunker. Subtask 3 requires Chonkie verification or fallback
chunker. Subtasks 4–5 require subtask 3. Subtask 6 is documentation only. Each
subtask is a separate commit on a feature branch; any prefix of the sequence is a
valid stopping point.

Dependency graph:
```
Subtask 1 (config/estimator) ─┐
                               ├─► Subtask 3 (chunking) ─► Subtask 4 (controller)
Subtask 2 (selection/trigger) ─┘                           ─► Subtask 5 (integration)
                                                              ─► Subtask 6 (docs)
```

## Workspace and evidence

`git status --short` showed unrelated modifications to agent/_loop_helpers.py,
loop.py, registry.py, session.py, skills.py, main.py, pyside_gui/bridge.py,
overlays.py, tests/test_session_tracker.py, tests/test_subagent_main.py,
tools/subagent_main.py, plus deleted .dagi/tmp_repro_drift.py and
agent/_plan_mode.py. Preserve all of them. Stay on main for planning; branch
creation, switching, commits and pushes require separate authorization.
Implementation must reread the affected dirty files and apply only reviewable
local hunks.

Prior wiki lookup is reused: historical read_large_text rebuild (2026-08-15),
hash-anchor revert (2026-07-27), generic registry architecture; no current
detailed reader contract.

Observed current paths:

- `tools/read/_read.py`: `ReadTool.run` validates path, decodes UTF-8 or
  converts documents, optionally selects PDF pages, splits lines and numbers the
  selected lines. Only default offset=1/limit=2000, non-document, >2000-line
  reads with config delegate. Huge single lines, explicit ranges, and converted
  documents bypass this trigger.
- `_delegate_to_read_large_text` sends a file path, not the actual selected
  source. It calls public `tools.subagent_api.run_subagent`, then formats the
  handoff again.
- `.dagi/subagents/read-large-text`: a thin wrapper and prompt asking for
  2000-line reads. No enforced coverage, accumulation, or budget accounting
  exists there.
- `agent/tools.py` configures the parent ReadTool. `agent/subagent_tools.py`
  creates child ReadTool without config, incidentally preventing automatic nested
  readers.
- `agent/_tool_dispatch.py:bookkeep_tool_call` filters the final dispatch output
  with `loop.config.reserve_tokens`. `tools/output_filter.py` serializes strings
  directly, lists as `__list__:` plus JSON, estimates `len(serialized)//4`,
  filters at >= reserve. Nonpositive reserve disables filtering; cache failure
  returns the original output.
- `tools/_handoff_format.py:format_handoff_result` includes the actual handoff
  path and content header; unverified results add a banner. Its wrapper cannot be
  omitted from budget calculations. `SubagentResult.is_ok` currently includes
  `ok_unverified`.
- Pipe callbacks -> runner event forwarding -> bridge factory -> app signal
  connection -> `ConversationView.append_subagent_event` -> JS
  `appendSubagentEvent`. Existing event types include start, status, message,
  tool_call, tool_result, error, done. No live GUI check yet.

## Effective configuration: one source of truth

Existing YAML fields: top-level `context_window`, `reserve_tokens`,
`keep_recent_tokens`, `default_model`, optional `worker_model`/`advanced_model`;
model catalog entries may override the three token fields. `max_continuations`,
`null_response_retries`, `api_error_retries` are existing top-level controls. Do
not mistake YAML `max_iterations: 20` for an available reader limit: it is not
loaded into AgentConfig by the inspected resolver.

`agent/config_loader.py:resolve_model_config` merges project YAML over root
YAML, resolves the selected entry through `_build_config_from_entry`, and builds
optional worker/advanced configs. Token fields currently use
`entry.get(field) or raw.get(field, default)`; explicit per-model zero therefore
falls back. Fix that only for the token fields this work consumes, using
missing/None rather than truthiness; test it as an intentional config semantic
fix.

Fresh pipe child: `run_subagent_pipe_mode` resolves config, applies
`_apply_worker_config` (or advanced), then uses the flattened
context_window/reserve_tokens/keep_recent_tokens. Missing or unknown
worker_model currently falls back to default; retain that behavior and include
the resolved model ID in reader diagnostics.

Parent-context child: `run_subagent` writes a version-2 fork and
`subagent_main.main` routes to `run_forked_subagent_mode` BEFORE normal
model-tier handling. `_build_inherited_config` resolves the inherited
provider/model; the exact parent prefix and schemas are retained. The
read-large-text preset's `model_tier: worker` does not force a worker model on
this path. Recommended compatibility choice: retain both paths and use the ACTUAL
child config and entire inherited prefix. Do not silently switch models or
discard that prefix. If the user wants all readers on worker_model, that is a
separate explicit behavior decision requiring a fresh-context launch contract.
The implementation must not label an inherited reader as the worker model when it
is using the parent model.

Observed YAML top-level values are context_window=200000, reserve_tokens=16384,
keep_recent_tokens=20000; worker_model is commented out. These are observations,
not constants to copy. `dagi` is Python 3.14.4; project metadata requires
Python >=3.11.

There is no normal YAML-loaded max_tokens/max_completion_tokens field. Normal
provider requests spread `AgentConfig.request_kwargs`; client scripts can supply
an output cap. Reserve is headroom, not a verified provider maximum. Proposed
minimal addition: `max_output_tokens: int | None = None` on AgentConfig, loaded
from the same top-level / model catalog precedence, copied by worker/advanced
flattening and inherited resolution. Omission derives the reader output
reservation from its effective reserve_tokens. A supplied value and any actual
client-script output limit can only tighten that reservation. This is one
optional model capacity field, not a second reader-budget section. Document that
configured context and output capacity are operator declarations, not provider
metadata verification. An unknown provider cap may cause an explicit provider
rejection; never claim universal fit.

## Budgets and ownership

Parent owns immutable invocation snapshot P (its effective reserve_tokens),
selected source, and return-format metadata. Child resolves its effective
C=context_window and R=reserve_tokens after choosing the execution path. Child
owns chunks, cursor, accumulated messages, canonical digest, allocations, and
repair counts. Never use R as the parent's threshold or P as C.
Parent checks P again at return; a concurrent effective-parent budget change
yields a stale budget error, not an unchecked digest. Never transfer credentials
in the read-job manifest.

Parent estimator F(x) is the extracted, shared output-filter estimator, unchanged
semantically. Success requires P>0 and F(complete_rendered_return)<P. For the
current string estimator, the largest allowed complete string is `4*P-1`
characters; references and wrappers consume that same capacity. Use F for the
final decision rather than subtracting independently floored token estimates.
Pre-render the actual immutable wrapper using the real handoff path. Nonpositive
P: preserve inline passthrough with auto-delegation disabled; explicit large
digest requests fail with an actionable positive-reserve requirement. No invented
fallback threshold. Tiny positive P that cannot hold even the wrapper fails
before provider calls. Errors are explicit, possibly filtered by normal parent
behavior; never mislabel them success.

Reader estimator E is deliberately distinct from F. Recommended no-download
conservative fallback: UTF-8 byte count of canonical JSON request
(ensure_ascii=False), including model messages, tools, query, references and
transport fields. This is an explicit estimator, not a mathematically universal
tokenizer bound. Add margin M=ceil(R/8), derived from the existing reserve; do
not add an independent fixed-token margin. Record estimator identity. Use
observed provider prompt usage to raise, never lower, E for later requests when
needed. Unknown/underestimated tokenization results in explicit
unsupported-context failure.

Per request require E(request)+O+M<=C, where O=min(R, configured
max_output_tokens if set, actual client-script cap if set). Validate positive
C/R/O and R<C. Enforce an API completion cap using O (or a smaller section
allocation); include hidden reasoning in reservation and fail if no usable
summary emerges. Normalize supported max_tokens/max_completion_tokens arguments
without sending conflicting fields; provider incompatibility fails clearly.
`keep_recent_tokens` must NOT become a hidden chunk budget or allow history
eviction.

Derive initial raw chunk target K=min(R, C-O-M-E(base_request)); K must be
positive. Recount each decorated chunk/request because raw source alone excludes
references/instructions. Plan chunks, then preflight the ENTIRE accumulated
conversation: base prefix, all selected source chunks and per-turn envelopes, a
conservative upper bound on all summaries, possible repair/condensation messages,
final tool arguments/results and O+M. A smaller chunk does not solve total
accumulation overflow. Fail before reading when the full plan cannot fit; return
estimated required/available capacity and recommend a narrower request or
configured larger model. Check again before EVERY call; unexpected response
overhead may still exhaust it. No automatic compaction, eviction, repeated full
digest injection or nested compact agent.

Canonical digest uses a header with selected-source scope and compact per-chunk
references. Compute a minimum skeleton covering every chunk; if it cannot fit P
or reader output capacity, fail. Allocate remaining prose capacity
proportionally to E(chunk), deterministic remainder to earlier chunks. Reserve
minimum references for all unread chunks before each allocation. Carry unused
capacity forward; charge actual rendered characters against the parent space and
actual E(messages) against reader space. Section allocation is also capped by O
and available context. These are derived values, never extra YAML budgets.

After all chunks, render and check the complete return with F. If oversized, keep
the SAME subprocess, conversation and coverage ledger; ask it to condense the
existing digest into a smaller complete digest. Do not append another copy of the
entire old digest as a new user message: it already exists in accumulated section
messages. Condensation may replace the final presentation, never the coverage
ledger. Every covered chunk ID must remain represented (coalesced adjacent
references permitted). Bound semantic repair/condensation attempts together by
effective `max_continuations`; each failed condensation must strictly reduce
serialized size or fail immediately. Note: condensation is an LLM operation —
the model may fail to compress further on the first attempt. An equal-length
condensation counts as no-progress and fails immediately; this is an expected
outcome, not a bug. Zero means no repair attempts. Context failure stops
immediately. Transport retries use existing api_error_retries/null_response_retries
and do not append duplicate source or committed sections.

## Exact flow and proposed function inventory

All new names below are PROPOSED. Existing names are called out. Dataclasses use
keyword-only construction, functions <=100 lines, <=5 positional parameters,
complexity <=8; modules <=500 lines. Split new helpers by ownership below rather
than growing dirty loop.py/subagent_main.py.

### A. `tools/read/_selection.py` (new, needed for source fidelity)

- `SourceSpan(*, start: int, end: int, source_start: int, line_start: int,
  page: int | None)`: half-open Python character offsets; maps selected text back
  to normalized original text or converter Markdown. Offsets are NOT raw PDF byte
  offsets or original DOCX/XLSX coordinates.
- `ReadSelection(*, path: Path, text: str, spans: tuple[SourceSpan, ...],
  header: str | None, editable_path: Path | None, scope: str)`: immutable
  snapshot of exactly the request.
- `load_selection(path: Path, *, offset: int, limit: int | None,
  pages: str | None, options: ReadOptions) -> ReadSelection`: caller
  ReadTool/direct reader; validates using existing validate_path,
  convert_document and cache_path_for. Retain source with line endings before
  selection, map PDF pages before line slicing; limit=None is internal full
  selection.
- `select_source(text: str, *, offset: int, limit: int | None,
  pages: set[int] | None) -> tuple[str, tuple[SourceSpan, ...]]`: source-order
  page selection, then offset/limit. Preserve line-ending/text bytes after
  existing UTF-8 newline normalization. Explicit negative limit and offset<1
  become clear validation errors (document compatibility change); empty selection
  is inline, not a delegated success.
- `render_inline(selection: ReadSelection) -> str`: reproduces small-result cat-n
  formatting and document headers. Selected-PDF numbering can retain current
  filtered numbering for inline compatibility; digest references explicitly
  include original converted line and PDF page.
- `references_for(selection: ReadSelection, start: int,
  end: int) -> tuple[SourceSpan, ...]`: handles spans across noncontiguous
  selected pages; never fabricates a contiguous source range.
- `ReadOptions` contains cwd/allowed_roots/project_path/service_url only, no
  parallel budget.

### B. `tools/output_filter.py` and `tools/read/_budgets.py` (new)

- Existing `_serialise(result)` remains canonical. NEW
  `estimate_tool_output(result: str | list) -> int` uses `_serialise` and
  existing //4 rule; `filter_tool_output` delegates to it, otherwise unchanged.
- `ReaderLimits(*, parent_reserve: int, context_window: int,
  output_reserve: int, estimator_margin: int, max_repairs: int)` stores derived
  immutable numbers.
- `resolve_reader_limits(parent_reserve: int, config: AgentConfig, *,
  request_kwargs: dict) -> ReaderLimits`: child startup; validates and tightens
  actual limits.
- `estimate_reader_request(request: dict) -> int`: explicit E above; shared
  chunk/preflight accounting.
  `estimate_reader_text(text: str) -> int` supplies Chonkie's count function.
- `require_context_fit(request: dict, limits: ReaderLimits) -> None`: before each
  API call.
- `preflight_reader(base_request: dict, chunks: tuple[ReaderChunk, ...], *,
  limits: ReaderLimits,
  return_format: ReaderReturnFormat) -> SummaryAllocation`: computes
  complete-history upper bound and parent skeleton capacity; fails before partial
  work. On failure, raises `ReaderCapacityError` (A5).
- `allocate_sections(chunks: tuple[ReaderChunk, ...], *, available_chars: int,
  minimum_refs: tuple[str, ...]) -> tuple[int, ...]`: deterministic proportional
  allocation.
- `require_parent_fit(text: str, parent_reserve: int) -> None`: calls actual
  shared F; neither truncates nor delegates. Caller finalizer and parent return
  boundary.
- `ReaderCapacityError(*, required_tokens: int, available_tokens: int,
  recommendation: str)` (A5): structured exception for preflight failures.
  `recommendation` is one of: `"narrow the selected range"`, `"configure a
  larger context_window model"`, or `"reduce the number of selected pages"`.
  The parent formats this into the tool output verbatim. Error message must
  contain all three fields (required, available, recommendation) and the
  recommendation must match the failure mode.

### C. `tools/read/_chunking.py` (new)

- `ReaderChunk(*, index: int, start: int, end: int, text: str,
  references: tuple[SourceSpan, ...], estimated_tokens: int)` is immutable.
- `structural_spans(text: str) -> tuple[tuple[int, int], ...]`: deterministic
  scan for Markdown headings, blank paragraphs, fenced code and contiguous table
  rows. Preserve whole code/table blocks when they fit. For plain code use
  blank/function-like line boundaries as preferences, not a claim of
  language-complete AST parsing. No new parser dependency.
- `build_recursive_chunker(chunk_tokens: int) -> RecursiveChunker`: explicit
  count callable, explicit rules, delimiter retention and
  min_characters_per_chunk=1. Do not rely on defaults. On `ImportError`, fall
  back to `stdlib_chunk_selection` (A1).
- `chunk_selection(selection: ReadSelection, *,
  chunk_tokens: int) -> tuple[ReaderChunk, ...]`: Chonkie recursively divides
  structural spans; translate local offsets into selection offsets. On Chonkie
  `ImportError`, delegates to `stdlib_chunk_selection` with a logged warning.
- `stdlib_chunk_selection(selection: ReadSelection, *,
  chunk_chars: int) -> tuple[ReaderChunk, ...]` (A1): pure-Python fallback
  chunker. Uses the same `structural_spans` scan, then recursively splits on
  `\n\n` -> `\n` -> sentence boundaries (`. `, `? `, `! `) -> whitespace ->
  fixed codepoint slices. Uses character-count estimation (len//4) instead of
  token-count. Same `ReaderChunk` output contract; same `validate_chunks` checks.
  ~80 lines, no external dependencies. This eliminates Chonkie as a hard blocker.
- `split_oversized_span(text: str, *, start: int, chunk_tokens: int)
  -> tuple[tuple[int, int], ...]`: deterministic code-point slicing with
  byte-estimate bounds for huge single tokens/lines/cells. Prefer sentence,
  newline/row, whitespace, then smaller spans. Never split encoded bytes or
  silently strip delimiters. If one code point cannot fit, fail rather than loop.
  Mark continued code/table blocks in metadata outside source text.
- `validate_chunks(selection: ReadSelection,
  chunks: tuple[ReaderChunk, ...], *,
  chunk_tokens: int) -> None`: assert contiguous selection offsets, first=0,
  last=len(text), no gaps/overlaps, exact slice equality, concatenation equality,
  ordered references, recount every chunk. Chonkie text/offset discrepancy fails
  loudly; no fuzzy text search repair.

### D. `tools/read/_reader_job.py` (new parent/child transport)

- `ReaderJob(*, version: int, selection: ReadSelection, query: str,
  parent_reserve: int, return_format: ReaderReturnFormat)`: invocation input, no
  API keys, no mutable running summary.
- `ReaderReturnFormat(*, signpost: str, handoff_path: Path)`: exact successful
  wrapper metadata.
- `write_reader_job(job: ReaderJob, directory: Path) -> Path` and
  `load_reader_job(path: Path) -> ReaderJob`: versioned temporary source
  snapshot; validate schema, offsets, project scope and source digest; do not
  reread a changed source file.
- `render_reader_return(content: str, fmt: ReaderReturnFormat) -> str`: one pure
  renderer used by child budget validation and parent return. Extract a pure
  `format_handoff_content(content: str, handoff_path: str, *,
  unverified: bool=False) -> str` in existing `_handoff_format.py`; existing
  format_handoff_result reads then calls it.
- `delegate_selection(selection: ReadSelection, *, query: str,
  context: ReaderLaunchContext) -> str`: one public run_subagent call, normal
  callback factory and parent_context; parent independently validates verified
  handoff and complete return, preserves detailed failure diagnostics.
  `ReaderLaunchContext` groups config/callbacks/log/parent_context.

### E. Existing entry points and integration seams

- `ReadTool.run(self, path: str, offset: int=1, limit: int=2000,
  pages: str | None=None, query: str | None=None) -> str | list`: signature
  unchanged; load selection -> render inline -> estimate actual result ->
  delegate if config and P>0 and F(result)>=P. No line-count branch.
  Config=None retains plain child/local inline behavior. Update
  descriptions/schema help; do not silently reread source in delegation.
- Replace `_delegate_to_read_large_text(self, path, total_lines, query)` with
  `_delegate_to_read_large_text(self, selection: ReadSelection,
  query: str | None) -> str`, thin call into delegate_selection. Existing helpers
  _parse_page_spec/_select_pages can be retained as compatibility wrappers around
  selection helpers where tests/imports require them.
- **Rollback flag (A4):** Add `use_legacy_reader: bool = False` to `AgentConfig`,
  loaded from YAML. When true, `ReadTool.run` uses the old line-count trigger
  and the existing `read-large-text` preset via the original delegation path.
  The old preset stays in `.dagi/subagents/read-large-text/` and is not removed.
  Remove this flag after one release cycle. This is one boolean, one `if` branch,
  zero architectural impact.
- `ReadLargeTextTool.run(self, task: str='', custom_instructions: str='', *,
  path: str | None=None, offset: int=1, limit: int | None=None,
  pages: str | None=None, query: str | None=None) -> str`: add structured
  schema, full-source default for explicit reader. `path` is preferred; existing
  task containing only a valid path can map exactly. Ambiguous prose task returns
  an actionable structured-path error, never guesses which source to read.
  Preserve custom_instructions as query guidance. This is an explicit legacy-call
  compatibility limitation; do not retain an unenforced bypass.
- `tools.subagent_api.run_subagent(..., *,
  reader_job: ReaderJob | None=None)` gains optional keyword (all existing
  arguments retained): after allocating actual handoff_path, fill exact return
  format, write job, pass `--reader-job`, clean job on terminal exit; reject job
  on other presets. Existing parent-context lineage/stale-generation validation
  remains.
- `tools/subagent_main.py:main()` adds --reader-job and routes read jobs after
  validating type, fork version and paths. **Routing constraint (A6):** the
  `--reader-job` dispatch in `main()` must be <=5 lines: parse the job path,
  validate it exists, call `run_reader_job_mode(args)`. The
  `run_reader_job_mode` function lives in `tools/read/_reader_controller.py`,
  not in `subagent_main.py`. This file is already at 724 lines and must not grow
  by more than 10 lines net.
- `tools/_subagent_runner.py`: add read-job ownership to `_SubagentState` and
  terminal cleanup. Preserve existing spawn, stdout tee, timeout/resume and
  force-kill behavior. On timeout the live process owns its job until actual
  terminal exit; parent must not delete it prematurely.
- `agent/config_loader.py:_build_config_from_entry`, `AgentConfig`,
  worker/advanced config flatteners carry max_output_tokens. Existing parent
  filter always uses live loop.config. No default YAML budget edits; add
  explanatory YAML comments and optional field documentation.
- `agent/tools.py`, `agent/subagent_tools.py`: retain existing ReadTool
  registration and the nondelegating child invariant. Controller never exposes
  automatic read recursion.
- Preset prompt/config: describe sections-only response, untrusted source,
  all-chunk scope, code-owned append/coverage/budgets, final tool handoff;
  remove 2000-line policy. Keep normal preset identity and worker tier. No budget
  numbers in preset YAML or prompt.

### F. `tools/read/_reader_controller.py` and `_reader_provider.py` (new)

Dedicated deterministic reader controller INSIDE the normal subprocess, rather
than putting unbounded orchestration into a prompt or modifying AgentLoop's
general compaction behavior. Normal subagent API, events, client configuration,
handoff and cancellation remain integrated. The controller owns its accumulated
conversation; other agents retain their normal loop.

- `ReaderState(*, messages: list[dict], chunks: tuple[ReaderChunk, ...],
  cursor: int, digest: str, remaining_chars: int, repairs: int,
  covered: list[int])`: only mutable owner. Coverage is assigned by code after
  accepted model output, never trusted from model claims.
- `ReaderController.__init__(self, *, job: ReaderJob, config: AgentConfig,
  runtime: ReaderRuntime)`: runtime groups client, initial prefix/schemas,
  callbacks, cancellation check, handoff tool, resolved provider request options.
- `run(self) -> None`: derive limits/chunks, preflight, process each chunk,
  finalize, write handoff as final action; emit error and nonzero exit on
  failure. Never emits success early.
- `_read_next(self) -> None`: add exactly next decorated source chunk once, call
  provider with tool use disabled for section turns, require one nonempty
  complete section response, then commit. Query stays in base instructions;
  irrelevant chunks still get concise coverage.
- `_append_section(self, chunk_index: int, summary: str) -> None`: require
  index==cursor, attach code-owned refs, update digest and both counters
  atomically, then advance cursor. Reject duplicate/out-of-order commits.
  Summary must not be a repeated full running digest; prompt enforces section
  scope, code rejects structured wrong-index responses and retries within shared
  repair allowance. Cannot prove semantic completeness purely by code.
- `_finalize(self) -> str`: requires cursor==len(chunks), verifies refs and
  parent-rendered size; requests bounded condensation in same messages if needed.
  No second worker.
- `_condense(self, target_chars: int) -> str`: retains ordered coverage
  references, checks strict size progress; output is final digest candidate, not
  another appended section.
- `_write_handoff(self, content: str) -> None`: dispatch existing
  WriteHandoffTool.run with validated content, check END_TURN, emit normal
  tool_call/tool_result and final done once. This is a code-controlled tool
  invocation; the LLM does not get to end reading early. No handoff exists on
  incomplete coverage; writing failure is error, never scraped success.
- `ReaderRuntime` is a dataclass of the above dependencies; no unrelated registry
  mutations.
- `build_reader_request(state: ReaderState, *, runtime: ReaderRuntime,
  output_tokens: int) -> dict`: includes real tools and transport instructions
  in estimator; inherited prefix remains intact, tool_choice disables tools
  during section calls.
- `call_reader(request: dict, *, runtime: ReaderRuntime,
  limits: ReaderLimits) -> str`: final pre-call fit check, configured output cap,
  existing configured retry counts, cancellation between attempts and stream
  deltas, provider usage calibration. Handle stream and non-stream consistently;
  length-truncated, empty or tool-call responses are rejected before commit.
  Reuse build_openai_client and provider configuration conventions, no second
  credential path.
- `emit_reader_progress(callbacks: AgentCallbacks, *, completed: int,
  total: int, phase: str) -> None`: existing status event shape; source text not
  dumped into status.

Errors: invalid source/pages, missing converter, conversion failure, unsupported
UTF-8, missing/incompatible Chonkie (falls back to stdlib chunker per A1),
bad offsets, impossible budgets, unexpected output/context overflow, cancellation,
provider timeout/retry exhaustion, handoff I/O failure and stale parent
generation are distinct actionable failures. Normal runner timeout remains
resumable; it is not successful completion. Permanent cancellation uses existing
process termination and cleanup, with no surviving reader loop or falsely valid
handoff.

GUI should need no production edits: wire start/status/messages/error/done
through existing callback factory. If failure currently leaves a block visually
open, adapt the existing terminal event handling surgically only after
reproducing it; error must not render as a successful done. Distinguish terminal
closure from success in any added event field.

## Chonkie compatibility strategy

[RecursiveChunker docs](https://docs.chonkie.ai/oss/chunkers/recursive-chunker)
document custom counting, rules, chunk size and source indices. These describe
boundary preferences, not proof of exact source conservation, code parsing or a
hard token cap for every input.
[Current recursive source](https://raw.githubusercontent.com/chonkie-inc/chonkie/main/src/chonkie/chunker/recursive.py)
uses cumulative offsets and a token encode/decode fallback; exhausted rules may
return a large span. Our adapter must validate and safely bound results, not
trust chunk_size alone.

[PyPI](https://pypi.org/project/chonkie/) identifies 1.7.0, Python >=3.10 and a
universal Python wheel. Recommend candidate `chonkie==1.7.0`, conditional on
runtime tests. Main-branch source is not a pinned-release guarantee.
[Project metadata](https://raw.githubusercontent.com/chonkie-inc/chonkie/main/pyproject.toml)
lists numpy, chonkie-core, tokie, tqdm, tenacity and httpx as base dependencies;
native transitive wheels must work on Windows CPython 3.14. No
embeddings/code/all extras needed.

**Stdlib fallback (A1):** if Chonkie 1.7.0 fails to install or its native
transitive dependencies are incompatible with Python 3.14/Windows, the stdlib
fallback chunker (`stdlib_chunk_selection`) provides full functionality using
character-count estimation. Chonkie remains the preferred backend for
token-aware splitting; the fallback uses `len//4` character estimation. Lazy
import keeps small reads working with any environment; oversized reads with
neither Chonkie nor a working stdlib path fail with install guidance.

Before implementation commit: inspect the exact 1.7.0 release artifact, record
hash, confirm RecursiveRules constructor spelling (`levels` versus docs' example
`rules`), RecursiveLevel delimiter inclusion, callable tokenizer behavior and
min-size rules. Keep encode/decode fallback outside Chonkie by ending our rules
before token-level fallback and applying our lossless bounded span splitter.
Test Unicode, literal internal separator characters, CRLF, blank-only input,
repeated delimiters, whitespace and minimum-size merging against that pin. Do not
call online from_recipe or download a tokenizer model. If 1.7.0 fails, the
stdlib fallback is immediately available; report exact Chonkie failure for future
resolution. No silent library substitution/downgrade.

After approval, add tested pin to requirements-core.txt and matching pyproject
dependency because configured core ReadTool uses it. Lazy import keeps small
reads working with an older environment; oversized reads fall back to stdlib
chunker with logged warning per A1. Resolve compatible transitive versions and
record them with the repository's pinning convention; no dependency installation
was done during planning. Native compatibility remains unverified.

## Subtasks and meaningful tests

All subtasks pending. Add tests only for externally meaningful invariants, not
implementation mirrors. Fixture text generated in tmp_path; no production
fixtures or converter dependency.

### Subtask 1 [ ] Config and estimator contract

Files: output_filter.py, config_loader.py, _loop_config.py,
tests/test_output_filter.py, tests/test_config_resolution.py,
tests/test_project_config.py; new test_reader_budgets.py.
Test exact threshold strings of lengths 4P-1, 4P, 4P+3 and list serialization
with Unicode. Pass the real final renderer into real filter_tool_output and
assert success has identical returned text and no hash-cache call. Test long
paths/wrappers consume capacity; P<=0 preserves filter behavior but disables
reader trigger; tiny P rejects before spawn/call. Use temp YAML with parent
P=300, worker C=6000/R=700 and per-model output cap=200; assert those values
reach limits, chunk target, allocations and API kwargs. Change each value
independently and assert behavior changes at its own boundary, not another
model's budget. Cover project override, selected main model, worker fallback,
inherited parent model, explicit zero, missing/None, negative, client-script
tighter cap and conflicting API keys (argument names, not credentials). No secret
values in transported job.

### Subtask 2 [ ] Exact request selection and size trigger

Files: read/_read.py, _selection.py, tests/test_read_tool.py; direct wrapper
tests in tests/test_read_large_text_tool.py. Stub run_subagent; do not run a
provider for these.
Short file inline unchanged; >2000 tiny lines with small default result stays
inline; <2000 giant lines triggers; explicit offset/limit triggers iff rendered
selected result >=P. Default request covers exactly documented first window; full
structured reader covers whole source. Huge omitted portions do not affect
trigger. Query reaches worker once unchanged. Mock converter Markdown for
PDF/docx/xlsx/pptx; conversion once only; headers counted; selected pages in
source order, disjoint pages correctly referenced, offset/limit after pages, no
content outside selection. Cover empty/out-of-range, malformed/reversed/zero
pages, invalid negative range, UTF-8 failure, images, converter error, denied
path and missing config. Assert no worker starts for failure or empty result.
Source mutation after dispatch must not change snapshot/chunk content. Test CRLF
normalization is explicitly documented.

**Converted document delegation (A3):** explicitly test that a converted document
whose rendered output exceeds the parent threshold triggers delegation. This is a
behavior change from the old code which excluded converted documents regardless
of size.

**Rollback flag (A4):** test that `use_legacy_reader=True` in config routes
through the old line-count trigger and existing preset. Test that the old preset
still produces a result (stub provider). This is the rollback verification.

### Subtask 3 [ ] Chonkie adapter and coverage

New tests/test_reader_chunking.py. Run against BOTH the real pinned Chonkie
library AND the stdlib fallback chunker (A1). Parameterize Markdown headings,
normal prose, repeated paragraphs, giant no-space line, CJK/emoji/combining
marks, tabs/blank lines/trailing newline, fenced code containing fake headings,
ordinary code, Markdown table with huge cell, CSV-like rows, and delimiter
separator characters. Assert concatenation exactly equals selected text; offsets
cover [0,len) once, each text equals its slice, estimates satisfy cap, and all
original refs map correctly. A code/table block that fits stays intact; an
oversized one splits safely with continuation refs. Tiny caps that cannot fit one
Unicode code point fail promptly. Inject malformed library chunks with gaps,
overlaps, duplicate text/wrong offsets, changed whitespace and oversize minimum
merges: validation must reject or bounded splitter must repair size without
altering source.

**Stdlib fallback (A1):** all parameterized tests run against both
`chunk_selection` (Chonkie path) and `stdlib_chunk_selection` (fallback path).
Skip Chonkie tests with `pytest.importorskip("chonkie")` when the library is
absent. The stdlib path must pass unconditionally on any Python >=3.11.

### Subtask 4 [ ] Sequential controller and budget exhaustion

New tests/test_reader_controller.py and test_reader_provider.py use a scripted
fake provider that captures full requests and yields known responses/usage/errors.
Verify every source chunk appears once in accumulated history, old summaries
remain without repeated full-digest messages, code append occurs once, index
monotonicity and remaining capacity tracks reality. Place query answer only in
first chunk and sentinel facts in middle/last: all chunks still visited and
references present. This proves traversal, not LLM semantic recall; separately
review a live digest against the source after approval.
Test preflight rejects total accumulation overflow even when each chunk fits.
Assert next call is never sent when inherited prefix/tools/query/previous
summaries/output reservation/margin or usage calibration push it over C. Exact
boundary fits. No compact/spawn calls. Test oversize final candidate condenses
with same provider/session/PID; strict below-P result accepted, equal-to-P
rejected; wrapper-only overflow; dropped refs rejected; no-progress condensation
fails; max_continuations exhausted; zero repairs; context expires during repair.
Section response empty, truncated, wrong-index or duplicated commits never
advance coverage. Transient retry doesn't duplicate source/summary; late provider
failure/cancel leaves no successful handoff. Huge query and too many mandatory
references fail before paid calls.

**Preflight error messages (A5):** test that `ReaderCapacityError` contains
`required_tokens`, `available_tokens`, and `recommendation` fields.
`recommendation` must be `"narrow the selected range"` when chunk count is
reducible, `"configure a larger context_window model"` when the base request
alone exceeds capacity, or `"reduce the number of selected pages"` when page
selection drives the overflow. Parent formats this verbatim into tool output.

### Subtask 5 [ ] Subprocess/handoff and GUI integration

Extend tests/test_subagent_api.py, test_subagent_main.py,
test_subagent_runner.py, test_read_large_text_tool.py,
test_write_handoff_tool.py; add tests/test_reader_integration.py and
tests/test_reader_gui_events.py if no suitable existing GUI harness. Re-read
dirty tests. Verify one launch; actual allocated handoff path budgeted; both
fresh and fork-v2 routes; parent prefix preserved on inherited route, actual
effective model/limits used; config changes during invocation detected; verified
success only. ok_unverified and missing/empty handoff fail reader success.
Nonzero process exit cannot be hidden by a handoff. JSON job
tampering/version/path escape rejected; snapshot cleanup on success/failure/cancel
and retention on resumable timeout. Normal stale-generation guard still applies.
Use callback spies for start -> ordered chunk/condense status -> verified done;
errors/cancel do not emit success. Test bridge signal payload and
ConversationView JS serialization with quotes/Unicode; browser DOM fixture
exercises existing appendSubagentEvent and visible status/error/terminal
behavior. Assert no parallel reader block and exactly one start/end. Pure Python
event tests can run without Qt; Qt signal and rendered DOM tests need real
runtime. GUI smoke: launch normal PySide in activated dagi, read large
text/range/PDF, watch start, progress, digest completion; force provider failure
and cancel; verify visible failed state. Document conversion service required
only for live PDF smoke. No GUI success claims until done.

**Routing constraint (A6):** verify that `subagent_main.py` grows by no more
than 10 lines net. The reader job mode body must live in
`tools/read/_reader_controller.py`. Test the routing dispatch independently.

### Subtask 6 [ ] Documentation and surgical delivery

Update read help, preset, wiki architecture/workflows/errors only with verified
implementation facts. Update AGENTS per explicit repo rule without rewriting
stable behavioral content. Save approved decisions via wiki-add BEFORE
implementation; save actual completion after verification. This draft is not
approval. Do not manufacture green test claims or baseline failures from the
dirty checkout. Report blockers with failing test and source evidence.

## Verification commands (future implementation, not executed here)

Run at C:/Users/alexr/Driverless_AGI. Initial runtime inspection already
confirmed Python 3.14.4 and Chonkie absent; shell network access was denied,
official web sources were used. The following commands require dependency
approval/implementation phase and network access:

```powershell
conda run -n dagi python -m pip install --dry-run --only-binary=:all: "chonkie==1.7.0"
conda run -n dagi python -m pip install -r requirements-core.txt
conda run -n dagi python -m pip check
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_output_filter.py tests/test_config_resolution.py tests/test_project_config.py tests/test_reader_budgets.py -q
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_read_tool.py tests/test_read_large_text_tool.py tests/test_reader_chunking.py -q
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_reader_controller.py tests/test_reader_provider.py tests/test_reader_integration.py -q
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_subagent_api.py tests/test_subagent_main.py tests/test_subagent_runner.py tests/test_write_handoff_tool.py -q
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_reader_gui_events.py -q
```

New test files above do not exist yet. Isolated tests must use local fixtures so
--noconftest does not remove required setup; check existing fixtures before each
run. Plugin name is pytest-qt, not qt. Do not hide required Qt tests behind
blanket skips. For real Qt tests, activate dagi fully (Windows Qt DLL
requirement) and run their dedicated suite with needed pytest-qt fixtures; first
inspect GUI launch command rather than inventing one. Watchdog and existing GUI
file-cap failures must be attributed, not fixed incidentally. Run meaningful
targeted tests once, broaden only for changed shared config/filter/subagent
contracts.

## Review decisions and remaining gates

1. Approve exact-range default semantics and structured direct-reader
   compatibility above.
2. Recommended preserve current inherited-prefix path, with honest model
   diagnostics; forcing worker_model on every read would require a separately
   approved context-inheritance change.
3. Approve optional YAML max_output_tokens capacity field; absent means derive O
   from R, with configured-provider capability unverified. Fix truthiness bug
   only for fields this work touches — no scope-creep into general config fix.
4. Accept conservative UTF-8/request estimation plus reserve-derived margin and
   explicit unsupported-context failure; provider tokenizer identity is not
   universally available. Calibrate empirically in integration tests.
5. Validate Chonkie 1.7.0/transitive native wheels on actual Windows Python 3.14
   before pinning. If validation fails, stdlib fallback chunker (A1) provides
   immediate coverage; Chonkie resolution deferred to a future pin update.
6. Review code-controlled final WriteHandoffTool invocation: retains typed final
   action and normal GUI lifecycle while preventing an LLM from ending the
   reading loop prematurely.

## Amendment summary

| ID | Amendment | Type | Integrated into |
|----|-----------|------|-----------------|
| A1 | Stdlib fallback chunker | Addition | Scope, C inventory, Chonkie strategy, Subtask 3 |
| A2 | Subtask sequencing contract | Addition | New section after Scope |
| A3 | Converted document delegation callout | Clarification | Scope, Subtask 2 |
| A4 | Rollback config flag | Addition | E inventory, Subtask 2 |
| A5 | Structured preflight errors | Tightening | B inventory, Subtask 4 |
| A6 | `subagent_main.py` routing cap | Constraint | E inventory, Subtask 5 |

Plan-only checkpoint: source/config inspection and external API research
complete; artifact written; production code unchanged; implementation, dependency
resolution, tests, GUI smoke, plan approval and approval wiki record remain
pending.
