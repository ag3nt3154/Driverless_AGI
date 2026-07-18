# Plan Skill Decomposition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose the monolithic `plan-work-review` skill into a composable chain of four skills (`grilling` → `plan` → `to-spec` → `dagi-execute`), strip planning prompts from tool implementations and system prompts, and add previous-branch tracking for end-of-task checkout.

**Architecture:** Replace the single `plan-work-review/SKILL.md` with four independent skill files chained via "invoke X next" instructions. Move all planning guidance out of `tools/plan_mode.py` descriptions, `main_system.md`, and the plan template in `agent/loop.py` into the `plan` skill. Add a `previous_branch` field to `AgentConfig` and a `get_current_branch()` helper to `agent/_git_branch.py`.

**Tech Stack:** Python 3.14, Markdown skill files, pytest

---

## File Structure

### Files to Create
- `.dagi/skills/grilling/SKILL.md` — streamlined adversarial interrogation skill (Mode A only)
- `.dagi/skills/plan/SKILL.md` — plan-mode orchestration skill
- `.dagi/skills/to-spec/SKILL.md` — conversation-to-spec synthesis skill
- `.dagi/skills/dagi-execute/SKILL.md` — execution cycle skill
- `tests/test_previous_branch.py` — tests for previous-branch tracking

### Files to Modify
- `tools/plan_mode.py:11-17,41-45` — strip prompts from tool descriptions
- `.dagi/prompts/main/main_system.md:31-41` — remove Autonomous Plan Mode section
- `agent/_git_branch.py` — add `get_current_branch()` helper
- `agent/loop.py:116-165` — add `previous_branch` field to `AgentConfig`
- `agent/loop.py:722-790` — record previous branch before creating task branch, strip Execution Protocol from plan template

### Files to Delete
- `.dagi/skills/grill-me/SKILL.md` — replaced by `grilling`
- `.dagi/skills/plan-work-review/SKILL.md` — replaced by `plan` + `dagi-execute`

---

### Task 1: [ ] Add `get_current_branch()` helper and `previous_branch` config field

**Files:**
- Modify: `agent/_git_branch.py`
- Modify: `agent/loop.py:116-165`
- Test: `tests/test_git_branch.py`

- [ ] **Step 1: Write the failing test for `get_current_branch()`**

Add to `tests/test_git_branch.py`:

```python
from agent._git_branch import get_current_branch


class TestGetCurrentBranch:
    def test_returns_branch_name_in_repo(self, tmp_path: Path):
        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
        assert get_current_branch(tmp_path) == "main"

    def test_returns_none_outside_repo(self, tmp_path: Path):
        assert get_current_branch(tmp_path) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi pytest tests/test_git_branch.py::TestGetCurrentBranch -v`
Expected: FAIL with "cannot import name 'get_current_branch'"

- [ ] **Step 3: Implement `get_current_branch()` in `agent/_git_branch.py`**

Add after `is_git_repo()` (after line 48):

```python
def get_current_branch(cwd: Path) -> str | None:
    """Return the current branch name, or None if not in a git repo."""
    if not is_git_repo(cwd):
        return None
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n dagi pytest tests/test_git_branch.py::TestGetCurrentBranch -v`
Expected: PASS

- [ ] **Step 5: Add `previous_branch` field to `AgentConfig`**

In `agent/loop.py`, after line 141 (`active_plan_file: str | None = None`), add:

```python
    # Branch the user was on before entering plan mode — used for checkout-back at task end
    previous_branch: str | None = None
```

- [ ] **Step 6: Commit**

```bash
git add agent/_git_branch.py agent/loop.py tests/test_git_branch.py
git commit -m "feat: add get_current_branch helper and previous_branch config field"
```

---

### Task 2: [ ] Record previous branch in `_handle_enter_plan_mode` and strip plan template

**Files:**
- Modify: `agent/loop.py:722-790`
- Test: `tests/test_plan_mode_branch.py`

- [ ] **Step 1: Write the failing test for previous branch recording**

Add to `tests/test_plan_mode_branch.py`:

```python
class TestEnterPlanModePreviousBranch:
    def test_records_previous_branch(self, git_repo: Path):
        loop = _make_loop(git_repo)
        loop._handle_enter_plan_mode({"mode": "interactive", "task_summary": "test-task"})
        assert loop.config.previous_branch == "main"

    def test_previous_branch_none_without_git(self, tmp_path: Path):
        loop = _make_loop(tmp_path)
        loop._handle_enter_plan_mode({"mode": "interactive", "task_summary": "test-task"})
        assert loop.config.previous_branch is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n dagi pytest tests/test_plan_mode_branch.py::TestEnterPlanModePreviousBranch -v`
