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
request did not approve the broader lifecycle integration recommendations above.

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

## Navigation

[Workflows](../workflows.md) records the approved skill-level ownership migration and the open
follow-up recommendations.

[Notes index](index.md) · [Project wiki](../index.md)
