---
name: wiki-add
description: >-
  File an entry into the project wiki (<project_folder>/wiki).
  Use after fixing an error, after a decision is approved, at task end (todos, ideas,
  reusable knowledge, completed todos), or when the user says remember this, save to
  memory, note this down, log this, add a todo.
---

# wiki-add

Update the project wiki `<project_folder>/wiki` with new information. This skill is executed inline by the main agent. Do not spawn a subagent. Target: ≤3 tool calls.

## 1. Check for an existing entry
Use `grep` with 1–3 specific keywords to look for a related entry, for example if you are adding a decision about a function, search for the function name. If you find an entry on the same subject, edit that file (merge, don't duplicate).

## 3. Write
If a new entry is needed, create a new file `<project_folder>/wiki/<slug>.md`, where `<slug>` is a kebab-case version of the title, ≤50 chars. The file should have the following structure:

```markdown
New file `<project_folder>/wiki/<slug>.md`, slug = kebab-case of title, ≤50 chars:

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
- Tags are search keywords, not categories. No `notes`, `misc`, `info`.
- **Errors:** quote the error message verbatim in a code block, then `## Cause`, `## Fix`.
- **Decisions:** the choice, alternatives rejected, why, and the date.
- **Todos:** one file per todo; state a due date in the body if there is one.
- **Completed todo:** file any lesson as a normal entry first, then delete the todo file.

Report: path written and whether created or updated.