Expected: FAIL with `assert None == "main"`

- [ ] **Step 3: Record previous branch in `_handle_enter_plan_mode`**

In `agent/loop.py`, in `_handle_enter_plan_mode`, add before the `branch_name: str | None = None` line (before line 756):

```python
        from agent._git_branch import get_current_branch
        self.config.previous_branch = get_current_branch(self.config.project_path)
```

Note: `get_current_branch` is already imported via the module — add it to the existing import at the top of the function or at file level.

- [ ] **Step 4: Strip Execution Protocol from plan template**

In `agent/loop.py`, `_handle_enter_plan_mode`, replace the `plan_file.write_text(...)` call (lines 736-754) with:

```python
        plan_file.write_text(
            f"# Plan: {task_summary}\n\n"
            "## Context\n\n\n"
            "## Approach\n\n\n"
            "## Files to Modify\n\n\n"
            "## Subtasks\n\n"
            "### Subtask 1: [ ] \n"
            "**Goal:** \n"
            "**Requirements:**\n"
            "- \n"
            "**Acceptance Criteria:**\n"
            "- \n"
            "#### Tests\n\n"
            "## Notes\n\n"
            "## Verification\n\n",
            encoding="utf-8",
        )
```

Changes: removed the `<!-- Filled by main agent... -->` comment and removed the empty `## Execution Protocol` section.

- [ ] **Step 5: Run tests to verify everything passes**

Run: `conda run -n dagi pytest tests/test_plan_mode_branch.py -v`
Expected: all tests PASS (including existing ones — `test_plan_title_seeded_with_task_summary` still passes because the plan header format is unchanged)

- [ ] **Step 6: Commit**

```bash
git add agent/loop.py tests/test_plan_mode_branch.py
git commit -m "feat: record previous branch on plan-mode entry, strip template prompts"
```

---

### Task 3: [ ] Strip prompts from `tools/plan_mode.py` and `main_system.md`

**Files:**
- Modify: `tools/plan_mode.py:11-17,41-45`
- Modify: `.dagi/prompts/main/main_system.md:31-41`

- [ ] **Step 1: Strip `EnterPlanModeTool.description`**

In `tools/plan_mode.py`, replace lines 11-17:

```python
    description = (
        "Enter plan mode. Restricts tools to read-only plus plan-file write. "
        "Creates a git branch for the task."
    )
```

- [ ] **Step 2: Strip `ExitPlanModeTool.description`**

In `tools/plan_mode.py`, replace lines 40-45:

```python
    description = "Exit plan mode. Restores full tool access."
```

- [ ] **Step 3: Remove Autonomous Plan Mode section from `main_system.md`**

In `.dagi/prompts/main/main_system.md`, replace lines 31-41 (the full "## Autonomous Plan Mode" section including the numbered list) with:

```markdown
## Planning

Use the `plan` skill for tasks requiring structured planning. See `.dagi/skills/plan/SKILL.md`.
```

- [ ] **Step 4: Run existing tests to ensure nothing breaks**

Run: `conda run -n dagi pytest tests/ -v --tb=short`
Expected: all existing tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/plan_mode.py .dagi/prompts/main/main_system.md
git commit -m "refactor: strip planning prompts from tools and system prompt"
```

---

### Task 4: [ ] Create `grilling` skill (replaces `grill-me`)

**Files:**
- Create: `.dagi/skills/grilling/SKILL.md`
- Delete: `.dagi/skills/grill-me/SKILL.md`

- [ ] **Step 1: Create `.dagi/skills/grilling/SKILL.md`**

```markdown
---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
triggers: grill, /grill, /grilling, stress-test this, grill my plan, grill my idea
---

# grilling

Interview me relentlessly about every aspect of this until we reach a shared
understanding. Walk down each branch of the decision tree, resolving dependencies
between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before
continuing. Asking multiple questions at once is bewildering.

If a fact can be found by exploring the environment (filesystem, tools, etc.),
look it up rather than asking me. The decisions, though, are mine — put each one
to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## Closing

When shared understanding is reached, produce a closing summary covering:
- what was tested
- what held up under pressure
- what was weak, missing, or unresolved
- concrete actions before proceeding

