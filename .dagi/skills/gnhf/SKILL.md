---
name: gnhf
description: Iterative committed development with cross-session notes — plan small milestones, commit each success, rollback failures, maintain per-session notes files for continuity across sessions
---

# GNHF — Good Night, Have Fun

Work toward an objective in small, committed iterations. Each session gets its own `notes_{datetime}.md` file. After each successful milestone, commit the work and write to the session notes so the next session knows exactly what was tried, what landed, and what comes next.

---

## Step 1 — Initialise the session

Run the init script, passing the objective:

```
bash("python .dagi/skills/gnhf/scripts/init.py \"<objective>\"")
```

The script will:
- Error if you are not on the `dagi` branch. If so, switch first:
  `bash("git checkout dagi")` — or `bash("git checkout -b dagi")` if it doesn't exist yet.
- Print the tail of the most recent prior session (if any) for orientation.
- Create a new `notes_{datetime}.md` for this session and set `.current_session` to point at it.

After init, read the current session's file for full context (it will be short at this point). If prior sessions exist and you need more context, read their tails:

```
bash("ls -lt .dagi/gnhf/notes_*.md")          # list all sessions newest-first
bash("tail -n 30 .dagi/gnhf/notes_<prev>.md") # read a prior session
```

**Before doing any work**, surface to the user:
- The objective (as reported by the init script)
- Any relevant context from prior sessions
- Ask: "Ready to begin, or do you want to adjust the objective?"

Wait for confirmation before proceeding.

---

## Step 2 — The loop

Repeat until the objective is fully met:

### 2a. Plan the next milestone

Identify the **smallest next step** that:
- Can be independently implemented and verified
- Leaves the codebase in a working state if committed right now
- Moves the objective meaningfully forward

Do not plan multiple milestones ahead. One at a time.

### 2b. Implement

Make the changes.

### 2c. Verify

Run whatever checks are appropriate for the milestone (tests, linting, manual inspection). If the project has a test suite, run it. If there are no automated checks, reason explicitly about correctness before committing.

### 2d. On success — commit and record

```
git_commit(message="gnhf: <imperative verb> <what was done>")
```

Then immediately append a note:

```
bash("python .dagi/skills/gnhf/scripts/append_note.py \"<commit-hash>\" \"<what was done, what was found, what comes next>\"")
```

Get the commit hash from the `git_commit` output. The note should be a short freeform paragraph — not bullet points. Write what a colleague would need to know to pick this up tomorrow.

Continue to the next milestone.

### 2e. On failure — rollback and record (retry_count < 3)

```
git_rollback()
```

Then record the failure:

```
bash("python .dagi/skills/gnhf/scripts/append_note.py \"FAILED\" \"FAILED: <error message> | Reason: <why it failed> | Expected fix: <what to try next>\"")
```

Increment your internal retry count for this milestone. Try a different approach.

### 2f. On failure — escalate (retry_count >= 3)

```
git_rollback()
bash("python .dagi/skills/gnhf/scripts/append_note.py \"FAILED\" \"FAILED (giving up): <error> | Reason: <why> | Tried: <approaches attempted>\"")
ask_user("Stuck after 3 attempts on: <milestone>. Last error: <error>. Options: <what you've tried>. How should I proceed?")
```

Reset retry count after escalating.

---

## Commit message convention

```
gnhf: <imperative verb> <what>
```

Examples:
- `gnhf: add user authentication module`
- `gnhf: fix null token edge case in session middleware`
- `gnhf: refactor database connection pool`

Keep it under 72 characters.

---

## Reading history

**Current session:**
```
bash("cat .dagi/gnhf/.current_session")        # get active filename
bash("tail -n 50 .dagi/gnhf/notes_<name>.md") # read it
```

**List all sessions** (newest first):
```
bash("ls -lt .dagi/gnhf/notes_*.md")
```

**Read a prior session:**
```
bash("tail -n 30 .dagi/gnhf/notes_20260513_210000.md")
```

**Scan for failures across all sessions:**
```
bash("grep -n \"FAILED\\|^## \" .dagi/gnhf/notes_*.md")
```

---

## Done

When the objective is fully met:

```
ask_user("Objective complete. All milestones committed to the 'dagi' branch. Ready to merge to main?")
```

Do not merge automatically — branching is the user's responsibility.
