# Workflow review — 2026-09-20

> **Status:** Review of the user's uncommitted workflow changes. The scoped approval below
> records decisions for the next implementation step; remaining recommendations are unapproved.

## Intended lifecycle

The user's vision is: system prompt → request → enter-workflow → explore → grill → approval →
task branch → spec → plan → deliver → offer merge into the user-specified parent with confirmation.

## Verified gaps

- `enter-workflow` line 62 invoked nonexistent `write-plans`; the available skill is `write-plan`.
  **Superseded by the verified implementation below.**
- The existing plan line 47 invoked deleted `to-spec`. **Superseded by the verified implementation
  below.**
- `write-plan` lines 159–167 called unregistered `show_plan` (the current agent tool registry does
  not register it), referenced nonexistent steps 7 and 8, and invoked `deliver` itself even though
  `enter-workflow` also owned approval, commit, and delivery. **The stale references and self-
  invocation are superseded by the verified implementation below; plan-format alignment remains
  open.**
- Attaching the plan before delivery made deliver Phase 1 skip Phase 3's independent plan review.
  **Superseded for the approved ownership scope: plan attachment and independent review now belong
  to the lifecycle owner.**
- The new plan header lacks `Context`, `Approach`, and `Notes`. A direct probe of
  `dagi` Python `tools._plan_parser.extract_global_sections(header)` returned an empty string;
  the worker plan utilities use this extractor, so `Global Constraints`, `Review Focus`, and the
  spec reference are omitted from the explicit task body.
- A new heading without status parses as unknown. The template lacks task-level `Acceptance
  Criteria`, while integrated delivery verification expects it.
- There is no merge offer or parent-capture workflow; delivery ends at detach. **Still open; no
  merge integration was added.**
- The bounded path explicitly skips branch/spec/plan/deliver and commits after its steps. This
  needs reconciliation with the intended exception and the repository's explicit Git permission.
- The branch step lacks dirty-work handling, parent capture, existing-branch policy, and resume
  policy.
- `write-spec` ends with an empty `Saving the spec` heading.
- New entry paths do not explicitly ensure a wiki query before exploration; delivery ensures it
  only later. **Superseded for the approved ownership scope: the lifecycle owner now preserves the
  wiki-query gate.**

## Recommendations

Use one lifecycle owner, probably `enter-workflow`; have writer skills return control; let deliver
execute the reviewed, approved plan and return the verified result; and make the final merge offer
include an explicit target-parent confirmation. These are recommendations, not approved
implementation.

## Approved scope — 2026-09-20

The user explicitly approved work on checklist points 1 and 2 only. The approved ownership and
routing decisions are:

- `enter-workflow` is the sole lifecycle owner.
- Planning, specification, writing, review, approval, and delivery stages return control to that
  owner instead of invoking later lifecycle stages themselves.
- Correct `write-plans` to `write-plan`.
- Remove the deleted `to-spec` invocation.
- Redirect legacy `/plan` to the same owner, planning-only, without implementation.
- Transfer writer approval, plan attachment, and delivery handoff ownership to the lifecycle owner;
  transfer the old planning ownership and final-closure responsibility to the lifecycle owner.

This is an approved scoped change list, not evidence that implementation is complete. Existing
wiki-query and wiki-add gates remain in force. The remaining checklist items, including TDD and
merge-draft integration, were not approved for this step.

## Follow-up results — 2026-09-20

The user then requested a concrete change list with recommendations and two simple placeholders,
named `do-TDD` and `merging-git-branch`; the placeholder contents were to be decided later. The
request did not approve the broader lifecycle integration recommendations above. The placeholder
contents were subsequently replaced by the approval recorded below.

The resulting draft artifacts are:

- `.dagi/skills/do-TDD/SKILL.md` (34 lines): a draft sample describing red/green/refactor inside
  `deliver` for approved behavior, with implementer/worker evidence returned and no delegation.
- `.dagi/skills/merging-git-branch/SKILL.md` (35 lines): a draft sample for after successful
  delivery verification/final review; it inspects the task and parent, offers an explicit named
  target or retain choice, merges only after user approval, verifies the result, and returns the
  status for the caller to record and detach. Push and branch deletion remain separately
  authorized.

The proposed integration was not implemented. `new_skills_planning.md` now has a prepended
15-item actionable checklist and proposed lifecycle, with its original notes preserved, and
`AGENTS.md` links to that checklist. No branches, commits, or runtime changes were made.