Then chain: **invoke `plan` next.**
```

- [ ] **Step 2: Delete `.dagi/skills/grill-me/SKILL.md`**

Remove the file `.dagi/skills/grill-me/SKILL.md`.

- [ ] **Step 3: Verify the skill loads**

Run: `conda run -n dagi python -c "from agent.skill_loader import SkillLoader; from pathlib import Path; skills, errs = SkillLoader().load_all_with_errors([Path('.dagi/skills')]); print([s.name for s in skills]); print(errs)"`
Expected: output includes `'grilling'`, does not include `'grill-me'`, no errors

- [ ] **Step 4: Commit**

```bash
git add .dagi/skills/grilling/SKILL.md
git rm .dagi/skills/grill-me/SKILL.md
git commit -m "feat: replace grill-me with grilling skill (Mode A only)"
```

---

### Task 5: [ ] Create `to-spec` skill

**Files:**
- Create: `.dagi/skills/to-spec/SKILL.md`

- [ ] **Step 1: Create `.dagi/skills/to-spec/SKILL.md`**

```markdown
---
name: to-spec
description: Turn the current conversation into a spec and save it to the plan directory — no interview, just synthesis of what has already been discussed.
disable-model-invocation: true
---

# to-spec

This skill takes the current conversation context and codebase understanding and
produces a spec. Do NOT interview the user — just synthesize what you already know.

## Process

1. Explore the repo to understand the current state of the codebase, if you haven't
   already. Use the project's domain glossary vocabulary throughout the spec, and
   respect any ADRs in the area you're touching.

2. Sketch out the seams at which you're going to test the feature. Existing seams
   should be preferred to new ones. Use the highest seam possible. If new seams are
   needed, propose them at the highest point you can. The fewer seams across the
   codebase, the better — the ideal number is one.

   Check with the user that these seams match their expectations.

3. Write the spec using the template below, then save it to the active plan
   directory: `.dagi/plans/<plan_dir>/spec.md`.

## Spec Template

### Problem Statement

The problem that the user is facing, from the user's perspective.

### Solution

The solution to the problem, from the user's perspective.

### User Stories

A LONG, numbered list of user stories. Each user story should be in the format of:

1. As an \<actor\>, I want a \<feature\>, so that \<benefit\>

This list of user stories should be extremely extensive and cover all aspects of the
feature.

### Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Do NOT include specific file paths or code snippets. They may end up being outdated
very quickly.

Exception: if a prototype produced a snippet that encodes a decision more precisely
than prose can (state machine, reducer, schema, type shape), inline it within the
relevant decision and note briefly that it came from a prototype. Trim to the
decision-rich parts — not a working demo, just the important bits.

### Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not
  implementation details)
- Which modules will be tested
- Prior art for the tests (i.e. similar types of tests in the codebase)

### Out of Scope

A description of the things that are out of scope for this spec.

### Further Notes

Any further notes about the feature.
```

- [ ] **Step 2: Verify the skill loads**

Run: `conda run -n dagi python -c "from agent.skill_loader import SkillLoader; from pathlib import Path; skills, errs = SkillLoader().load_all_with_errors([Path('.dagi/skills')]); print([s.name for s in skills]); print(errs)"`
Expected: output includes `'to-spec'`, no errors

- [ ] **Step 3: Commit**

```bash
git add .dagi/skills/to-spec/SKILL.md
git commit -m "feat: add to-spec skill for conversation-to-PRD synthesis"
```

---

### Task 6: [ ] Create `plan` skill

**Files:**
- Create: `.dagi/skills/plan/SKILL.md`

- [ ] **Step 1: Create `.dagi/skills/plan/SKILL.md`**

```markdown
---
name: plan
description: Full planning lifecycle — enters plan mode, generates spec from conversation, explores codebase, writes implementation plan, gets approval, exits plan mode. Invoke directly via /plan or chained from grilling.
triggers: /plan, plan this, create a plan
---

# plan

This skill owns the planning phase: entering plan mode, generating a spec,
exploring the codebase, writing the implementation plan, and getting approval.

## Direct invocation

`/plan` can be invoked directly when requirements are already clear (skipping
`grilling`). When chained from `grilling`, the conversation context from the
interrogation is already available — no re-gathering needed.

## Process

### Step 1 — Enter Plan Mode

Call `enter_plan_mode(mode, task_summary)` where:
- `mode`: `"interactive"` when invoked by the user; `"autonomous"` when DAGI
  initiates internally
- `task_summary`: a short kebab-case slug derived from the task description
  (e.g. `"fix-login-bug"`)

This is a pure infrastructure call — it enters plan-mode state, creates a git
branch, restricts tools to read-only plus plan-file write, and switches to the
advanced model.

### Step 2 — Generate Spec

