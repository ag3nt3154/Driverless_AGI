---
name: enter-workflow
description: Own the task lifecycle, stage transitions, approvals, and closure.
---

# Ownership and entry

Only the main agent runs this lifecycle. `enter-workflow` owns stage transitions,
user approvals, active-plan association, and final closure. `grill-me`, `write-spec`,
`write-plan`, `deliver`, and `merging-git-branch` return their result here as stages; they do not
launch one another.
Loading a skill is not spawning an agent or ending a turn. Continue the owning
workflow after reading its result; use `ask_user` when user input is required.

- **New task:** check for an unfinished workflow in the conversation and call
  `check_active_plan()` before starting or replacing planned work. If another task is
  unfinished, ask whether to continue it or switch; preserve its files and progress.
  An explicit switch authorizes the switch, not deletion or approval of the old work.
  Otherwise follow the request path below.
- **Planning-only request:** follow the architectural sequence even for a bounded
  request, then stop after approval, the spec/plan commit, and plan attachment.
  Do not invoke `deliver`; planning approval is not implementation authorization.
- **Direct `/deliver`:** the deliver skill routes here once when invoked without this
  owner. Use the continuation routing below for existing work. With no existing task,
  follow the architectural sequence even for a direct delivery request.

## Continuation routing

Apply this before the numbered Steps for answers, corrections, status requests, explicit
resume, or restored/compacted context. Do not reclassify a continuation as a new task.

1. Identify the task, current stage, and pending question from the conversation/checkpoint.
   On resume or compaction, or before acting on plan state, call `check_active_plan()`.
   Read the returned plan and compare its identity and branch with the checkpoint.
2. No active plan does not mean no workflow: grilling, spec review, and bounded work may
   precede attachment. Recover from the retained conversation and known artifact paths.
   A missing/unreadable plan, unexplained branch mismatch, or conflicting evidence blocks
   dependent mutations; inspect known evidence and ask a targeted question if unresolved.
   Never infer approval from a plan's existence or reattach just to hide a mismatch.
   After a confirmed merge into the recorded target, that branch mismatch is explained:
   leave the association unchanged while finishing closure, then detach normally.
3. Bind an answer only to the pending question and the artifact/scope it concerned.
   Preserve valid prior approval; ask again only when it is missing, ambiguous, or the
   relevant scope changed. Use `ask_user(..., no_timeout=true)` for approval gates.
   Silence, timeout defaults, and automated reminders are not user approval.
4. Continue at the first unfinished stage shown by evidence:
   - Exploration/grilling or approval: continue that stage and its pending question.
   - Bounded implementation/review: resume TDD or review on the current branch. No plan
     association exists; recover scope from the inline plan in conversation context.
   - Spec/plan writing/review: reuse artifacts; complete missing review, joint approval,
     document-commit, or attachment gates before implementation.
   - Approved planning-only work: remain stopped unless execution is now authorized.
   - Implementation: invoke `deliver` for pending tasks after its entry checks; an accepted
     but uncommitted subtask resumes at its commit, not at its worker.
   - Verification: invoke `deliver` at integrated verification, without rerunning accepted tasks.
   - Awaiting merge/keep or closing: resume Closure. If a merge may already have happened,
     inspect Git state before repeating it; finish only missing verification/documentation.
5. Answer status questions from current evidence without changing the stage. Corrections
   invalidate only affected work, review, and approval. Before repeating any interrupted
   branch creation, commit, or merge, inspect its actual result; a missing reply is not failure.

## Workflow checkpoint

At stage transitions and before asking the user to decide, retain a compact checkpoint:
task identity and scope; current stage and next action; artifact paths and task/parent
branches and starting commit; pending question and its approval scope; completed gates,
document/subtask commit evidence, and blockers.
Record it in existing plan Notes/Next Action when a plan exists. Before a plan exists,
include it in the pending question or handoff context; do not create another state file.
Treat it as recorded evidence to reconcile, not permission to override later user choices.
The active-plan sidecar records an association, not stage progress or approval.