Verification used the dagi Python `SkillLoader` and `SkillTool`: both draft skills were discovered
and loaded; the loader normalizes `do-TDD` to the callable name `do-tdd` while preserving the
filename/title case. A generic quick validation passed for `merging-git-branch` and rejected the
requested uppercase `do-TDD` spelling under its lowercase-only naming rule; the requested spelling
was preserved because the real dagi loader/tool accepts it via normalization. `git diff --check`
passed for the checklist. These results do not change the unapproved status of the integration
recommendations or the unresolved gaps above.

## Implementation result — 2026-09-20

The user approved checklist points 1 and 2 only. The approved ownership migration was implemented
at the skill-instruction level and verified against the six modified skills. `enter-workflow` is now
the sole owner of stages, approval, active-plan state, and closure. `/plan` is a planning-only
adapter that calls that owner once; writer skills return paths/readiness without launching later
stages; `grill` returns to the owner; and `deliver` owns execution, per-task review, and integrated
verification. Standalone deliver redirects to the owner once, while an owner-invoked deliver stage
does not redirect. Blockers that require plan or scope changes return to the owner.

The owner now preserves the wiki-query gate, approval wiki-add, independent plan review, completion
wiki-add/update-context, and detach responsibility. Closure detaches before the final-response call.
The implementation also corrected `write-plans` to `write-plan`, removed `to-spec`, removed the old
`.dagi/plans` path and old `/plan` body, and removed `show_plan` plus nonexistent steps 7 and 8.

Verification in the `dagi` Python environment loaded all six modified skills through
`SkillLoader.load_all_with_errors` and `SkillTool.run` with no load errors; removed names were
absent; and scoped `git diff --check` passed. Manual review covered planning-only stopping, direct
deliver routing, and return/blocker ownership. No live model end-to-end run occurred, and no runtime
code or tests changed. No commits or branch changes were made.

This records a skill-level ownership migration, not full workflow completion. The remaining open
work includes plan-format alignment, a complete resume protocol, Git parent/dirty-state policy, the
bounded exception, the write-spec saving contract, artifact-location consistency, and TDD/merge-draft
integration. The owner preserves the current report/detach behavior; no merge was added.

## Plan adapter correction and completion — 2026-09-20

The earlier approved-scope wording that preserved a legacy `/plan` adapter was superseded by the
user's correction that `/plan` is removed and planning is provided by `write-plan`. The deleted
`.dagi/skills/plan/SKILL.md` and active adapter references were removed from the lifecycle owner,
delivery, grill, project instructions, and the workflow checklist. Planning-only intent handling
remains in the owner; `write-plan` remains an artifact-only standalone skill, while
`enter-workflow` owns approval and the transition into delivery.

The implementation also updated the README planning guidance and TUI slash-command help to use
`write-plan`, and removed the stale `/plan` claim from the Git helper docstring. No broad cleanup,
branch, commit, or merge was performed. TDD and merge-draft work remains unchanged and the other
workflow migration issues remain open.

Verification used the `dagi` Python loader and tool: `/plan` is absent and a call returns
not-found, while `write-plan` is callable. Slash help omits the old command and includes the new
one. Scoped `git diff --check` passed. No live model end-to-end run was performed.

## Approval checkpoint — 2026-09-24

The user approved replacing the two placeholders and integrating them into the main workflow
before checklist point 3. The approved behavior is:

- `do-TDD`: for approved behavior, write a meaningful failing test or mock first, implement the
  minimum change to make it pass, then refactor while keeping the relevant tests passing. Record
  the red, green, and refactor evidence; disclose deviations or when no meaningful test exists;
  never delete code automatically. The worker returns evidence and does not delegate or commit;
  `deliver` owns full verification.
- `merging-git-branch`: after delivery verification, merge only into an explicitly confirmed local
  parent, or retain the task branch when that is selected. Verify current evidence and the merged
  result; preserve work and block closure on failures. Do not push, create a PR, pull, force,
  discard, or remove branches/worktrees automatically. Cleanup requires separate authorization.
  `enter-workflow` owns the final documentation and detach after the outcome.

These are approved workflow behavior and integration decisions, not evidence that implementation
is complete. The implementation must place TDD during approved delivery and the merge offer after
successful verification, before checklist point 3 is addressed. Existing wiki-query and wiki-add
gates remain in force.

## TDD and merge integration completion — 2026-09-24

The approved placeholders were replaced and integrated at the prompt and skill-instruction
level before checklist point 3. This supersedes the draft placeholder descriptions above; the
earlier review history remains preserved.

- `do-TDD` is invoked during approved delivery. Its runtime name is lowercase `do-tdd`.
  `deliver` loads the full instruction text and sends it through `run_worker` as
  `custom_instructions`, including repair guidance because workers do not have the skill tool.
  The bounded main implementer also loads the TDD instructions. Workers must report red, green,
  and refactor evidence plus limitations; no tool permissions are expanded. A task without a
  task branch produces no merge offer.
