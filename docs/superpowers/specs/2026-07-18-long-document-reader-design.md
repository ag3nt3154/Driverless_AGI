# Long Document Reader — Design Spec

> **Date:** 2026-07-18
> **Status:** Approved
> **Problem:** When `ReadTool` output exceeds the token budget, `output_filter.py` truncates it and tells the LLM to "read chunk by chunk with offset/limit." This causes cascading truncation (each chunked read is itself truncated into a new hash cache file), wastes 5+ tool calls per large document, and triggers premature context compaction — all without the LLM ever gaining holistic understanding.

---

## Solution: Automatic Accumulative-Summary Reader Subagent

When `read()` detects that a document exceeds the `reserve_tokens` budget, it automatically spawns a `document-reader` subagent instead of truncating. The subagent reads the document in chunks, builds an accumulative summary with per-section structure, writes the digest to a cache file, and the parent receives the sectioned summary as the tool result.

---

## Output Format

The parent LLM receives a sectioned digest with line ranges, summaries, and key excerpts per section. This lets the parent identify areas of interest and drill into specific line ranges with targeted `read(path, offset, limit)` calls.

```
[Document: <filename> | <N> pages | full text cached: <cache_path>]

## <Section Heading> (lines <start>-<end>, ~<T> tokens)
**Summary:** <section summary, written in context of all prior sections>
**Key excerpts:**
- L<N>: "<verbatim quote or description>"
- L<N>-<M>: <table/formula/definition description>

## <Next Section Heading> (lines <start>-<end>, ~<T> tokens)
**Summary:** ...
**Key excerpts:**
- ...

...

---
Full text: <cache_path>
Use read(path, offset, limit) for verbatim content from any section.
```

Each section header includes an estimated token count (`~<T> tokens`) so the parent LLM can gauge the cost of drilling into a section before issuing a targeted read.

---

## Trigger & Flow

1. `ReadTool.run()` returns the full document text (from file, PDF cache, or markitdown conversion)
2. Estimated token count is checked against `reserve_tokens` (same threshold used by `output_filter.py`)
3. If under budget → return raw text as today (no change)
4. If over budget:
   a. Save full text to hash cache (`tool_output/` namespace, as today)
   b. Check for existing summary in `document_summary/` cache namespace (keyed by SHA-256 of full text)
   c. If cache hit → read and return the cached summary (no subagent, no LLM cost)
   d. If cache miss → spawn `document-reader` subagent → wait for completion → read the written summary file → return to parent

**Decision point:** The trigger lives in `ReadTool.run()` (or a wrapper around it), not in `output_filter.py`. This ensures the subagent path is only activated for `read` results, not arbitrary large tool outputs (bash, grep, etc.) which should continue to use dumb truncation.

**Config access:** `ReadTool` needs `reserve_tokens` and `project_path` to decide when to trigger summarization and where to find/write cache files. These are passed at construction time (same pattern as `cwd` and `allowed_roots` today).

---

## Reader Subagent — Internal Mechanics

### Chunking

The subagent reads the cached full text in chunks via `read(path, offset, limit)`. Default chunk size: ~2000 lines (matching the current `read` default). Section boundaries are detected heuristically:

- Markdown headings (`#`, `##`, etc.)
- PDF page markers (`<!-- Page N -->`)
- Fixed-size windows as fallback for unstructured text

### Accumulative Summary Loop

```
accumulative_summary = ""
sections = []

for each chunk (lines start..end):
    1. read(cached_path, offset=start, limit=chunk_size)
    2. LLM call:
       - System: "You are a document reader. For this section:
                  1. Identify the section heading (or infer one).
                  2. Write a summary in context of the prior summary.
                  3. Extract key excerpts: tables, formulas, definitions,
                     critical quotes. Include line numbers.
                  4. Note the line range.
                  5. Estimate the token count of this section (~chars/4)."
       - User: "Prior summary:\n{accumulative_summary}\n---\n
                New section (lines {start}-{end}):\n{chunk_text}"
    3. Parse LLM response into: heading, summary, key_excerpts
    4. Append to sections[] (with estimated token count for the chunk)
    5. Update accumulative_summary (append + compress if growing too large)
```

### Verification Pass

After completing the accumulative summary loop, the subagent performs a verification pass: it reviews the summary for claims that depend on precise details (numbers, formulas, specific names, dates) and uses `grep` and targeted `read` calls to verify them against the source text. This catches hallucinated details and strengthens key excerpts with accurate line references.

The system prompt encourages this explicitly:

> "After summarizing all sections, review your summary for specific claims
> (numbers, formulas, names, percentages, table values). Use grep and read
> to verify at least the most critical details against the source text.
> Correct any inaccuracies before writing the final digest."

### Model Tier

The subagent uses the **worker tier** model (configured in `config.yaml`) — cheaper than the main model, appropriate for summarization work.

### Tool Access

Minimal toolset: `read`, `grep`, `write`.

- `read` — to read chunks from the cached full text
- `grep` — to search within the document if needed
- `write` — to write the final sectioned digest to the summary cache

---

## Handoff Mechanism

The reader subagent writes its output to a deterministic cache path:

```
.dagi/hash_cache/document_summary/<sha256>_summary.md
```

Where `<sha256>` is the SHA-256 of the full document text (same hash used by other cache namespaces).

**Subagent's final action:**
1. Assemble the full sectioned digest (header + per-section summaries/excerpts + footer with cache path)
2. `write()` to `document_summary/<sha256>_summary.md`
3. Return the path via stdout

**Parent reads the written file** and returns it as the `read` tool result.

### Cache Hit Benefit

Second read of the same document → instant return. No subagent spawn, no LLM calls. Cache invalidates automatically when document content changes (different SHA-256).

---

## Integration Points

| Component | Change |
|-----------|--------|
| `tools/read.py` | After getting full text, estimate tokens vs `reserve_tokens`. If over → check summary cache → spawn subagent on miss → return summary |
| `tools/output_filter.py` | No change needed if trigger moves to `read.py`. `read` results that go through the subagent path arrive already within budget. Non-`read` large outputs continue to use dumb truncation. |
| `.dagi/subagents/document-reader/` | New subagent config: `tools: [read, grep, write]`, worker tier, summarization system prompt |
| `tools/_hash_cache.py` | Add `document_summary` as a new cache namespace alongside `pdf` and `tool_output` |

---

## Edge Cases

| Case | Handling |
|------|----------|
| Document changes after summary cached | Automatic: SHA-256 is content-based, changed file → different hash → cache miss → re-summarize |
| Subagent fails mid-read | Fall back to current truncation behavior (save full text to `tool_output/` cache, return truncated preview + "read chunk by chunk") |
| Document just barely over budget | Still summarize. Threshold is `reserve_tokens`, no grey zone. |
| Non-text content (images, diagrams) | Subagent works on markdown conversion — images already lost. Notes `[Figure N]` / `[Table N]` placeholders if present. |
| Already-cached PDF markdown | Reader subagent reads from PDF cache (`.dagi/hash_cache/pdf/`), no double-conversion |
| Very large documents (100+ pages) | Accumulative summary may itself grow large — the subagent compresses/rewrites the accumulative summary periodically to stay within its own context window |

---

## What Does NOT Change

- `read()` behavior for documents under the budget — unchanged, raw text returned
- `output_filter.py` behavior for non-`read` tools (bash, grep) — unchanged, dumb truncation
- The hash cache structure — new namespace added, existing namespaces untouched
- PDF conversion pipeline — untouched, reader subagent consumes its output
- `offset`/`limit`/`pages` parameters on `read` — still work for targeted reads after seeing the summary
