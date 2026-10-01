# Large file reading — plan (2026-10-01)

**Status: implemented** on branch `feat/large-file-reading`. Deviations from the plan
below: one config field `truncate_edge_chars` instead of separate head/tail fields; the
tool lives in `.dagi/subagents/read-large-file/main.py` (discovered like the other
subagent tools) rather than `tools/read_large_file/`; it does not forward
`parent_context` (the reader never sees the parent conversation); an unparseable chunk
reply is retried once and then kept as raw notes instead of failing the run; excerpts
not found in the source are flagged, not dropped.

Replace automatic delegation in `read` with **middle truncation + an explicit
`read_large_file` tool**, and reuse the same truncation for every oversized tool output.

## Decisions

| Topic | Decision |
|---|---|
| Oversized `read` | Return head + marker + tail; never delegate automatically |
| Size kept | 4000 chars at each end, cut on whole lines |
| Oversized output from other tools (bash etc.) | Same format via `filter_tool_output`; marker points at the saved full output |
| Full read | Agent opts in with `read_large_file(path, query?)` |
| Reader loop | Fixed sequential loop, **not** an agent loop. Context per call is constant: running summary + current chunk |
| Output | Index: sections with line ranges + verbatim excerpts |
| No query | General digest |
| Cache | Yes, keyed on content + query + model + reader version |
| Order | Sequential |
| Out of scope (later) | Moving `grep`/`find`/`web_fetch`/`read_notepad` self-caps onto the shared filter; pruning saved tool outputs |

## Target flow

```
read(path) ──► rendered output < reserve_tokens? ──yes──► full numbered text
                          │no
                          ▼
              head 4000 chars + marker + tail 4000 chars   (line numbers kept)
                          │
           agent decides: read(offset/limit) · grep · read_large_file(path, query)
                                                                │
                                         cache hit? ──yes──► cached index
                                                │no
                                   run_subagent(reader job) ─► fixed loop ─► index ─► cache ─► agent
```

## Marker format

```
<head: whole lines, ≤ 4000 chars>
[… lines {a}–{b} of {N} omitted (~{T:,} tokens). Full text: {path}
 Use read with offset/limit for a range, grep to locate content,
 or read_large_file(path="{path}", query=…) for an indexed digest.]
<tail: whole lines, ≤ 4000 chars>
```

- If one line is longer than the budget, that line is cut and marked `…`.
- For PDFs, the marker also mentions `pages`.
- For tool output: `{path}` is the saved file under `.dagi/hash_cache/tool_output/`. Line
  numbers refer to that file. Lines are not numbered in the head/tail, but the omitted
  range is given so `read(path, offset=a)` lands correctly.
- If the cache write failed, the marker says the full output was not saved and gives no
  path.

## Phases

### 1. Shared truncation — `tools/_truncate.py`
- `truncate_middle(lines, *, source, total_lines, line_offset=1, numbered, head_chars, tail_chars) -> str`
  builds head/tail on whole lines and renders the marker above.
- New `AgentConfig` fields `truncate_head_chars` / `truncate_tail_chars`, both default 4000.
  Clamp so head + tail + marker stays well under `reserve_tokens`.
- Unit tests: line boundaries, a single huge line, tiny input, numbered vs plain, marker
  ranges.

### 2. `read` truncates instead of delegating — `tools/read/_read.py`
- Drop the 2000-line default `limit`. With no `limit`, the whole file is selected and size
  alone decides whether to truncate. `offset`/`limit` still work and are truncated the
  same way if still too large.
- If the rendered output ≥ `reserve_tokens`, call `truncate_middle` with the **original
  path** and real line numbers.
- Remove `query`, `_delegate_to_read_large_text`, `_delegate_legacy` and
  `use_legacy_reader`. Update the tool description.
- Subagent `ReadTool` instances are built without `config` (`agent/subagent_tools.py`).
  Pass the threshold in explicitly so subagents truncate too.
