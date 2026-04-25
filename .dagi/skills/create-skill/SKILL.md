---
name: create-skill
description: Create a new SKILL.md file so future agents can reuse learned workflows
triggers: create a skill, build a skill, write a skill, new skill, add a skill, make a skill, define a skill
---

# Creating a New Skill

## What is a Skill?

A skill is a `SKILL.md` markdown file that provides detailed, reusable guidance for a specific
workflow or technique. Skills are discovered at session start and listed alongside tools in the
system prompt. The agent can invoke the `skill` tool autonomously to load their full content.

## Skill Locations

| Location | Scope |
|---|---|
| `<dagi_root>/skills/<skill-name>/SKILL.md` | Built-in — available in every project |
| `<project>/.dagi/skills/<skill-name>/SKILL.md` | Project-specific — this project only |

Use the project location for skills that encode project-specific conventions. Use the built-in
location for general-purpose techniques that are useful across all projects. Project skills
override built-in skills of the same name.

## SKILL.md Format

Every `SKILL.md` must begin with YAML frontmatter, followed by the skill body:

```
---
name: my-skill-name        # kebab-case; defaults to the parent directory name if omitted
description: One-line summary shown in the system prompt (keep under 120 chars)
---

# My Skill Name

[Full markdown guidance here. Be specific and actionable — this content is only loaded
on demand, so thoroughness is preferred over brevity.]
```

### Frontmatter fields

- **`name`** — The identifier used when calling `skill("my-skill-name")`. Lowercase, hyphens OK.
  Defaults to the parent directory name if omitted.
- **`description`** — Shown in the system prompt skills list. Use a verb phrase:
  e.g. *"Generate pytest test suites for Python modules"*.

## Steps to Create a Skill

1. **Choose a name** — descriptive, kebab-case (e.g. `write-tests`, `refactor-module`, `api-client`)
2. **Choose a location** — built-in (`./skills/`) or project (`./.dagi/skills/`)
3. **Create the directory**:
   ```bash
   mkdir -p skills/<name>
   # or for project-specific:
   mkdir -p .dagi/skills/<name>
   ```
4. **Write the `SKILL.md`** using the format above
5. **Verify** — the skill appears in the `/skills` CLI command on the next session start

## Example

Creating a built-in skill for writing unit tests:

```bash
mkdir -p skills/write-tests
```

`skills/write-tests/SKILL.md`:
```
---
name: write-tests
description: Generate pytest test suites following project conventions
---

# Writing Tests

## Structure
- Place tests in `tests/` mirroring the source tree
- Name files `test_<module>.py`
...
```

## Tips

- The **description** is the only thing shown in the system prompt — make it scannable
- The **body** is loaded on demand via `skill("name")` — be thorough
- Skills can reference any available tool (`bash`, `read`, `write`, `edit`, etc.)
- A skill can call other skills by instructing the agent to invoke `skill("other-skill")`
