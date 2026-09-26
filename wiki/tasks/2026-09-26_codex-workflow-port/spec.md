# Dagi workflow alignment and global Codex port

## 1. Document status

- Date: 2026-09-26. Version: 1. Status: approved for implementation and global installation.
- Owner: main Codex agent. Decision owner: user. Independent review: PASS, 2026-09-26.
- Plan: [plan.md](plan.md).
- User approved these reviewed artifacts by replying `continue` to the joint approval request.
  This authorizes implementation, global installation, and autonomous reviewed task commits.
  Merge requires a later, separate decision.

## 2. Summary and problem

Dagi's `enter-workflow` owns exploration, design, approval, delivery, and closure.
Its writers and delivery stage currently disagree on the plan format. Delivery also calls
a matching commit message proof of approval and marks tasks complete before committing.
The user wants these inconsistencies fixed in Dagi and the workflow available globally in
Codex, with reviewed subtask commits made autonomously after initial implementation approval.

Codex already has `grill-me`, `wiki-query`, `wiki-add`, and `update-project-context`.
It does not expose Dagi's worker, review, active-plan, or skill-loading tool interfaces.
Porting requires host-specific instructions, not an unchanged copy of the Dagi files.

## 3. Goals, scope, and non-goals

Deliver six new Codex skills: `enter-workflow`, `write-spec`, `write-plan`, `deliver`,
`do-tdd`, and `merging-git-branch`. Adapt the existing Codex `grill-me` and
`update-project-context`; reuse the installed wiki-query/add skills unchanged.
Align Dagi's plan template, approval evidence, progress transitions, wiki initialization,
and conflicting context/TDD ownership instructions.

Keep tracked Codex sources in `integrations/codex/`, then install to the existing user
skill root `C:/Users/alexr/.codex/skills`. Add routing to `C:/Users/alexr/.codex/AGENTS.md`.
This location is already loaded in this session; do not create a duplicate installation
under `.agents/skills` or change unrelated Codex configuration.

Out of scope: a new MCP service, custom active-plan sidecar for Codex, automatic goals,
plugins, changes to model providers, changes to Dagi's runtime status enums, publishing,
pushes, branch deletion, unrelated cleanup, and automatic creation of a Git repository.

## 4. Requirements and behavior

| ID | Requirement |
|---|---|
| R1 | `enter-workflow` alone owns stage changes, authorization, recovery, and closure. |
| R2 | One maintained plan template per host serves both writer and delivery. The Codex copy is packaged from the canonical Dagi reference and must remain identical. |
| R3 | Preserve `wiki/tasks/YYYY-MM-DD_<task>/spec.md` and `plan.md`; select the date/slug once and reuse them on continuation. |
| R4 | Approval gates are branch setup, joint spec/plan plus autonomous implementation/commit authority, and final verified branch merge/keep. Never request approval after each subtask or commit. |
| R5 | Actual user approval and its scope are separate evidence from document commits. A filename, status field, matching commit subject, or silence never establishes permission. |
| R6 | Subtasks progress through pending, working, review accepted/commit pending, and verified complete. Interrupted commits are reconciled against history before retrying. |
| R7 | Codex uses native worker and independent reviewer subagents. Only the main agent updates shared progress, delegates, stages, and commits. |
| R8 | Codex subagents use `gpt-5.6-luna` with medium reasoning, honoring the user's global setting. Missing required delegation capability is reported, never simulated as independent review. |
| R9 | New coding tasks enter the workflow; continuations resume the current stage; explicit standalone skills retain their scope. Read-only questions and conversation do not require preliminary approval. |
| R10 | At substantive workflow entry, resolve the project root, check the wiki, initialize missing scaffold files if needed, then perform wiki-query. Preserve all existing files. |
| R11 | Default task branches are `dagi/<task>` in Dagi and `codex/<task>` in Codex; explicit applicable project instructions may override the default. |
| R12 | Preserve Codex grill-me's frontier rounds and Dagi grill-me's one-question style. Add only the missing Codex return-to-owner contract. |
| R13 | Reuse prior approval and valid verification. Changes invalidate only affected scope; unresolved ambiguity blocks dependent mutations. |
| R14 | Global installation preserves unrelated skills, guidance, and existing customization, is verified by readback, and reports any unavailable discovery check honestly. |
| R15 | Both hosts preserve TDD's meaningful-test exception, final integrated verification, separate merge authorization, and required wiki approval/completion checkpoints. |