- Factor file/document loading into a helper that `read_large_file` also uses.

### 3. Shared filter uses the same format — `tools/output_filter.py`
- Replace the head-only `reserve_tokens/2` preview with `truncate_middle` over the saved
  output. The tail is what matters for bash (pytest summary, tracebacks).
- Save the **raw text** (not the `__list__:` JSON form) so line numbers in the marker match
  the file.
- Remove the "DO NOT read the full output from the cache file" message. The marker now
  invites `read` / `grep` / `read_large_file` on that path.
- List (multimodal) results: truncate text parts only and pass images through, rather than
  cutting serialized JSON.
- Update `tests/test_output_filter.py`.

### 4. `read_large_file` tool — `tools/read_large_file/`
- Built-in `BaseTool` registered in `agent/tools.py`. Params: `path`, optional `query`,
  optional `offset`/`limit`, optional `pages` (PDF).
- Load the selection (shared loader) → cache lookup → `delegate_selection` via
  `run_subagent` (separate process, progress events, cancellation, handoff file) → store in
  cache → return.
- Replaces `read_large_text`: delete `.dagi/subagents/read-large-text/main.py` and
  `prompt.md`. Keep `subagent_config.yaml` for preset settings (`model_tier: worker`).

### 5. Reader loop rewrite — `tools/read/_reader_controller.py`, `_budgets.py`
Per chunk, one request containing system prompt + query + running summary (capped at
S chars) + chunk rendered **with line numbers**. The response has two parts:
- `<notes>` — this chunk's section entries: title, line range, key points, verbatim
  excerpts with line numbers. **Appended to a list and never rewritten.**
- `<summary>` — updated running summary, ≤ S chars, used only as context for the next
  chunk.

If a response doesn't parse, retry once, then fail.

Then the final merge: turn all notes into the index. If the notes don't fit one call,
merge in batches, then merge the batch results; repeat until one remains.

Budget changes:
- Chunk size K = C − base − S − O − M. Context per call no longer grows, so the
  whole-history preflight bound goes and file length is unlimited. Keep the per-call fit
  check.
- Fix the unit mismatch: `estimate_reader_request` counts bytes but is added to token
  values. Use the //4 token estimate throughout.
- Final output must fit the parent (< `reserve_tokens`). Keep the condensation retry for
  the merge step.

Fixes carried over:
- Section line ranges: compute the end line from the chunk's newline count
  (`_last_line` currently returns the start line of the last reference).
- Use the preset's worker model and the parent's `project_path`, not
  `selection.path.parent`.
- Check each excerpt against the source text by exact match. Drop or flag misses so
  quoted text is never invented.

Index format:
```
# {file} — {N} lines, ~{T} tokens{, query: …}
## Overview
3–5 sentences.
## Index
| Lines | Section | Contents |
|---|---|---|
| 1–240 | Introduction | … |
## Sections
### §1 Introduction (lines 1–240)
- key point
> "verbatim excerpt" (line 57)
```

### 6. Cache
- Key: sha256(selection text) + normalized query + model id + `READER_VERSION`. Bump
  `READER_VERSION` when prompts or chunking change.
- Stored through `tools/_hash_cache.get_or_compute` under the namespace
  `read_large_file`. Returned digests note `(cached)`.

### 7. Cleanup & docs
- Remove dead code: the `use_legacy_reader` path, legacy prompt, whole-history preflight,
  and `allocate_sections` if unused.
- Update tests: `test_read_tool.py`, `test_read_large_text_tool.py` (→
  `test_read_large_file_tool.py`), `test_reader_controller.py`, `test_reader_budgets.py`.
- README: tool table, tree, and the reader description. TODO: move this entry to Completed.

## Suggested order
1 → 2 → 3 make the truncation change; each can ship and be checked in isolation.
4 → 5 → 6 build the new tool. 7 is cleanup alongside.
