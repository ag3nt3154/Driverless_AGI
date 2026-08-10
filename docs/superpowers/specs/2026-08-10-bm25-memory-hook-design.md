# Design: BM25 Memory Recall — Claude Code UserPromptSubmit Hook

**Date:** 2026-08-10  
**Status:** Approved

---

## Overview

A global Claude Code hook that fires on `UserPromptSubmit`, runs BM25 retrieval against the
personal memory wiki, displays retrieved items to the user in the terminal, and injects them
into Claude's context via `systemMessage`. Zero extra LLM calls; deterministic; ~100ms latency.

Implements the passive retrieval half of [TODO-013] at the Claude Code layer rather than as a
DAGI tool — meaning it benefits all Claude Code sessions, not just DAGI.

---

## Architecture

```
User types prompt
       │
  UserPromptSubmit hook fires
       │
  [bm25_memory_recall.py]
       ├── is_substantive()? ──No──→ exit 0 (no-op)
       │        Yes
       ├── glob + parse all wiki .md files
       ├── build BM25Okapi index in-memory (rank_bm25)
       ├── score against prompt tokens
       ├── apply Reasonix gates
       ├── write formatted display → stderr   (user sees this)
       └── write { "systemMessage": "..." } → stdout  (Claude sees this)
       │
  Claude Code receives prompt + injected systemMessage
```

**Single file.** Script lives at `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py`.  
**Global scope.** Registered in `~/.claude/settings.json` — fires for all Claude Code sessions.

---

## Files

| Path | Purpose |
|------|---------|
| `C:\Users\alexr\.claude\hooks\bm25_memory_recall.py` | Hook script |
| `C:\Users\alexr\.claude\settings.json` | Hook registration (add `UserPromptSubmit` entry) |

---

## Substantiveness Filter

Skip the BM25 retrieval entirely if the prompt is conversational or too short.

```python
MIN_WORDS = 8
SKIP_OPENINGS = {
    "thanks", "thank you", "ok", "okay", "yes", "no",
    "sure", "got it", "great", "good", "sounds good", "perfect"
}

def is_substantive(prompt: str) -> bool:
    words = prompt.lower().split()
    if len(words) < MIN_WORDS:
        return False
    lead = " ".join(words[:2])
    return words[0] not in SKIP_OPENINGS and lead not in SKIP_OPENINGS
```

---

## BM25 Retrieval

**Corpus:** All `.md` files under `G:\My Drive\black_grimoire\dagi-memory\wiki\` (recursive),
excluding dot-files (`.index.md` etc).

**Document representation:** For each file, concatenate `title + tags + description + body`
into a single string for tokenisation. Frontmatter is parsed separately to extract title,
tags, and description as high-signal fields.

**Tokenisation:** `re.findall(r'\w+', text.lower())` — simple word-level, lowercased.

**Index:** `BM25Okapi` from `rank_bm25`, built fresh per invocation (~100ms for ~100 files).

### Reasonix Gates (from TODO-013)

| Gate | Value |
|------|-------|
| Relative score cutoff | Drop results scoring < 24% of top score |
| Max results | 8 |
| Char budget | 2400 chars total across all injected entries |
| Body snippet per result | 300 chars |

**Graceful degradation:** If `rank_bm25` is not installed or wiki root doesn't exist,
exit 0 silently — hook never crashes or blocks the prompt.

---

## Output

### stderr → displayed to user

```
[memory-recall] 3 item(s) retrieved:
  • Ralph Loops — Simple AI Agent Harness Pattern
    (knowledge/llm-agents/ralph-loops.md)
  • DAGI: Passive BM25 memory_recall tool
    (todos/todo_013_dagi-passive-bm25-memoryrecall-tool.md)
  • LLM Wiki Pattern
    (knowledge/llm-agents/llm-wiki-pattern.md)
```

### stdout → JSON injected into Claude's context

```json
{ "systemMessage": "[Memory Wiki — Retrieved Context]\n\n### Title\ndescription\nsnippet...\n\n..." }
```

Each entry in `systemMessage`: `### {title}`, description line, up to 300 chars of body.

---

## Hook Registration

Add to `C:\Users\alexr\.claude\settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "conda run -n dagi python C:/Users/alexr/.claude/hooks/bm25_memory_recall.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

---

## Error Handling

- Missing `rank_bm25`: exit 0 (silent skip)
- Wiki root missing: exit 0 (silent skip)
- Empty corpus: exit 0
- All scores zero: exit 0
- Any uncaught exception: exit 0 (never block user prompt)

All failures are silent — a broken hook must never prevent the user from submitting a prompt.

---

## Out of Scope

- Index caching (premature for ~100 files at ~100ms rebuild)
- LLM-based substantiveness classification
- Semantic/embedding-based retrieval (that's the `memory-query` subagent's job)
- Filtering by wiki category