When a stage returns a blocker or a changed requirement, resolve it here and revisit
only the affected stage. Preserve already settled decisions. Call `write-plan` directly
for the plan-writing stage; a standalone invocation writes the artifact without launching
the lifecycle or authorizing implementation.

## Memory checkpoint (task start) — required

Before each overall substantive project task (including a read-only query), load
`skill("memory-query")` and search the central memory wiki: first `projects/<slug>/` (the
`[MEMORY]` pointer names it) for the task's keywords, then `knowledge/`, and list
`projects/<slug>/todo/`. State what you found — cited paths, or "no wiki entries". Missing or
empty results never block work. Reuse this lookup through chained stages, not once per subtask.

Advisory triggers during the task: before debugging any error, grep the exact error text
across the wiki; before a design choice, search for earlier decisions on the same thing.

Task specs and plans live in this repo at `wiki/tasks/YYYY-MM-DD_<task>/`; create
`wiki/tasks/` if it is missing. That folder holds task artifacts only, never knowledge.

# Steps
1. Classify the request and state it so the user can override it. Bounded changes use
   proportionate exploration, specs, and plans; both implementation paths use the same gates:
   - **Query** - intent is a read-only answer or investigation. Answer without a
   preliminary approval or nod; clarify only consequential ambiguity. Classify by intended
   outcome, not phrases such as "can you": a request to make a change is implementation.
   Ordinary casual conversation stays outside this lifecycle.
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
   to implementation on both paths below. Read-only queries and creating an empty
   `wiki/tasks/` folder do not require this approval.
   </HARD-GATE>

2. For a **query**, inspect enough context to answer accurately and report findings.
   No branch, spec, plan, or preliminary permission is required. Any temporary probe must
   remain explicitly disposable and within the authorized investigation scope. A later
   request to keep or implement a change enters the matching implementation sequence.

3. For **bounded** or **architectural** implementation, follow the matching sequence
   below. Both paths share explore/grill and the approval gate. Bounded work stays on the
   current branch with no spec/plan documents; architectural work gets a dedicated branch,
   written spec and plan, and the full deliver/merge pipeline.

   If hidden complexity surfaces mid-bounded-work, stop and upgrade to architectural.

## Bounded sequence

1. **Explore and grill.** Inspect project context and invoke `grill-me`. Resolve intent,
   scope, constraints, and meaningful alternatives until shared understanding is reached.
2. **Check uncommitted work.** Run `git status` and identify staged, unstaged, and untracked
   work. Reuse a recorded user decision to preserve existing changes. Proceed when task
   changes can be isolated safely; do not demand a clean tree. Ask only for an unresolved
   ownership or handling decision. Never silently stash, discard, or include unrelated work.
3. **Present inline plan.** Summarize the change in chat: what files are affected, the
   approach, and how it will be tested. This is the plan — no document, no spec file.
4. **Ask approval.** Use `ask_user(..., no_timeout=true)`. Wait for an explicit yes.
   This approval covers implementation and reviewed commits on the current branch.
   No per-subtask approval follows.
5. **Implement with TDD.** Load `skill("do-tdd")` and implement directly on the current
   branch, following the red/green/refactor cycle. The main agent implements directly
   (no worker subagent needed for bounded work, though one may be used).
6. **Review.** Call `review_work` with the full diff, acceptance criteria from the inline
   plan, and test commands. On ESCALATE, repair and re-review. On PASS, proceed to commit.
7. **Commit.** Stage and commit the accepted changes with a Conventional Commit message.
   Verify the commit succeeded; reconcile interrupted commits from history before retrying.
8. **Close bounded work.** The owner performs proportionate integrated verification and
   final review, runs the task-end memory checkpoint and `update-project-context`, and
   reports the verified result. Do not invoke `deliver` or manufacture a branch/merge offer.

## Architectural sequence

1. **Explore and grill.** Inspect project context and invoke `grill-me`. Resolve intent,
   scope, constraints, and meaningful alternatives until shared understanding is reached.