- `write-plan` links both delivery stages. `enter-workflow` records the parent before creating a
  task branch and carries it into the plan Notes.
- After delivery verification, `merging-git-branch` verifies current evidence and offers only an
  explicit local named-target merge or keep-as-is choice through `no_timeout` `ask_user`. It does
  not push, create PRs, or clean up automatically. It returns merged, kept, or blocked; the owner
  records the result, writes the completion wiki/context updates, and detaches only on success.
  A blocked outcome stays attached. Keep-as-is is a valid completion. Closure documentation targets
  the appropriate checkout after merge and reports uncommitted documentation without auto-commit.

Verification loaded the five relevant skills through the actual `dagi` `SkillLoader` and
`SkillTool`; mocked `RunWorker` dispatch preserved the full loaded TDD text in custom
instructions. `tests/test_subagent_tools_new.py` passed all 32 tests with an isolated writable
basetemp after an initial run exposed four temp-fixture permission errors. `git diff --check` and
the generic quick merge validator passed; the validator rejects uppercase `do-TDD`, while actual
dagi loading succeeds through normalization. No live model or end-to-end merge run occurred. No
runtime Python changes, commit, branch, or merge were made. Point 3/full resume redesign and known
plan-format gaps remain pending.

The completion result is recorded here for the lifecycle owner's final wiki-add; no broad
historical cleanup was performed.

## Checklist point 3 approval — 2026-09-24

The user said, “okay let's go to point3,” authorizing work on checklist point 3 and its
entry/resume instructions. Genuinely new requests start `enter-workflow`; follow-ups, approval
answers, and resume requests continue the current stage using the existing active-plan tool and
conversation evidence. This preserves the previously approved TDD and merge integration and
does not propose a new state machine or session storage. This approval checkpoint is superseded by
the completion below; the prior history remains preserved.

## Checklist point 3 completion — 2026-09-24

Point 3 was implemented at the instruction level. The main prompt now classifies new tasks,
answers/approvals, follow-ups, status requests, casual messages, and automated continuations.
Approvals are scoped to a pending question. On resume or compaction, and before plan actions, the
owner reads `check_active_plan`; pre-plan stages use retained context. Unknown, stale, or
mismatched evidence blocks mutations pending clarification.

The existing plan `Notes`/`Next Action` fields, or the pre-plan conversation, carry the checkpoint
stage, task, artifacts, branch, question, approval evidence, and next action. Compact templates and
the compact worker preserve that checkpoint and never invent one. Delivery resumes pending
implementation or integrated verification from accepted evidence; failed markers do not count as
completion. Interrupted merge side effects are checked against actual Git state. An explained
branch mismatch after a confirmed target merge remains associated until closure. No new state
machine or sidecar schema was introduced.

The related skill guidance was updated to avoid restarting on reload, and the all-tasks-resolved
reminder now routes through branch finishing and documentation before detach. README and AGENTS
checklists record point 3. Existing uncommitted TDD and merge work was preserved.

Verification passed: 19 `tests/test_active_plan.py`, 20 `tests/test_system_prompt.py`, and
`tests/test_compact_subagent.py` (39 tests total) in the `dagi` environment with isolated writable
basetemp; actual `SkillLoader`/`SkillTool` routing loaded; and `git diff --check` passed. An
independent paper review covered eight entry/resume cases, including pre-plan work, planning-only
approval, compaction, interrupted merge, unrelated task, status, failed task, and a missing
pending question; the explained branch-mismatch clarification was addressed. No live model or
full workflow run occurred, so prompt instructions are not deterministic runtime enforcement. No
commit, branch, or merge was made.

Point 3 completion supersedes the earlier pending statement. Known plan-format gaps remain outside
this completion. The prior pending point 3 record and all earlier review history remain preserved.

## Git sequence approval checkpoint — 2026-09-24

After the grill stage and shared understanding, the user explicitly chose the following workflow
sequence. This supersedes the separate spec-approval-plus-commit sequence and the earlier
per-step-commit interpretation:

1. Ask approval to create the task branch.
2. Create the task branch.
3. Write the spec and plan.
4. Ask approval for the spec and plan.
5. Commit the spec and plan to the task branch.
6. Start implementation.
7. Commit after each completed subtask.
8. After full completion, ask approval to merge.

