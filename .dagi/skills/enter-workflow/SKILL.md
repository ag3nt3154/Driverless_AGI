---
name: enter-workflow
description: Own the task lifecycle, stage transitions, approvals, and closure.
---

# Ownership and entry

Only the main agent runs this lifecycle. `enter-workflow` owns stage transitions,
user approvals, active-plan association, and final closure. `grill-me`, `write-spec`,
`write-plan`, and `deliver` return their result here when running as stages; they do not
launch one another.
Loading a skill is not spawning an agent or ending a turn. Continue the owning
workflow after reading its result; use `ask_user` when user input is required.

- **Normal entry:** follow the request path below.
- **Planning-only request:** follow the architectural planning stages even for
  a bounded request, then stop after plan approval, attachment, and approval wiki-add.
  Do not invoke `deliver`; planning approval is not implementation authorization.
- **Direct `/deliver`:** the deliver skill routes here once when invoked without this
  owner. Call `check_active_plan()`. If the associated plan matches the request and
  has user approval and execution authorization, reuse it at **Plan handoff** below.
  Otherwise resolve the missing approval or follow the architectural planning stages,
  even for a bounded request explicitly submitted to `/deliver`. Do not replace a
  different associated plan without asking the user.

Before this overall substantive task, invoke `wiki-query` unless it already ran in
this context. Share the lookup across all stages. Retry failure once, then block
dependent work. An initialized empty wiki permits project investigation.

When a stage returns a blocker or a changed requirement, resolve it here and revisit
only the affected stage. Preserve already settled decisions. Call `write-plan` directly
for the plan-writing stage; a standalone invocation writes the artifact without launching
the lifecycle or authorizing implementation.

# Steps
1. Classify the request and say the classification out loud — "this looks bounded, so I'll present a short design here rather than write a spec" — so your user can override it:
   - **Query** — a feasibility question ("can we...", "is it possible...",
   "quick and dirty is fine") whose output is an answer, not code you
   keep. Present the question and what you'll try in 2-3 sentences, get
   a nod, then find out as cheaply as correctness allows. No design
   doc, no spec file. Report findings as a recommendation; anything you
   built stays labeled throwaway.
   - **Bounded** — a well-scoped change to code that already exists in
   this repo: a new flag, a small endpoint, a one-file fix.
   Understanding the kind of app is not enough — bounded means the flow
   you are changing is already here to read. If there is no existing
   flow to change, the task is not bounded. 
   - **Architectural** — new projects, new subsystems, changes that
   restructure how components fit together or alter interfaces others
   depend on.

   <HARD-GATE>
   Do NOT invoke any implementation skill, write any code, scaffold any
   project, or take any implementation action until you have told your
   user what you intend and they have approved it. This applies
   to EVERY task on EVERY path below — the ceremony scales with the task;
   the approval gate never does.
   </HARD-GATE>

2. If the request is a **query**, this is the user asking for an answer to a question.
   No code changes necessary. You should clarify with the user what the user is asking
   and then provide an answer based on available information.
  1. **Explore project context** — enough to frame the probe
  2. **Clarify question from user** — Make sure that you understand what the user is
    asking. If it is a complex query covering multiple files, produce a probe plan in 2-3 sentences
  3. **Get approval** — a nod is enough
  4. **Investigate** — as cheaply as correctness allows. You may write and run scripts 
    to investigate and gather the correct information, but you should label anything 
    built as `tmp`.
  5. **Report findings** — report findings based on user's ask. You should remove the
    `tmp` scripts that you built during the investigation.

3. If the request is **bounded**, this is a simple and bounded change. No need to open
  a new `git` branch. You should clarify with the user what the user is asking and then
  implement the requested changes, committing the changes to `git` after every 
  completed step.
  1. **Explore project context** — check files, docs, recent commits
  2. **Ask clarifying questions** — invoke the `grill-me` skill
  3. **Present short design in chat** — approach, files touched, testing
  4. **Get approval** — STOP and wait for an explicit yes
  5.  **Implement** — proceed with the normal development workflow (TDD applies); no plan document; commit to `git` after every completed step.

4. If the request is **Architectural**, this is a complex change, such as building a new feature. You should clarify with the user what the user is asking, create the implementation plan, and then begin implementation. Since this is a complex change, you should create a new `git` branch for this change, which will be merged back to the original branch once everything is done.
  1.  **Explore project context** — check files, docs, recent commits
  2.  **Ask clarifying questions** — invoke the `grill-me` skill
  3.  **Propose 2-3 approaches** — with trade-offs and your recommendation
  4.  **Present design** — in sections scaled to their complexity, get user approval after each section
  5. **Start git workflow** — create a new task branch `dagi/<task-name-slug>` and `git checkout` to it.
  6.  **Write design doc** — invoke `write-spec` skill. Write the spec file to `wiki/plans/YYYY-MM-DD-<task-name-slug>/spec.md`.
  7.  **User reviews written spec** — show the spec file to the user and ask user to review. When the user approves, add and commit the spec file to the task branch.
  8.  **Create implementation plan** — invoke `write-plan` to write
      `wiki/plans/YYYY-MM-DD-<task-name-slug>/plan.md`, then receive its path and readiness.
  9.  **User reviews implementation plan** — present the returned file with `show_file`
      where available, otherwise the normal response mechanism. Call `ask_user` with
      `no_timeout=true` for explicit approval, requested edits, or cancellation.
      For edits, call the writer again and repeat review. On cancellation, stop.
      Commit approved artifacts only within the user's Git authorization.
  10. **Plan handoff** — complete the handoff below. Planning-only requests stop there.
  11. **Implement** — invoke `deliver` as the execution stage of this workflow. Read its
      result and resolve blockers; follow existing task-scoped commit authorization.
  12. **Close** — after verified delivery, run **Closure** below.

## Plan handoff

1. Call `set_active_plan(path)` with the approved plan and confirm association using
   `check_active_plan()`. Attachment alone is not user approval or execution authority.
2. Preserve the independent plan review from the previous delivery lifecycle. Call
   `review_work` with the plan path, request and design decisions, and criteria covering
   completeness, checkable task acceptance criteria, consistency, and implementation traps.
   Read the handoff. On `ESCALATE`, revise through `write-plan` and repeat review; obtain
   renewed user approval for material changes. Record the accepted review in plan Notes.
   Reuse review evidence only when it applies to the current plan.
3. Invoke `wiki-add` with selected approved decisions/user choices unless successful
   evidence already covers this plan. Read the handoff and record success in plan Notes.
   Retry once; continued failure blocks implementation and leaves the plan associated.
4. For planning-only entry, report the approved plan is ready and return without delivery.
   Otherwise require execution authorization and continue to the implementation stage
   (architectural Step 11), then Closure. Reusing a plan does not restart branch creation.

## Closure

`deliver` returns implementation status, verification results, final review, and unresolved
items. A blocked or interrupted stage leaves the plan associated; do not claim completion.

After successful verification and final review:

1. Invoke `wiki-add` with actual implementation, verification evidence, and completion
   status. Read the handoff and record success in plan Notes. Retry failure once; on
   continued failure report the implementation status but keep the workflow incomplete
   and plan associated. For partial writes, have the writer reread before retrying.
2. Check `update-project-context`.
3. Call `set_active_plan(null)` to detach. Preserve the plan document on disk, then
   present the verified outcome through the normal final-response mechanism.

The `do-TDD` and `merging-git-branch` drafts are not integrated in this migration step.
This closure preserves the existing report/detach behavior; it does not authorize a merge.
