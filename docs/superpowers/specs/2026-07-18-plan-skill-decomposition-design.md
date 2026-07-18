# Plan Skill Decomposition — Design

> Status: draft | Author: Claude-chan (via brainstorming session) | Date: 2026-07-18

## Problem Statement

The `plan-work-review` skill is a monolithic 200-line SKILL.md that owns the entire
lifecycle: requirements gathering, plan-mode entry, codebase exploration, plan
authoring, approval, execution (test → implement → review), and completion. This
makes individual phases non-reusable — you cannot invoke exploration or grilling
independently, and the skill cannot evolve one phase without risking regressions in
others.

Additionally, planning prompts are scattered across multiple locations (tool
descriptions in `tools/plan_mode.py`, the "Autonomous Plan Mode" section in
`.dagi/prompts/main/main_system.md`, the skill file itself, and the plan template
scaffolded by `agent/loop.py`). This makes it hard to reason about what instructions
the agent actually sees at each phase.

## Solution

Decompose `plan-work-review` into a chain of four independently-invokable skills,
each chaining to the next via a "invoke skill X next" instruction (matching the
superpowers plugin's composability pattern). Strip planning prompts from tool
implementations and system prompts so that skills are the single source of truth for
planning behavior.

### Skill Chain

```
grilling → plan → dagi-execute
                ↑
             to-spec (called by plan, not standalone)
```

### Process Flow

```
1.  User describes a task
2.  DAGI invokes `grilling`
3.  grilling: adversarial interrogation, one question at a time
4.  grilling closes with shared understanding summary
5.  grilling chains to `plan`
6.  plan: calls enter_plan_mode (infrastructure: state change + branch creation)
7.  plan: invokes to-spec (synthesizes conversation into spec/PRD, saves to disk)
8.  plan: explores codebase via spawn_explore_files_subagent
9.  plan: writes plan.md (implementation plan informed by spec + explore findings)
10. plan: show_plan → ask_user approve/modify/cancel loop
11. plan: calls exit_plan_mode (infrastructure: restore full tools)
12. plan chains to `dagi-execute`
13. dagi-execute: per subtask — main agent writes tests → worker implements → review grades
14. dagi-execute: main agent commits after each successful review
15. dagi-execute: calls complete_plan()
16. dagi-execute: invokes update-project-context skill + commits
17. dagi-execute: git checkout back to previous branch
```

## Skill Definitions

### 1. `grilling` (replaces `grill-me`, Mode A only)

**Location:** `.dagi/skills/grilling/SKILL.md`

**Triggers:** `grill`, `/grill`, `/grilling`, `stress-test this`, `grill my plan`

**Scope change from `grill-me`:** Removes Mode B (Socratic questioning on
topics/documents/codebases). Mode B becomes a separate skill in a future task.
Removes the elaborate Phase 1 knowledge-gathering protocol (codebase scan,
AGENTS.md, memory-wiki). The new skill is lightweight: if a fact can be found by
exploring the environment, look it up rather than asking; decisions are the user's.

**Content (per user-provided reference):**

```
Interview me relentlessly about every aspect of this until we reach a shared
understanding. Walk down each branch of the decision tree, resolving dependencies
between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before
continuing. Asking multiple questions at once is bewildering.

If a fact can be found by exploring the environment (filesystem, tools, etc.),
look it up rather than asking me. The decisions, though, are mine — put each one
to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.
```

**Closing behavior:** When shared understanding is reached, produce a closing
summary, then chain: "invoke `plan` next."

### 2. `plan` (new skill)

**Location:** `.dagi/skills/plan/SKILL.md`

**Triggers:** `/plan`

**Direct invocation:** `/plan` can be invoked directly when requirements are already
clear (skipping `grilling`). When chained from `grilling`, the conversation context
from the interrogation is already available — no re-gathering needed.

**Responsibilities:**

1. Call `enter_plan_mode(mode, task_summary)` — this is a pure infrastructure call
   (enters plan-mode state, creates git branch, restricts tools, switches to
   advanced model). The tool description contains no planning prompts.

2. Invoke `to-spec` — synthesizes the grilling conversation + codebase understanding
   into a spec/PRD document. Saves to `.dagi/plans/<plan_dir>/spec.md`. No
   interview — pure synthesis of what's already been discussed.

3. Explore the codebase via `spawn_explore_files_subagent(...)` with a task informed
   by the spec's Implementation Decisions and Testing Decisions sections.

4. Write `plan.md` — the implementation plan, informed by spec + explore findings.
   Plan format follows the current structure (Context, Approach, Files to Modify,
   Subtasks) with these additions:
   - Each subtask includes acceptance criteria + test snippets (not full test code —
     key assertions and approach hints that the main agent will expand into full
     test files at execution time)
   - Each subtask's execution protocol is baked in: write tests → worker implements
     → review subagent grades

5. `show_plan` → `ask_user` approve/modify/cancel loop.

6. On approve: call `exit_plan_mode` (infrastructure: restore full tools, return
   plan contents).

7. Chain: "invoke `dagi-execute` next."

### 3. `to-spec` (new skill, called by `plan`)

**Location:** `.dagi/skills/to-spec/SKILL.md`

**Not directly user-invokable** — called by the `plan` skill during plan mode.

**Content:** Follows the user-provided to-spec template. Synthesizes conversation
context and codebase understanding into a spec with these sections:

- Problem Statement
- Solution
- User Stories (extensive numbered list)
- Implementation Decisions (modules, interfaces, architecture — no file paths)
- Testing Decisions (what makes a good test, which modules, prior art)
- Out of Scope
- Further Notes

**Adaptation for DAGI:** "Publish to issue tracker" becomes "save to
`.dagi/plans/<plan_dir>/spec.md`" since DAGI has no issue tracker integration yet.

**Seam check:** Before writing the spec, sketch out the seams at which the feature
will be tested. Prefer existing seams to new ones. Use the highest seam possible.
Check with the user that seams match expectations.

### 4. `dagi-execute` (new skill)

**Location:** `.dagi/skills/dagi-execute/SKILL.md`

**Triggers:** `/execute`, `execute plan`, `start execution`

**Per-subtask cycle:**

1. Main agent reads subtask's acceptance criteria + test snippets from plan
2. Main agent writes full test files to `.dagi/plans/<plan_dir>/tests/`
3. Main agent updates plan's `#### Tests` subsection with test file paths
4. Worker subagent spawned via `spawn_worker_subagent(subtask_name, custom_instructions)`
   — worker is blind to tests
5. Review subagent spawned via `spawn_review_subagent(subtask_name, worker_handoff_path, unit_test_paths)`
   — grades against the hidden tests
6. Main agent evaluates review verdict:
   - **PASS:** mark subtask `[x]`, commit touched files, append PASS to
     `cycle_log.md`, update plan Notes section
   - **FAIL:** append FAIL to `cycle_log.md`, retry with augmented instructions
     (max 2 attempts; escalations are free and don't count toward budget)
   - **ESCALATED:** answer the question (or `ask_user` if it's a genuine product
     decision), re-spawn same subagent type — does not consume a retry

**After all subtasks resolved:**

1. Call `complete_plan()`
2. Invoke `update-project-context` skill
3. Commit context updates
4. `git checkout` back to previous branch (recorded at `enter_plan_mode` time)
5. Report summary: branch name, number of commits, files changed, reminder that
   branch is ready for user review and merge

**Failure escalation:** If 2 attempts exhausted without PASS, mark subtask `[!]`,
stop the cycle, present structured escalation report (attempt summaries, root cause
diagnosis, proposed solutions), wait for user guidance.

## Code Changes

### `tools/plan_mode.py` — Strip prompts from tool descriptions

**Current `EnterPlanModeTool.description`** (lines 11–17): Contains guidance on when
to use each mode and what `task_summary` is for.

**New description:**
```
"Enter plan mode. Restricts tools to read-only plus plan-file write. "
"Creates a git branch for the task."
```

**Current `ExitPlanModeTool.description`** (lines 41–45): Contains guidance on when
to call it (after approval or cancel).

**New description:**
```
"Exit plan mode. Restores full tool access."
```

### `.dagi/prompts/main/main_system.md` — Remove planning prompts

**Delete lines 31–41** (the "Autonomous Plan Mode" section). This guidance now lives
entirely in the `plan` skill.

Replace with a one-line pointer:
```
## Planning
Use the `plan` skill for tasks requiring planning. See `.dagi/skills/plan/SKILL.md`.
```

### `agent/loop.py` — Plan template cleanup

**Lines 736–753** (`_handle_enter_plan_mode`): The plan template scaffolded into
`plan.md` currently includes an "Execution Protocol" section with embedded
instructions. Strip this to just structural headers (Context, Approach, Files to
Modify, Subtasks, Notes, Verification). The execution protocol instructions move to
the `plan` skill and `dagi-execute` skill.

### `agent/loop.py` — Store previous branch for checkout

**In `_handle_enter_plan_mode`** (around line 756): Before creating the task branch,
record the current branch name (`git branch --show-current`) and stash it on
`self.config` (e.g. `self.config.previous_branch`). `dagi-execute` uses this at
step 17 to checkout back.

### `.dagi/skills/grill-me/` — Replace with `grilling/`

Delete `.dagi/skills/grill-me/SKILL.md`. Create `.dagi/skills/grilling/SKILL.md`
with the streamlined Mode-A-only content.

### `.dagi/skills/plan-work-review/` — Replace with `plan/` and `dagi-execute/`

Delete `.dagi/skills/plan-work-review/SKILL.md`. Create:
- `.dagi/skills/plan/SKILL.md`
- `.dagi/skills/to-spec/SKILL.md`
- `.dagi/skills/dagi-execute/SKILL.md`

## Migration Notes

- The current `plan-work-review` skill's triggers (`/plan`, `/plan-work-review`,
  `execute plan`) are redistributed: `/plan` goes to the `plan` skill, execution
  triggers go to `dagi-execute`.
- Any existing plans created under the old skill remain valid — the plan.md format
  is unchanged. `dagi-execute` can pick up mid-flight plans.
- The `grill-me` skill's Mode B (Socratic questioning) is out of scope for this
  work. It will become a separate skill in a future task.
- The `cycle_log.md` format and retry/escalation mechanics in `dagi-execute` are
  unchanged from the current `plan-work-review` Phase 2.

## Out of Scope

- Mode B (Socratic/quiz) skill extraction from `grill-me`
- Issue tracker integration for `to-spec`
- Changes to the blind-oracle test model (tests hidden from worker)
- Changes to the single worker/review execution model
- Inline execution alternative (superpowers' `executing-plans` analog)
- Changes to subagent spawning tools (`spawn_worker_subagent`,
  `spawn_review_subagent`, `spawn_explore_files_subagent`)