Invoke `skill("to-spec")`. This synthesizes the conversation context into a spec
(Problem Statement, Solution, User Stories, Implementation Decisions, Testing
Decisions, Out of Scope) and saves it to `.dagi/plans/<plan_dir>/spec.md`.

Wait for the user to confirm the test seams before proceeding.

### Step 3 — Explore Codebase

Call `spawn_explore_files_subagent(...)` with a task informed by the spec's
Implementation Decisions and Testing Decisions sections. The subagent maps
relevant files, architecture, and patterns. Read its handoff when it returns.

### Step 4 — Write Implementation Plan

Write `plan.md` in the plan directory. Use the current plan format:

- **Context** — why this change is needed
- **Approach** — high-level strategy and key decisions
- **Files to Modify** — exact paths
- **Subtasks** — each with:
  - `### Subtask N: [ ] <name>` (status marker in heading)
  - **Goal:** one sentence
  - **Requirements:** bulleted list
  - **Acceptance Criteria:** bulleted list
  - **Test snippets:** key assertions and approach hints (not full test code — the
    main agent expands these into full test files at execution time)
  - Each subtask's execution protocol: write tests → worker implements → review
    grades
- **Notes** — findings from exploration, traps to avoid
- **Verification** — how to verify end-to-end

### Step 5 — Show and Approve

1. Call `show_plan` to render the plan.
2. Call `ask_user("Approve this plan? Type [approve] to proceed, describe changes
   to modify, or [cancel] to abort.")`
   - **approve** → proceed to Step 6
   - **modify** → edit plan.md, go back to Step 5
   - **cancel** → call `exit_plan_mode`, stop

### Step 6 — Exit Plan Mode

Call `exit_plan_mode(summary)` to restore full tools.

### Step 7 — Chain to Execution

Invoke `skill("dagi-execute")` or tell the user: "Plan approved and saved. Invoke
`dagi-execute` to begin implementation."
```

- [ ] **Step 2: Verify the skill loads**

Run: `conda run -n dagi python -c "from agent.skill_loader import SkillLoader; from pathlib import Path; skills, errs = SkillLoader().load_all_with_errors([Path('.dagi/skills')]); print([s.name for s in skills]); print(errs)"`
Expected: output includes `'plan'`, no errors

- [ ] **Step 3: Commit**

```bash
git add .dagi/skills/plan/SKILL.md
git commit -m "feat: add plan skill for planning lifecycle orchestration"
```

---

### Task 7: [ ] Create `dagi-execute` skill and delete `plan-work-review`

**Files:**
- Create: `.dagi/skills/dagi-execute/SKILL.md`
- Delete: `.dagi/skills/plan-work-review/SKILL.md`

- [ ] **Step 1: Create `.dagi/skills/dagi-execute/SKILL.md`**

```markdown
---
name: dagi-execute
description: Execute an approved plan via the work-review cycle — main agent writes tests, worker subagent implements, review subagent grades, main agent commits. Handles retry logic, escalation, completion, and branch cleanup.
triggers: /execute, execute plan, start execution
---

# dagi-execute

Execute the approved plan subtask by subtask. Delegate implementation to worker
subagents and evaluation to review subagents. The main agent writes tests and
commits.

## Prerequisites

- A plan file must be active (`config.active_plan_file` is set)
- The plan must have been approved and plan mode exited
- Read the plan file in full before starting

## Per-Subtask Cycle

For each `[ ] pending` subtask in the plan:

### Step 1 — Write Tests

Before spawning the worker, write the test file(s) for this subtask:
- Read the subtask's **Acceptance Criteria** and **Test snippets**
- Expand them into full test files
- Save to `.dagi/plans/{plan_dir}/tests/`
- Edit `plan.md` to fill in the subtask's `#### Tests` subsection with test file
  paths and a one-line description of what each test verifies
- Do NOT pass test paths to the worker — tests are a hidden oracle for review only

### Step 2 — Spawn Worker

Edit `plan.md` to change the subtask heading marker from `[ ]` to `[~]`
(in-progress).

Call `spawn_worker_subagent(subtask_name, custom_instructions)`. The tool
automatically injects plan context and subtask details. Keep the returned handoff
path for Step 3.

### Step 3 — Spawn Review

Call `spawn_review_subagent(subtask_name, worker_handoff_path, unit_test_paths)`.
The tool automatically injects plan context and the subtask block (including
Tests section). Read the returned review report.

### Step 4 — Evaluate and Decide

Pass/fail is determined by the review subagent's verdict — not your own judgment.

