---
name: enter-workflow
description: Own coding-task planning, approvals, execution, recovery, and closure; resume existing stages without restarting. Use context-only entry for substantive project questions, not casual conversation.
---

# Workflow owner

Only the main agent runs this lifecycle. Writers, grilling, delivery, and branch finishing
return their results here. Reading a skill refreshes its instructions; it does not spawn an
agent, restart the task, erase approval, or end a turn. Respect the host's current mode and
tool permissions; a skill cannot switch collaboration modes or invent unavailable tools.

Load sibling skills through their discovered SKILL.md paths. This workflow needs `grill-me`,
`write-spec`, `write-plan`, `deliver`, `do-tdd`, `merging-git-branch`, `wiki-query`, `wiki-add`,
and `update-project-context`. Missing required capabilities block only dependent work;
report the missing capability rather than pretending it ran.

## Entry and context

1. Identify whether the message is new work, an answer, a correction, a status question,
   or a continuation. Preserve an unfinished task unless the user explicitly switches it.
   An explicit standalone skill request retains that skill's scope.
2. Resolve the selected project root from the task and workspace, not a guessed nested cwd.
   For substantive project work, check `wiki/index.md`. If absent, or a prior bootstrap is
   recorded as incomplete, run
   [scripts/init_wiki.py](scripts/init_wiki.py) with `--project-root <absolute-project-root>`
   using the project's required Python environment or an available Python 3.10+ interpreter.
   This preserving bootstrap is authorized at workflow entry, before feature approval.
   An unreadable index, unsafe link, or incompatible path is an error, not a missing wiki.
   Verify the created index. Do not use another application's `/init` as a substitute.
3. Load `wiki-query` and delegate the overall-task lookup according to its protocol.
   Reuse a successful lookup across stages. An initialized empty wiki permits investigation.
   Retry a required failure once, then block dependent work. Never access personal memory
   unless explicitly requested.
4. Read relevant project instructions, source, and Git state before proposing changes.
   Ordinary conversation requires no lifecycle. For a read-only project query, investigate
   and answer without branch setup, grilling ceremony, or preliminary approval. Interpret
   requests by intended outcome: "can you fix" is an action request, not a query keyword.

## Plan identity and recovery

There is no custom active-plan service. Retain an explicit project-relative plan path in
the task checkpoint. Architectural artifacts are
`wiki/tasks/YYYY-MM-DD_<task>/spec.md` and `plan.md`; select the date/slug once and reuse them.
The main agent owns these files even though they sit inside the wiki. Wiki delegates receive
selected facts and must not read or edit task plans.

At transitions and before decisions, record task scope, stage, next action, spec/plan paths,
task/parent branches, starting commit, approval scope, pending question, review evidence,
verified commits, and blockers. Use plan Notes/Next Action when available; before planning,
keep the checkpoint in the conversation. Do not create another state file.

On continuation or compaction, reread the recorded plan and inspect Git state. Reconcile
evidence rather than trusting a status label. If the path was lost, inspect known artifacts
and the recorded branch; never choose the newest plan or a matching filename alone when
identity remains ambiguous. Missing/unreadable plan, unexplained branch mismatch, conflicting
approval, or uncertain ownership blocks dependent mutations. Ask one targeted question.
A verified merge to the recorded parent explains the branch change; close in that checkout.

Resume the first unfinished stage:
- Grilling or a pending decision: continue that question with settled choices preserved.
- Writers/review/approval: reuse artifacts; finish only missing gates.
- Bounded work: recover the inline scope and resume implementation/review without a plan file.
- Accepted task with unverified commit: inspect history, then finish only the commit or record.
- Delivery: load `deliver` at the pending subtask or integrated verification stage.
- Verified branch awaiting merge/keep: resume finishing without rerunning accepted work.
- Planning-only approval: remain stopped until execution is authorized.

Status questions do not change stage. Corrections invalidate only affected work/approval.
User approval must be grounded in the actual decision and artifact scope, recorded separately
from commits. A plan label, matching commit subject, silence, timeout, reminder, or automatic
continuation is never approval. Use an available question mechanism permitted by its real
contract, or a clear final-message question. Do not use a planning-only question tool for
permission or assume a `no_timeout` parameter exists. Wait for a real answer at a pending gate.

## Choose the implementation path