For bounded work, retain the existing current-branch/inline-plan path: one approval
authorizes implementation and commits, and the owner handles review and closure. No new
branch or merge offer is manufactured. Architectural work uses the full written pipeline.
Material scope changes and unresolved blockers may still require user input; routine
successful reviews and commits do not.

## 5. Constraints and assumptions

- Preserve existing uncommitted work; stage only task-owned files or separable hunks.
- Use the `dagi` Python environment for all Python commands in this repository.
- Functions <= 100 lines, cyclomatic complexity <= 8, positional parameters <= 5.
- Line length <= 100 characters for code; implementation files <= 500 lines.
- No dependency on the Dagi checkout in installed Codex skills.
- No subagent nesting; main agent owns plan progress and Git mutations.
- Bootstrap missing wiki files without overwriting any existing bytes or following an
  escaping symlink/junction. An inaccessible or non-file index is an error, not absence.
- Skill instructions remain instructions, not a new runtime permission-enforcement layer.

The global install path and tracked package location above are proposed implementation
choices included in this approval. Wiki bootstrap is the explicitly authorized entry
exception to the implementation gate; it does not authorize any other source edits.

## 6. Proposed architecture

```text
Global Codex AGENTS routing -> enter-workflow (main agent)
  -> wiki bootstrap if needed -> wiki-query
  -> grill-me -> write-spec -> write-plan -> independent plan review
  -> joint user approval -> wiki-add -> document commit
  -> deliver -> worker with TDD -> independent reviewer -> main-agent commit
  -> integrated verification + final review -> final user merge/keep choice
  -> context/wiki completion -> close
```

Dagi keeps its native tools and active-plan association. Codex uses its task conversation
checkpoint and explicit plan path; each resume rereads that file and reconciles its branch,
stage, approval scope, and Git evidence. Do not choose the newest file or a matching slug
alone when the task association is ambiguous. No custom state service is introduced.

The canonical template is `.dagi/skills/write-plan/references/plan-template.md`.
Dagi writer and delivery instructions point there; the Codex package contains the same
reference within its `write-plan` skill. Every reference resolves within the installed
skill set; nothing refers back to a repository-only absolute path.

Worker and reviewer protocols live in `deliver/references/worker.md` and `reviewer.md`.
They preserve Dagi's outcomes and evidence requirements but use native final messages
instead of handoff-file tools. The parent supplies full TDD instructions, task criteria,
global constraints, exact checkout, and allowed file scope.

## 7. Detailed contracts and state

The shared template includes the Goal/Architecture/Tech Stack/Spec header, Global
Constraints, Review Focus, Workspace, Overall Status, Subtasks, Notes, Open Issues,
Attempts and Resolutions, Verification, and Next Action.
Workspace records Branch, Parent, Starting commit, and Artifact directory before approval.
Each `### Subtask N: [ ] Name` includes Goal, Requirements, Acceptance Criteria, Files,
Interfaces, `#### Tests`, and concrete implementation/verification steps.

Keep the current parser markers: `[ ]` pending, `[~]` in progress, `[!]` blocked/failed,
and `[x]` complete. Review acceptance and commit-pending status are fields in Notes, not
new parser tokens. Record the reviewer outcome before committing. After verifying the
commit and its task-owned diff, set `[x]` and record its ID. A valid documented no-op may
complete without an empty commit.

A commit cannot contain its own final ID. Post-commit progress updates belong in the next
task commit or a final task-scoped verification-record commit before the merge offer.
On interruption, use the recorded accepted scope and Git diff/history to reconcile stale
markers. Do not rerun accepted implementation merely because the progress edit lagged.

Approval Notes record what the user approved, the relevant artifact version/scope, whether
execution was authorized, and document-commit evidence separately. If conversation and
checkpoint evidence conflict or authorization cannot be recovered, ask for clarification.
Do not invent approval or ask again solely because a new subtask begins.