The user also approved the main agent owning scoped commits, with merge remaining a separate
approval step. The implementation instructions must include Git safeguards that record the parent,
task, and artifacts; preserve unrelated dirty work; and recover existing or interrupted branches
safely. Bounded work is interpreted through this shared sequence with proportionate artifacts;
wiki queries remain unaffected. The requested readback must report Outcome, Paths, Change summary,
Conflicts, Partial writes, and Failure details promptly. This is an approval checkpoint for
instruction changes, not a request to create a branch or commit the current wiki edit. Work is not
complete until the sequence is implemented and verified.

## Global Codex port review findings — 2026-09-26

The requested examination covered the `enter-workflow` series for a possible global Codex port.
Nothing was installed and no implementation was approved. The proposed skill set is
`enter-workflow`, `write-spec`, `write-plan`, `deliver`, `do-tdd`, and `merging-git-branch`,
with the existing `grill-me`, `wiki-query`, `wiki-add`, and `update-project-context` skills
integrated as applicable.

The inspection found that `write-plan` lacks the `Workspace` field and the per-subtask `Goal`,
`Acceptance Criteria`, and status markers that `deliver` requires. It also found that `deliver`
treats an approval commit message as proof of formal approval, while the lifecycle owner requires
artifact/history evidence alone to remain insufficient. The draft `do-TDD` guidance assigns
bounded review to `deliver`, while the owner directly reviews bounded work. These claims conflict
with the corresponding prior workflow records; the conflicts are recorded for resolution rather
than auto-resolved (`conflict_detected: 2026-09-26`).

Any port must replace Dagi-specific `skill()`, `ask_user`, active-plan association,
`run_worker`/`review_work`, status parsing, and `write_handoff` behavior with the actual Codex
facilities and instructions. Native worker/reviewer prompt contracts must be carried as explicit
references. The global `grill-me` skill uses frontier rounds, whereas Dagi uses one question at a
time; the existing global preference should be preserved unless explicitly changed. Global
activation needs routing instructions, not skill files alone. Global wiki/path/branch policy also
needs an explicit design. All of these are proposals pending separate approval.

No source code or tests were changed by this review. Verification was limited to wiki readback and
link checks after this note update.

## Decision resolution — 2026-09-26

The user agreed the following design direction for Dagi alignment and the global Codex port. These
are recorded as agreed decisions for pending implementation; they do not record an implemented
port, committed subtasks, or global installation.

- Preserve `wiki/tasks/YYYY-MM-DD_<task>/spec.md` and `plan.md`. One shared writer/delivery plan
  template, including `Workspace` and the required per-subtask fields, applies to both hosts.
- Preserve the initial branch-setup gate and the joint spec/plan implementation-approval gate.
  After that approval, the main agent autonomously reviews and commits subtasks; there is no
  per-subtask or per-commit user approval gate. Request final approval only after all subtasks and
  verification, before merge.
- A commit subject alone is never approval. Keep accepted, commit-pending, and verified-complete
  evidence separate, and reconcile Git state on resume.
- Global Codex guidance routes new coding tasks into `enter-workflow`. Continuations preserve the
  current stage and approvals. Explicit standalone skills retain their scope, and read-only
  questions do not require a preliminary workflow nod.
- Preserve Codex `grill-me` frontier rounds while Dagi keeps its one-question-at-a-time style.
- Native worker and reviewer delegates have no nesting or commit authority and use
  `gpt-5.6-luna` with medium reasoning.
- Replace Dagi question-tool assumptions with the actual Codex facilities. Silence and timeouts
  never count as consent.
- Default branches are `dagi/<task>` and `codex/<task>`, subject to an applicable project
  override.

The user authorized branch setup and drafting only. Branch `dagi/codex-workflow-port` was created
from `main` at `5c1b6db6d56a409b12d06957786d4344a5012bb1`, with pre-existing unstaged work
preserved. The spec and plan were drafted. Joint artifact approval, their commits, implementation,
global installation, and merge remain pending and were not authorized or completed by this record.

This decision section resolves the reviewed design questions above where the user explicitly chose
a direction; the earlier proposal and conflict history remains intact for implementation review.

## Joint implementation approval — 2026-09-26

The user replied “continue” directly to the explicit joint approval request for
`wiki/tasks/2026-09-26_codex-workflow-port/spec.md` and `plan.md`. That reply authorizes the
reviewed artifacts and the scoped execution work: committing the documents, implementing the
Dagi alignment, installing the agreed Codex skills globally under `C:/Users/alexr/.codex/skills`,
and allowing the main agent to autonomously review and commit completed subtasks. It does not
authorize merging or choosing whether to keep the task branch; that remains a separate final
decision after completion and verification.

