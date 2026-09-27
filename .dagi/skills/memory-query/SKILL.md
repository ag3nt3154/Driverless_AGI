---
name: memory-query
description: >-
  Search the Admiral's memory wiki (G:\My Drive\black_grimoire\wiki) with grep and answer
  with citations. Use at the start of every task, BEFORE debugging any error (grep the exact
  error text), before a design choice, or when the user asks what do I know about X / have
  we seen this before.
---

# memory-query

Read-only, executed inline by the main agent. Do not spawn a subagent.

Root (always absolute and quoted; a relative `wiki/` may hit a legacy project folder):
`"G:/My Drive/black_grimoire/wiki"`, written below as `$W`. `$W` is notation only:
substitute the literal quoted path in every command (shell state does not persist).
Layout: `projects/<p>/*.md`, `projects/<p>/todo/*.md`, `knowledge/<topic>/*.md`.
Frontmatter lines: `title:`, `description:`, `tags:`, `updated:`.

## Search order (stop when you have enough)
1. `"$W/projects/<current-project>"` — plus `ls "$W/projects/<p>/todo"` at task start.
2. `"$W/knowledge"`
3. All of `"$W"`

## How
- **Errors:** grep the exact distinctive part of the message, fixed-string:
  `grep -rnF "<error text>" "$W"`. Then try the error class name alone.
- **Topics:** grep frontmatter first:
  `grep -rin -e "^title:.*<kw>" -e "^tags:.*<kw>" -e "^description:.*<kw>" "<scope>"`,
  then bodies `grep -ril "<kw>" "<scope>"` if frontmatter misses.
- Use 2–4 specific keywords (identifiers, library names), not generic words.
- Read only the matching files (limit to the best ~5).

## Answer
- Cite each fact as `wiki/<path>` with its `updated` date.
- If nothing matches, say "No wiki entry found" — then proceed normally.
- Stale entry (contradicted by current code)? Say so; fix it via memory-add after the task.
