---
name: memory-add
description: >-
  File an entry into the Admiral's memory wiki (G:\My Drive\black_grimoire\wiki).
  Use after fixing an error, after a decision is approved, at task end (todos, ideas,
  reusable knowledge, completed todos), or when the user says remember this, save to
  memory, note this down, log this, add a todo.
---

# memory-add

Executed inline by the main agent. Do not spawn a subagent. Target: ≤3 tool calls.

Root (always absolute and quoted; a relative `wiki/` may hit a legacy project folder):
`"G:/My Drive/black_grimoire/wiki"`, written below as `$W`. `$W` is notation only:
substitute the literal quoted path in every command (shell state does not persist).

## 1. Choose the folder
- Would this help in a different repo? → `knowledge/<topic>/` (reuse an existing topic:
  `ls "$W/knowledge"`).
- Otherwise → `projects/<project>/` (project = repo/initiative, kebab-case).
- Open todo → `projects/<project>/todo/`. Life goals get their own project
  (e.g. `projects/bto-flat/`); one-off errands → `projects/personal/todo/`.
- Create the folder if missing. No index or log files, ever.

## 2. Check for an existing entry
`grep -rin -e "^title:.*<keyword>" -e "^tags:.*<keyword>" "$W/<folder>"` with 1–3 specific
keywords.
Match on the same subject → Edit that file (merge, don't duplicate).

## 3. Write
New file `$W/<folder>/<slug>.md`, slug = kebab-case of title, ≤50 chars:

```markdown
---
title: '<specific one-line title>'
description: '<one line, ≤200 chars: what it says / the fix>'
tags: [<3-10 grep keywords: identifiers, libraries, error class names, domain terms>]
updated: <YYYY-MM-DD today>
---
<body>
```

Rules:
- Exactly these four keys, each on one line; `tags` inline list. Editing = bump `updated`.
- **YAML quoting (or the entry won't parse):** always wrap `title` and `description` in
  single quotes, and single-quote any tag containing punctuation other than `-`, `_`, `.`
  (write a literal `'` as `''`) — e.g.
  `description: 'Fix: pass ambiguous=''infer'''` and `tags: [pandas, 'messages[0]', 'k: v']`.
- Optional check: `conda run -n vibecode python -m migrate_wiki.cli validate "<wiki root>"`
  (run from `G:\My Drive\black_grimoire\src`) reports any malformed entry.
- Tags are search keywords, not categories. No `notes`, `misc`, `info`.
- **Errors:** quote the error message verbatim in a code block, then `## Cause`, `## Fix`.
- **Decisions:** the choice, alternatives rejected, why, and the date.
- **Todos:** one file per todo; state a due date in the body if there is one.
- **Completed todo:** file any lesson as a normal entry first, then delete the todo file.

Report: path written and whether created or updated.