The approved execution starts on branch `dagi/codex-workflow-port`, created from `main` at
`5c1b6db6d56a409b12d06957786d4344a5012bb1`. Pre-existing unstaged work is preserved. No
implementation, global installation, or commit had occurred when this authorization was recorded.

This section supersedes the earlier pending-artifact-approval status for the reviewed spec and
plan while preserving that history. It records authorization only; completion evidence belongs in
a later wiki-add after implementation and verification.

## Dagi alignment and global Codex installation — 2026-09-27

The approved Dagi alignment and global Codex workflow port are implemented and verified.
This completion evidence supersedes the earlier pending implementation and installation statuses
and resolves the implementation gaps described in the port review, while preserving those
historical findings and approvals. Installation is complete. At this checkpoint, the final
documentation commit and the user's merge-or-keep decision remain pending; the workflow is not
fully closed.

Six new skills are installed globally: `enter-workflow`, `write-spec`, `write-plan`, `deliver`,
`do-tdd`, and `merging-git-branch`. Existing `grill-me` and `update-project-context` were adapted;
the original `grill-me` frontier body was retained exactly with an added return contract.
`wiki-query` and `wiki-add` were reused unchanged. The tracked package is `integrations/codex`,
and the installed root is `C:/Users/alexr/.codex/skills`. Routing was appended to global
`AGENTS.md`, preserving the existing `gpt-5.6-luna` medium reasoning policy. After the Luna usage
limit, the user authorized a task-only `gpt-6-astra` exception; this does not replace that standing
policy. The refreshed host catalog exposes the six new and two adapted skills.

The canonical Dagi writer/delivery template now matches its consumers. Instructions distinguish
actual user approval from a commit subject and separate accepted, commit-pending, and
verified-complete states with Git recovery. Joint authorization permits scoped subtask commits
without further per-subtask or per-commit user gates. Standalone skill scope and owner closure
are preserved, and plans use `wiki/tasks/YYYY-MM-DD_<task>/`.

Entry initializes a missing wiki before querying it. The portable helper creates only the seven
missing wiki pages, preserves existing bytes and partial output, rejects unsafe paths, reports
clear failures, and has no Dagi dependency.

Recorded commits are:

| Commit | Scope |
| --- | --- |
| `4d0acab3` | Approved documents |
| `417d2244` | Canonical template |
| `35baf0f7` | Lifecycle alignment |
| `f39d42c5` | Portable wiki bootstrap |
| `09d4e2c9` | Codex package |

Independent subtask and package reviews passed. Independent final review passed through
`09d4e2c9`. The 108-test suite passed with no skips in both the working tree and a clean committed
archive; the final reviewer independently repeated the archive suite successfully. Eight packaged
and eight installed skill validations passed using UTF-8. Twelve installed files exactly matched
their source hashes; 73 unrelated original skill files, including grill metadata, were unchanged.
Canonical template equality and five link resolutions were verified.

Instruction scenario reviews covered authorization, recovery, wiki/query behavior, standalone
scope, branch overrides, and missing delegation. No live end-to-end model workflow was executed;
these instructions are not runtime enforcement.

The branch remains `dagi/codex-workflow-port`, with recorded parent `main` and initial commit
`5c1b6db6`. All pre-existing unrelated working changes were preserved and were not included
wholesale in the commits. Global backups are at
`C:/Users/alexr/AppData/Local/Temp/codex-workflow-port-20260926-103245/global-before`.
No merge, push, or deletion occurred. At this checkpoint, final documentation and the separate
user branch-finishing decision are still required.

## Local merge closure — 2026-09-27

The user explicitly replied `merge`, authorizing the local fast-forward-only merge of
`dagi/codex-workflow-port` into `main`. The merge advanced `main` from
`5c1b6db6d56a409b12d06957786d4344a5012bb1` to
`6b0a4ab41be8ce06e5b6aff63857574b57640c2e` and switched the checkout to `main`.
Overlapping dirty files required an ancestry-checked compare-and-swap ref advance followed by
a same-tree checkout; all premerge dirty-file SHA256 hashes were preserved. `HEAD`, `main`, and
the retained task branch now identify `6b0a4ab4`. No push or branch deletion occurred.

All 108 integrated tests passed on merged `main`, with no skips. The previously verified six new
and two adapted globally installed skills remained unchanged. This resolves the pending
merge-or-keep decision recorded above while preserving those earlier checkpoints.

Postmerge wiki, plan, and project-context closure updates remain uncommitted on `main`.
The earlier task-branch commit approval does not authorize new commits on `main`.

## Navigation

[Workflows](../workflows.md) records the approved skill-level ownership migration and the open
follow-up recommendations.

[Notes index](index.md) · [Project wiki](../index.md)