2. **Check uncommitted work.** Run `git status` and identify staged, unstaged, and untracked
   work. Reuse a recorded user decision to preserve existing changes. Proceed when task
   changes can be isolated safely; do not demand a clean tree. Ask only for an unresolved
   ownership or handling decision. Never silently stash, discard, or include unrelated work.
3. **Ask to create the branch.** Present the understood scope, parent branch, proposed
   `dagi/<task>` branch, and artifact directory `wiki/tasks/YYYY-MM-DD_<task>/`. The
   `<task>` slug is the same in both. Honor an explicit applicable project branch-prefix
   override and record the actual branch once; `dagi/` is only the default. Ask with
   `ask_user(..., no_timeout=true)` to create
   and check out that branch. This approval permits branch setup and drafting, not
   implementation or merging.
4. **Create the branch and artifact directory.** Record parent branch, starting commit,
   actual approved task branch, and the artifact directory
   (`wiki/tasks/YYYY-MM-DD_<task>/`) before switching. Create and check out the approved
   branch; create the artifact directory; verify success. Reuse these values on
   continuation.
5. **Write spec and plan.** Pass the recorded artifact directory to both writers.
   Invoke `write-spec` (saves `spec.md`), then `write-plan` (saves `plan.md`) in that
   directory. Carry the Git checkpoint into plan Notes. The writers return artifacts;
   do not ask for a separate spec approval or commit either document yet. Run the plan
   review below.
6. **Ask to approve both.** Show spec.md and plan.md together. Ask explicitly to approve
   both documents, commit them to the task branch, start implementation, and let the main
   agent commit each completed/reviewed subtask and task verification records. Use
   `ask_user(..., no_timeout=true)` and wait. Revisions return to the affected writer and
   review before asking again. Cancellation preserves the branch/artifacts without work.
   If a decline does not say revise or cancel, clarify that choice; do not start work.
   For planning-only requests, ask only to approve and commit the documents; no execution
   or implementation-commit permission is implied.
7. **Record approval and commit.** Run the approval record below. Stage only the
   approved spec and plan, inspect the staged diff, and commit them together with the
   message `plan(<task>): approve spec and plan` (where `<task>` is the recorded task
   slug). Inspect its committed contents and history, not just the subject. A subject
   is not user authorization. Verify the commit before advancing; record its ID in the
   continuation
   checkpoint. Do not include unrelated staged work in this commit.
8. **Attach and deliver.** Associate the approved plan using `set_active_plan(path)` and
   confirm with `check_active_plan()`. Planning-only work stops here. Otherwise invoke
   `deliver` with approval, document-commit evidence, and task-scoped commit authority.
9. **Finish and close.** After all subtasks are reviewed/committed and integrated
   verification succeeds, run Closure. The final merge/keep question remains separate.

## Plan review and approval checkpoint

Before presenting the spec and plan for approval, call `review_work` with the plan path,
request and spec context, and criteria for completeness, checkable acceptance criteria,
consistency, and implementation traps. Read the handoff. Revise through the writers on
`ESCALATE` and repeat until accepted. Record review evidence in plan Notes.

### Approval record

After explicit inline-plan or joint spec/plan approval, record actual user evidence and
scope separately from document-commit evidence (in plan Notes, or the conversation for
bounded work): approved artifact/version, execution and commit authority, and planning-only
limits. Never infer permission from a filename, status, plan association, review PASS, or
commit subject. Nothing is written to the memory wiki at approval; approved decisions are
filed at task end.

### Memory checkpoint (task end) — required

After verification, load `skill("memory-add")` and file, inline: approved decisions (choice,
rejected alternatives, rationale), errors fixed (verbatim error text, cause, fix), new todos,
ideas, and reusable knowledge. Delete completed todos after filing their lessons. State the
wiki paths written. A failed write is reported honestly; it does not undo verified work.

Approval and review evidence apply only to their reviewed scope; material later changes
require renewed approval before committing or work.