**If ESCALATED:** The subagent raised a blocking question (tool result starts with
`[worker escalated]` or `[review escalated]`).
- Read the question in full
- Decide the answer yourself if you can — you have full repo access and
  conversation context the subagent doesn't
- Only call `ask_user` for genuine product decisions
- Re-spawn the same subagent type with the answer via `custom_instructions`
- This does NOT consume a retry attempt — go back to Step 2 or 3

**If PASS:**
- Edit `plan.md` and mark the subtask `[x] complete`
- `git add` the files this subtask touched, then `git commit` with a message
  summarizing the subtask
- Append a PASS entry to `cycle_log.md` in the plan directory
- Update the `## Notes` section of `plan.md` with salient findings
- Proceed to the next subtask

**If FAIL:**
- Append a FAIL entry to `cycle_log.md` with: verdict, artifact file names,
  issue summary, action taken
- Update `## Notes` in `plan.md` with salient findings
- Decide retry strategy:
  - **Worker fell into a trap** (plan is sound): retry with augmented
    custom_instructions
  - **Plan is flawed** (subtask requirements wrong): edit the subtask in plan.md,
    then retry

**If 2 attempts exhausted** (1 initial + 1 retry; escalations free):
- Mark the subtask `[!] failed` in plan.md
- Stop the cycle
- Present structured escalation report:
  - Summary of all attempt handoff/review artifacts
  - Root cause diagnosis
  - Proposed solutions
- Wait for user guidance before continuing

## Completion

Once every subtask is resolved (all markers `[x]` or `[!]`):

1. Call `complete_plan()`
2. Invoke `skill("update-project-context")`
3. Commit context updates
4. Run `git checkout <previous_branch>` — the branch the user was on before plan
   mode (stored in `config.previous_branch`). Do NOT merge, force-push, or delete
   the task branch.
5. Report summary:
   - Branch name
   - Number of commits and files changed
   - Reminder that the branch is ready for user review and merge

## cycle_log.md Format

Maintain `cycle_log.md` in the plan directory. Append one block per attempt:

```
## Subtask N: <name>
### Attempt N — PASS/FAIL
- Worker: .dagi/handoffs/worker_<id>.md
- Review: .dagi/handoffs/review_<id>.md
- Issue: <one-line summary, or "None">
- Action: <what you did next, or "Subtask complete">
```
```

- [ ] **Step 2: Delete `.dagi/skills/plan-work-review/SKILL.md`**

Remove the file `.dagi/skills/plan-work-review/SKILL.md`.

- [ ] **Step 3: Verify skills load correctly**

Run: `conda run -n dagi python -c "from agent.skill_loader import SkillLoader; from pathlib import Path; skills, errs = SkillLoader().load_all_with_errors([Path('.dagi/skills')]); print([s.name for s in skills]); print(errs)"`
Expected: output includes `'dagi-execute'`, does not include `'plan-work-review'`, no errors

- [ ] **Step 4: Commit**

```bash
git add .dagi/skills/dagi-execute/SKILL.md
git rm .dagi/skills/plan-work-review/SKILL.md
git commit -m "feat: add dagi-execute skill, remove plan-work-review"
```

---

### Task 8: [ ] Full integration verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `conda run -n dagi pytest tests/ -v --tb=short`
Expected: all tests PASS

- [ ] **Step 2: Verify all four skills load**

Run: `conda run -n dagi python -c "from agent.skill_loader import SkillLoader; from pathlib import Path; skills, errs = SkillLoader().load_all_with_errors([Path('.dagi/skills')]); names = sorted(s.name for s in skills); print(names); assert 'grilling' in names; assert 'plan' in names; assert 'to-spec' in names; assert 'dagi-execute' in names; assert 'grill-me' not in names; assert 'plan-work-review' not in names; print('All skill assertions passed')"`
Expected: "All skill assertions passed"

- [ ] **Step 3: Verify `enter_plan_mode` description is stripped**

Run: `conda run -n dagi python -c "from tools.plan_mode import EnterPlanModeTool; t = EnterPlanModeTool.__new__(EnterPlanModeTool); print(repr(t.description))"`
Expected: short description without "Pass mode='interactive' when..." guidance

- [ ] **Step 4: Verify `main_system.md` has no Autonomous Plan Mode section**

Run: `conda run -n dagi python -c "from pathlib import Path; t = Path('.dagi/prompts/main/main_system.md').read_text(); assert 'Autonomous Plan Mode' not in t; assert '## Planning' in t; print('System prompt verified')"`
Expected: "System prompt verified"

- [ ] **Step 5: Commit (if any fixups needed)**

Only if prior steps required fixes. Otherwise skip.
