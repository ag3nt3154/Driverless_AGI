# Tool Output Filter — Design Spec

**Date:** 2026-06-30  
**Status:** Approved

---

## Problem

DAGI's tools (grep, read, bash, etc.) can return arbitrarily large text. If a tool result
exceeds the model's remaining context budget, the next API call fails immediately with a
context-length error, crashing the session. There is currently no safeguard between the raw
tool output and the content that enters `_messages`.

---

## Goal

Introduce a filter layer between `registry.dispatch()` and `_messages` that:

1. Passes small results through unchanged.
2. For large results: saves the full output to a temp file and places a truncated preview +
   pointer in context, telling the agent to read the file chunk by chunk.

---

## Architecture

### New file: `tools/output_filter.py`

A single pure function with no class or state:

```python
def filter_tool_output(
    result: str | list,
    reserve_tokens: int,
    temp_dir: Path,
) -> tuple[str | list, str]:
    ...
```

**Returns:** `(context_result, full_str)`
- `context_result` — what enters the LLM context and TUI callback (filtered if large)
- `full_str` — full serialised result for the JSONL tracker (always unfiltered)

### Modified file: `agent/loop.py`

One new call site, inserted after the sentinel-handling block and before `result_str`
is built. No other changes to `loop.py`.

---

## Data Flow

```
registry.dispatch()
    │
    ▼
sentinel checks (ENTER_PLAN_MODE, EXIT_PLAN_MODE, RELOAD_SKILLS, SWITCH_MODEL)
    │
    ▼
filter_tool_output(result, reserve_tokens, temp_dir)
    ├── context_result ──► callbacks.on_tool_end()          [TUI, filtered]
    │                 ──► _messages["content"]               [LLM context, filtered]
    └── full_str      ──► tracker.record_tool_end()          [JSONL, full]
                      ──► ToolCallRecord.result              [JSONL via record_assistant, full]
```

---

## Filter Logic

### Token estimation

```python
_CHARS_PER_TOKEN = 4
estimated_tokens = len(full_str) // _CHARS_PER_TOKEN
```

Same `len // 4` heuristic used by `compact.py`. No new dependency.

### Threshold

```python
if estimated_tokens < reserve_tokens:
    return result, full_str   # pass-through, no filtering
```

`reserve_tokens` comes from `AgentConfig.reserve_tokens` (default 16 384; read from
`config.yaml`). The same field that gates context compaction is reused here — if an output
is large enough to threaten the compaction reserve, it's too large to enter context raw.

### Preview size

```
preview_chars = (reserve_tokens // 2) * _CHARS_PER_TOKEN
preview = full_str[:preview_chars]
```

Half the reserve budget. With the default of 16 384, the preview is ~8 192 tokens (~32 KB of
text) — enough for the agent to understand the structure of the output and form a read plan.

### Temp file

Written atomically using the project's established TOCTOU-safe pattern
(`tempfile.mkstemp` + `os.close(fd)` + `write_text()`):

```python
temp_dir.mkdir(parents=True, exist_ok=True)
fd, tmp_path = tempfile.mkstemp(dir=temp_dir, prefix="tool_output_", suffix=".txt")
os.close(fd)
Path(tmp_path).write_text(full_str, encoding="utf-8")
```

**Location:** `DAGI_ROOT / ".dagi" / "temp"` — temp files belong to DAGI's own directory,
not the project being edited. `DAGI_ROOT` is imported from `agent` (the canonical constant).

### Context message placed in `_messages`

```
{preview — first reserve_tokens/2 tokens}

--- OUTPUT TRUNCATED ---
Full output saved to: <abs_path_to_temp_file>
Tool output is very large (~N tokens estimated). Read it chunk by chunk
using the read tool with the offset and limit parameters.
```

### List (multimodal) results

`result` can be a `list` (OpenAI vision format, base64-encoded images). For size estimation
and preview, the list is first serialised: `"__list__:" + json.dumps(result)`. If filtered,
`context_result` is always a plain `str` — the agent receives a text message, not a broken
image payload.

---

## Error Handling

| Condition | Behaviour |
|-----------|-----------|
| `temp_dir` creation fails | Fail open: return original unfiltered result; emit warning via `on_assistant_text` |
| File write fails | Same: fail open + warning |
| `reserve_tokens == 0` | Skip filtering entirely (divide-by-zero guard on `// 2`) |

Filtering must never crash the agent loop. All disk errors are caught and handled with
graceful degradation.

---

## Call Site in `agent/loop.py`

Replace the existing `result_str` block (currently lines ~556–568) with:

```python
# ── Output filter ────────────────────────────────────────────────────────────
_temp_dir = DAGI_ROOT / ".dagi" / "temp"
context_result, full_str = filter_tool_output(
    result, self.config.reserve_tokens, _temp_dir
)
result_str = (
    context_result if isinstance(context_result, str)
    else "__list__:" + json.dumps(context_result)
)
self.callbacks.on_tool_end(tc.function.name, result_str)    # filtered
self.tracker.record_tool_end(tc.function.name, full_str)     # full (JSONL)
# ─────────────────────────────────────────────────────────────────────────────

tool_records.append(ToolCallRecord(
    name=tc.function.name,
    description=description,
    input=tc.function.arguments,
    result=full_str,                                         # full (JSONL)
))
self._messages.append(
    {"role": "tool", "tool_call_id": tc.id, "content": context_result}  # filtered
)
```

---

## Config

No new config fields. `reserve_tokens` is already in `config.yaml` and `AgentConfig`.
The filter reuses the existing value — no additional knobs for the user to manage.

---

## Files Changed

| File | Change |
|------|--------|
| `tools/output_filter.py` | **New** — `filter_tool_output()` function |
| `agent/loop.py` | **Modified** — call site after sentinel block |

No changes to: registry, callbacks, tracker, config loader, or any tool.

---

## Non-goals

- No cleanup/expiry of `.dagi/temp/` files (future work).
- No per-tool allow/deny list (filter applies to all tools uniformly).
- No exact tokenizer (rough `len // 4` is sufficient; same bar as compaction).