On resume, complete only missing gates. A plan file or association alone proves neither
approval nor a successful document commit. Verify actual Git history before retrying a
commit, then continue at the first unfinished stage without recreating the branch.

## Git handling

The main agent owns staging and commits, including while running the `deliver` stage.
Workers return changes and evidence. Branch approval, spec/plan plus implementation-commit
approval, and merge approval are distinct; record their scopes in the checkpoint.

- Inspect current branch, staged/unstaged changes, and untracked files before setup.
  Identify existing work and preserve it. If switching would carry unrelated work, paths
  contain mixed ownership, or the parent is unclear, reuse recorded handling decisions;
  ask only if safe isolation or authority remains unresolved. Never silently
  stash, discard, reset, or include existing changes in task commits.
- Record the actual parent and starting commit; do not assume main or infer it from an
  upstream. Honor recorded explicit project branch-prefix overrides. Detached HEAD or a
  branch-name collision needs an explicit choice. Reuse an
  existing task branch only when evidence ties it to this task; otherwise propose a new
  name. Never reset an existing branch to make setup succeed.
- Before each commit, confirm the task branch and inspect both the task diff and the
  entire staged diff. Stage explicit task files/hunks. If unrelated content is already
  staged, isolate task staging without altering that work when safely possible. Ask only
  when ownership or safe separation remains unresolved; reuse recorded user choices.
- Commit only approved documents or accepted subtasks, not individual red/green steps.
  Verify each commit and retain its ID in the checkpoint. A failed/interrupted commit
  leaves a commit-pending stage; inspect history before retrying, without rerunning accepted
  implementation. No routine per-subtask or per-commit user approval is required. If history
  and the committed diff prove the expected commit succeeded,
  reconcile stale plan/checkpoint markers and its commit ID, then continue without another
  commit. If the result is uncertain, resolve it before proceeding. Report unchanged/no-op
  subtasks instead of manufacturing empty commits.
- Task-scoped verification/progress documentation can be committed on the task branch
  under the same implementation approval before the merge offer. That permission does
  not extend to new commits on the parent after merging, pushing, or deleting anything.
- A commit cannot contain its own final ID. Record verified IDs and completion markers
  after committing; include those updates in the next task commit or a final verification
  record commit. Keep that final commit's ID in the conversation checkpoint/Git history;
  do not create an endless chain of commits solely to record each preceding ID.

## Closure

`deliver` returns implementation status, verification results, final review, and unresolved
items. A blocked or interrupted stage leaves the plan associated; do not claim completion.

After successful verification and final review:

1. Record verified delivery in plan Notes. Commit remaining task-owned verification records
   on the task branch under the recorded commit authority, verifying the staged diff and
   resulting commit. This precedes the merge offer; unresolved commit issues block finishing.
   Invoke `skill("merging-git-branch")` with
   the task/parent branch names, plan path, and verification evidence in context.
   Keep the plan associated while awaiting the explicit merge/keep choice.
   Record the returned `merged`, `kept`, or `blocked` outcome and evidence in the plan
   in the appropriate checkout (the target checkout after a merge). A blocker
   leaves closure incomplete and the plan associated. Keeping the branch is successful
   finishing, not a failed merge. Resume an unfinished closing stage here using current
   evidence; do not rerun completed implementation just to obtain the finishing decision.
2. Run the task-end memory checkpoint and check `update-project-context`. After a merge,
   use the corresponding plan in the target
   checkout when recording closure; do not edit a stale source worktree or reattach the
   plan merely because switching to the approved target produces a branch mismatch.
   Report any final documentation changes still uncommitted; do not silently commit them.
3. Call `set_active_plan(null)` to detach only after finishing and documentation succeed.
   Preserve the plan document on disk, then present the verified outcome through the
   normal final-response mechanism.

The finishing skill offers only local merge or keep-as-is. Merge permission is separate
from design/implementation approval; pushing and cleanup are outside this workflow.