Codex questions use the actual available input mechanism or a clear final-message question.
Never assume `no_timeout` exists, use a planning-only tool for permission, or treat expiry
or an unanswered question as consent. Existing task-scoped approval remains effective.

Bootstrap checks a resolved selected project root before querying. Dagi reuses its existing
`agent.cli_utils._cmd_init` entry point. Codex gets a standalone stdlib helper that creates
only seven wiki scaffold files; it does not create `.dagi`, alter AGENTS, initialize Git,
populate project facts, or read personal memory. It also repairs missing scaffold members
when `wiki/index.md` is missing, preserving partially populated wikis.

Global routing leaves ordinary conversation outside the lifecycle. A substantive project
query uses entry's context/bootstrap handling without branch setup or approval ceremony.
With no Git repository, research may proceed; a branch-based implementation reports the
missing prerequisite and asks the user rather than running `git init` implicitly.

## 8. Quality and operational requirements

No new runtime service or third-party package. All executable helper behavior has focused
tests of preservation, path containment, and failure reporting. Template tests exercise
the real Dagi parser/worker extraction rather than only matching instructional wording.
Independent scenario review checks approval and recovery behavior that static tests cannot
prove. Record exactly which checks ran; no claim of a live Dagi model test without one.

## 9. Failure and recovery behavior

- Missing/unreadable plan, ambiguous task association, or unexplained branch mismatch:
  retain current artifacts and block dependent work.
- Review failure: repair the affected implementation without a new approval when within scope.
- Commit interruption: inspect actual history; resume at the missing commit/progress step.
- Wiki query/required write failure: retry once per existing wiki contract, then report it.
- Bootstrap failure: report the exact failed path; preserve any created files for safe retry.
- Global destination changed since inspection: compare and preserve the change before writing.
- Global write denied: keep the reviewed package, report installation incomplete, and use
  the platform's approved permission mechanism rather than bypassing its restrictions.
- Merge happened but verification failed: report both facts, retain recovery context.

## 10. Alternatives and decisions

User agreed to preserve the existing task directory rather than invent another plan root;
use file/checkpoint association initially instead of implementing Codex sidecars; unify the
template in Dagi too; and reserve user approval for initial scope and the completed branch.
The user explicitly chose wiki creation at workflow entry and approved native delegation,
host-specific grill styles, branch prefixes, and global routing.

A direct unchanged copy is rejected because its tool calls would be unavailable in Codex.
A plugin or generic installation framework is unnecessary for this personal installation.
The tracked package is justified by review, repeatability, and separation of global writes
from repository changes; installation can use ordinary bounded file operations.

## 11. Compatibility and release design

Keep existing Dagi tool APIs/status markers and leave legacy plan files untouched. A legacy
plan missing required fields is repaired explicitly when resumed, with approvals preserved
only where supported. Do not bulk-migrate historical notes or execution plans.

Install the six new directories and two reviewed updates into the existing global skill
root after checks pass and implementation/global-write authority is granted. Preserve
pre-install versions of files being replaced outside the discovered skill roots, record
their location, and apply a scoped routing addition to global AGENTS. Do not replace its
subagent model instruction. Restore only installation-owned changes if rollback is needed;
never overwrite subsequent user edits. Reload/restart only if discovery requires it.

## 12. Acceptance and verification

R1-R6/R13: common template parses, preserves worker requirements/tests, and recovery scenarios
do not skip authorization or repeat accepted work. R7-R8/R12: independent assignments carry
the right instructions and model settings, and existing grill style remains unchanged.
R9-R11: routing and bootstrap scenarios cover coding, continuation, standalone, query,
missing/partial wiki, and branch overrides. R14: package validation and installed readback
match the reviewed source, without unrelated changes. R15: TDD limitation reporting,
verification, wiki checkpoints, and separate merge/keep remain intact.

## 13. Risks and open questions

No unresolved product decision blocks implementation. Joint artifact approval is recorded above.
The working tree contains pre-existing edits, including several overlapping skill/context
files; approval to preserve them is not approval to commit them wholesale. Inspect hunks
before every commit and report inseparable ownership instead of folding unrelated work in.

Codex skill discovery for newly installed files may require a fresh session. File validation
and readback alone do not prove that a running task's cached catalog has refreshed.

Readiness: independently reviewed and approved for implementation.
