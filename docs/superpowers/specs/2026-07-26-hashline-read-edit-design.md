# Hash-anchored read/edit (hashline) — Design

> Date: 2026-07-26 | Status: approved, pending implementation plan
> Upstream reference: [RimuruW/pi-hashline-edit](https://github.com/RimuruW/pi-hashline-edit) (MIT)

## Problem

DAGI's `edit` addresses text by exact substring match (`oldText`/`newText`) and
requires the match to be unique in the file (`tools/edit/_edit.py:42`). This
fails in two common situations:

- **Ambiguity.** Repeated lines (`}`, `import x`, blank lines) cannot be
  targeted at all — the tool rejects the edit and tells the model to widen the
  context, costing tokens and round-trips.
- **Drift.** `read` output is `cat -n` numbered, but line numbers are not part
  of the edit contract, so the model reconstructs `oldText` by hand. Whitespace
  or content drift between read and edit produces a hard failure with no
  recovery path.

Hashline replaces substring addressing with a per-line **anchor**: a line number
plus a short hash of the line's local context. Edits target anchors, and the
anchor is revalidated against the file at edit time.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | **Hard replace.** `read`/`edit` are rewritten; no `oldText`-only path survives. | One way to edit. Avoids the model defaulting to the familiar shape and leaving the anchor system unused. |
| 2 | **Stateless validation.** `edit` recomputes the anchor table from disk and fails loud on mismatch. | DAGI subagents are separate OS processes (`tools/_subagent_runner.py`), so an in-memory read-time snapshot is invisible to the process that edits. Drops upstream's `snapshot.ts` and `merge.ts` entirely. |
| 3 | **Edit returns an anchors block only.** `ANCHOR_CONTEXT_LINES=2`, `ANCHOR_MAX_OUTPUT_LINES=12`, 50 KB guard. | Upstream parity. Lets the model chain a nearby follow-up edit without a re-read, while refusing to pay anchor-rendering cost on large edits. |
| 4 | **3-char base64url hash with perfect hashing.** Collisions resolved by appending `:R{retry}` to the hash input and recomputing until unique. | Diverges from upstream (2-char/16-char alphabet, no collision detection). Guarantees every line has a unique anchor and removes the need for upstream's fuzzy `textHint` subsystem. |
| 5 | **`grep` emits anchors.** Output becomes `path:LINE#HASH:content`. | Enables grep → edit with no intervening read — the largest workflow win. |
| 6 | **Converted documents are ordinary anchored files.** | `tools/read/_doc_service.py:53` already persists converted markdown to `.dagi/hash_cache/doc_convert/<sha256>.md` with LF endings, so those anchors are revalidatable. |
| 7 | **`replace_text` retained, desugared.** Resolved to a line range against the pre-edit snapshot, then applied through the positional path. | Anchors fail on staleness; `replace_text` fails on ambiguity. Orthogonal failure modes. Desugaring keeps a single execution path. |

### Accepted risk

Perfect hashing assigns retry indices in scan order, so a newly introduced
collision near the top of a file can shift the retry index of a colliding line
far below it, invalidating an anchor the model still holds. This forfeits
upstream's stated property that *"distant edits no longer invalidate anchors."*

Accepted because: 262,144 buckets make in-file collisions rare; and under
stateless fail-loud validation the failure mode is a clean `E_STALE_ANCHOR`
costing one re-read, never a silent wrong-line edit.

## Architecture

```
tools/_hashline.py          NEW — hash, anchor table, render, parse, resolve
tools/read/_read.py         emit LINE#HASH; disclose doc cache path
tools/edit/_edit.py         rewritten: batched anchored operations
tools/grep/_grep.py         emit path:LINE#HASH:content
```

`tools/_hashline.py` is a flat shared helper, matching the convention in
`AGENTS.md` for cross-tool utilities. It is the single source of truth for the
anchor format; no tool computes a hash independently. If it approaches the
500-line cap it splits into a `tools/_hashline/` package.

Constructor signatures for all three tools are unchanged, so `agent/tools.py`
and `agent/subagent_tools.py` require no edits — including the plan-mode
registration at `agent/tools.py:169` that scopes `EditTool` to the plan file.

### Hash

```python
_ALPHABET = "ABC...XYZabc...xyz0123456789-_"   # base64url, 64 chars
_HASH_LEN = 3                                   # 18 bits -> 262,144 buckets

def _line_hash(prev: str, curr: str, nxt: str, retry: int = 0) -> str:
    payload = f"{prev}\0{curr}\0{nxt}"
    if retry:
        payload += f":R{retry}"
    v = int.from_bytes(hashlib.blake2b(payload.encode(), digest_size=8).digest(), "big")
    return "".join(_ALPHABET[(v >> (6 * i)) & 63] for i in range(_HASH_LEN))
```

Table construction walks the file once. First and last lines use `""` for the
missing neighbour. On collision with an already-assigned hash, `retry`
increments until the hash is unique within the file.

- **`blake2b`, not `xxhash`.** Stdlib, no new dependency; `pyproject.toml` is
  the single source of truth for deps and has been actively trimmed. This is
  not cryptography — any modern digest gives adequate avalanche over a 3-line
  window.
- **Six bits per character.** Mask `& 63` per char rather than base-converting,
  mirroring upstream's nibble-per-char approach. Avoids modular bias and makes
  `_HASH_LEN` a pure knob on retained bits.
- **No content normalisation.** `read_text()` and `rg` both yield
  universal-newline text and `splitlines()` strips terminators, so lines never
  contain `\r`/`\n`. Beyond that, lines are hashed byte-exact including trailing
  whitespace: a real content change must invalidate the anchor.

## Tool contracts

### `read`

Parameters (`path`, `offset`, `limit`, `pages`) are unchanged. Output format
becomes `{lineno:>W}#{hash}:{content}`, where `W` is the width of the largest
line number in the returned window:

```
18#aB3:def resolve(path: str) -> Path:
19#Qx7:    return path.resolve()
```

Anchors are computed over the **entire file**, after which the `offset`/`limit`
window is rendered. A windowed read therefore yields anchors that validate; the
same rule makes `pages="5-6"` safe for documents.

Document reads disclose the editable artefact in the existing header:

```
[PDF: report.pdf | 12 pages | editable: .dagi/hash_cache/doc_convert/a3f9...c1.md]
```

The auto-summarisation gate (`tools/read/_read.py:176`) is unchanged. Upstream's
`raw` parameter is **not** ported — DAGI has a `copy` tool, and it can be added
later if verbatim content proves necessary.

### `edit`

Schema: `{path, edits: [...]}`.

| op | required | optional | behaviour |
|---|---|---|---|
| `replace` | `pos`, `lines` | `end` | replace one line, or the inclusive `pos..end` range |
| `append` | `lines` | `pos` | insert after `pos`; omit `pos` for EOF |
| `prepend` | `lines` | `pos` | insert before `pos`; omit `pos` for BOF |
| `replace_text` | `oldText`, `newText` | — | replace an exact, unique substring |

Execution, entirely within one call:

```
read file -> build anchor table
          -> resolve every edit against the PRE-EDIT snapshot
             (replace_text desugars here into a line range)
          -> reject overlapping ranges
          -> sort bottom-up, splice
          -> write LF-only
          -> rebuild table, render anchors window
```

Bottom-up application is what makes batching correct: splices perturb only the
indices below them, so every not-yet-applied edit's resolved index remains
valid.

Success returns the anchors block alone. If the changed span plus context
exceeds `ANCHOR_MAX_OUTPUT_LINES` or the 50 KB budget, the response degrades to
`"Anchors omitted; use read for subsequent edits."`

Targeting a `.pdf`/`.docx`/`.xlsx`/`.pptx` returns
`"cannot edit <ext> directly — edit the converted markdown at <cache path>"`.

Writes remain LF-only (`newline="\n"`), preserving the existing Windows CRLF
protection.

### `grep`

Output becomes `path:LINE#HASH:content`. `rg` still performs the search;
matches are grouped by file, and each file is read and hashed once.

**Anchors are only ever computed from a strict UTF-8 read.** The existing
Python fallback decodes with `errors="replace"` (`tools/grep/_grep.py:111`);
hashing that lossy text would yield anchors that look valid but can never match
`edit`'s strict-decode table. When a strict read fails, grep emits the match as
plain `path:lineno: content` with no anchor — the absent `#` signals that the
model must read before editing.

### Errors

| Code | Trigger |
|---|---|
| `E_STALE_ANCHOR` | line number in range, hash mismatch → re-read guidance |
| `E_INVALID_ANCHOR` | malformed anchor string, or line number out of range |
| `E_INVALID_PATCH` | supplied `lines` contain `N#hash:` prefixes or diff markers |
| `E_CONFLICT` | two edits in one batch target overlapping ranges |
| `E_TEXT_NOT_FOUND` | `replace_text` matched zero sites |
| `E_TEXT_AMBIGUOUS` | `replace_text` matched more than one site |
| `noop` | edits produced byte-identical content |

Upstream's `E_NOOP_LOOP` (three consecutive identical no-op edits) is **not**
ported: it requires cross-call state, which decision 2 forbids. Single-call
`noop` classification is retained.

## Testing

`EditTool` and `GrepTool` currently have **no** behavioural tests —
`tests/test_scope_tools.py` only asserts registration. This work establishes
coverage on the repo's most destructive tool rather than maintaining it.
Implementation follows TDD.

| File | Covers |
|---|---|
| `tests/test_hashline.py` (new) | determinism, neighbour sensitivity, first/last-line boundaries, collision retry, uniqueness |
| `tests/test_edit_tool.py` (new) | all four ops, batching, conflicts, every error code, noop, document guard, LF-on-Windows |
| `tests/test_grep_tool.py` (new) | anchor format, non-UTF-8 degrade path |
| `tests/test_read_tool.py` (update) | format assertions; doc-service mocks unchanged |

Three property tests carry the design:

1. **Uniqueness** — every anchor in a file is distinct. Run over the repo's own
   source files, which supply free adversarial input (many duplicate `}`,
   `import`, and blank lines).
2. **Cross-tool agreement** — `read`, `grep`, and `edit` compute an identical
   hash for the same file and line. This is the invariant that makes grep → edit
   legal.
3. **Bottom-up equivalence** — a batch of N edits yields byte-identical output
   to applying the same edits individually in descending line order.

## Migration

Prose and prompts only; no wiring changes.

- `AGENTS.md:199` — replace the `cat -n` contract note; add a `hashline` entry
  to Notes & Terms covering the anchor format, perfect hashing, and the accepted
  distant-invalidation risk.
- `README.md`, `TODO.md` — update per project rule.
- `projects/project_management_system/.dagi/skills/pms-ingest/SKILL.md:254` —
  retarget the troubleshooting line from non-unique `oldText` to stale anchors.
- **Tool descriptions** — the primary behavioural lever. `replace_text` must be
  described as a fallback for stale anchors, not a primary path. Precedent:
  rewording the `enter_plan_mode` description took adoption from zero
  (`AGENTS.md` Errors Log, 2026-07-19).

Untouched: `agent/tools.py`, `agent/subagent_tools.py`, all subagent configs,
and benchmark tool lists — tool names do not change. Historical design docs
under `docs/superpowers/` and dead code under `archive/` are not rewritten.

## Risks

- **One-way door.** Hard replace, no fallback, on the tool that writes files.
  Mitigated by the property tests, a manual smoke test against a real file
  before wiring, and git.
- **Distant anchor invalidation.** Accepted; see Accepted risk above.
- **Document cache lifecycle.** Edits to `.dagi/hash_cache/doc_convert/<sha>.md`
  persist only while the source document is unchanged. A modified source yields
  a new SHA and a fresh cache entry, silently orphaning prior edits. Acceptable
  for correcting a conversion; not durable storage.

## Out of scope

- Snapshot persistence, 3-way merge, and stale-anchor auto-recovery
  (upstream `snapshot.ts`, `merge.ts`).
- Fuzzy `textHint` matching (`hintMatchesLine`) — obviated by perfect hashing.
- `E_NOOP_LOOP` cross-call loop detection.
- A `hashline` config block. Constants live in `tools/_hashline.py`; a config
  surface can be added if `dagi_eval` later shows tuning is warranted.
- Upstream's `raw` read parameter.