State the classification briefly so the user can correct it. Bounded work changes an existing
well-understood flow without restructuring shared contracts. New subsystems, new projects,
or material interface/architecture changes use the architectural path. Upgrade bounded work
if discovery reveals that complexity; preserve completed exploration and valid approvals.

For both paths, explore facts yourself and use `grill-me` for unresolved design decisions.
Reuse shared understanding already reached; do not repeat the interview. Inspect existing
changes and preserve them. Reuse the user's handling decision; ask only about unresolved
ownership, unsafe overlap, or branch setup. Never silently stash, discard, reset, or commit
existing work. A dirty tree alone is not a reason to demand cleanup if changes are isolatable.

### Bounded work

1. Present an inline plan with scope, affected files, approach, and meaningful verification.
2. Obtain approval for implementation and task-owned commits on the current branch. Save
   selected approved choices through `wiki-add` before implementing; reuse successful evidence.
3. Load `do-tdd`, implement, and obtain independent review using the reviewer contract in
   `deliver`. Review PASS is internal acceptance, not another user approval gate.
4. Commit accepted task changes autonomously under that approval; verify the resulting diff.
   Save actual results through `wiki-add` and check `update-project-context`. Report any final
   documentation still uncommitted. No new task branch means no invented merge offer.

### Architectural work

1. Present scope, actual parent, proposed task branch, and artifact directory. Default to
   `codex/<task>` unless an explicit project instruction chooses another prefix. Keep the
   task slug identical in the recorded branch suffix and directory. Branch setup/drafting
   approval does not authorize implementation or merge. No Git repository, detached HEAD,
   or branch collision requires a specific choice; do not initialize/reset Git implicitly.
2. After branch approval, record parent and starting commit, create/check out the approved
   branch and artifact directory, and verify. Reuse these values on continuation.
3. Load `write-spec`, then `write-plan`, supplying that directory and Git checkpoint.
   Writers return artifacts without advancing stages. Independently review both using the
   reviewer protocol in `deliver`, with coverage, checkable criteria, and consistency as
   acceptance criteria. Resolve findings before presenting the pair.
4. Ask jointly to approve spec and plan, commit the documents, implement/install the stated
   scope, and let the main agent commit reviewed subtasks and verification records. For a
   planning-only request, ask only for document approval/commit and stop before delivery.
5. Record actual approval/scope in Notes; save selected decisions with `wiki-add`. Retry a
   required failure once; failure blocks implementation. Commit only the approved spec/plan
   as `plan(<task>): approve spec and plan`, inspect actual document content in the commit,
   and retain its ID. The subject is a locator, not proof of user consent.
6. Load `deliver` with plan path, authorization, and document-commit evidence. Commit reviewed
   subtasks autonomously. Do not seek another approval after each subtask or commit.
7. After all subtasks, integrated verification, and final review pass, finish below.

## Git and finishing

Before every commit, confirm the checkout/branch and inspect the entire staged diff. Stage
only accepted task files/hunks. If unrelated staged work cannot be separated safely, resolve
ownership before committing. Workers never stage, commit, or edit shared progress.

Keep a reviewed task `[~]` with `review accepted / commit pending` in Notes. Verify its commit
before marking `[x]` and recording the ID. An interrupted reply is not proof of failure:
inspect history and contents before retrying. Document true no-ops without empty commits.
Post-commit progress belongs in the next subtask commit or a final verification-record commit.
Record the last documentation commit ID in the conversation; do not create recursive commits
just to put a commit's own ID inside itself.

After verified delivery, commit remaining task-owned verification records under the approved
authority, then load `merging-git-branch` with actual task/parent names and test evidence.
Present the completed branch for the user's merge/keep choice. Design/implementation approval
does not authorize merging. A blocker retains the checkpoint and prevents completion claims.
Keeping the branch is valid finishing. Pushing, deletion, and cleanup are outside this workflow.

After finishing, record the actual outcome in the appropriate checkout, invoke `wiki-add` for
verified results/finishing status, and check `update-project-context`. Retry required wiki
failures once; unresolved failure leaves closure incomplete. Report any post-merge documentation
left uncommitted; task-branch commit authority does not extend to new parent-branch commits.
Close the checkpoint only after finishing and documentation succeed. Preserve the plan on disk.
