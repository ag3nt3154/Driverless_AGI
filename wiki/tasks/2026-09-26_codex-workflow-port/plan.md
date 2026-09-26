# Dagi workflow alignment and global Codex port Implementation Plan

**Goal:** Align Dagi's workflow contracts and install the approved workflow globally in Codex.
**Architecture:** Keep one canonical plan template, with host-specific lifecycle and execution
instructions. Package Codex sources in the repository and install after scoped verification.
**Tech Stack:** Markdown skills, Python stdlib/bootstrap, existing Dagi parser, pytest, Git.
**Spec:** [spec.md](spec.md), approved version 1, 2026-09-26.

## Global Constraints

- Preserve existing uncommitted work; stage only task-owned files or separable hunks.
- Use the `dagi` Python environment for all Python commands in this repository.
- Functions <= 100 lines, cyclomatic complexity <= 8, positional parameters <= 5.
- Line length <= 100 characters for code; implementation files <= 500 lines.
- No dependency on the Dagi checkout in installed Codex skills.
- No subagent nesting; main agent owns plan progress and Git mutations.
- Bootstrap missing wiki files without overwriting any existing bytes or following an
  escaping symlink/junction. An inaccessible or non-file index is an error, not absence.
- Skill instructions remain instructions, not a new runtime permission-enforcement layer.

## Review Focus

- A matching approval-commit subject without user authorization must not start delivery (2, 4).
- Commit success followed by interruption before progress update must not duplicate work (2, 4).
- Partial wiki, empty existing files, and escaping links must preserve outside/user data (3).
- Codex imports must run without Dagi tool names, paths, or package imports (3, 4).
- Global installation must retain existing grill style, model policy, and unrelated edits (4, 5).

## Workspace

- **Branch:** `dagi/codex-workflow-port`
- **Parent:** `main`
- **Starting commit:** `5c1b6db6d56a409b12d06957786d4344a5012bb1`
- **Artifact directory:** `wiki/tasks/2026-09-26_codex-workflow-port/`
- **Repository:** `C:/Users/alexr/Driverless_AGI`
- **Global skill destination:** `C:/Users/alexr/.codex/skills`
- **Global routing destination:** `C:/Users/alexr/.codex/AGENTS.md`

## Overall Status

Approved for implementation and global installation after independent review PASS.
Document commit and approval wiki checkpoint precede implementation. No subtask has started.

## Subtasks

### Subtask 1: [ ] Align the shared plan template with Dagi's consumers

**Goal:** A writer-produced plan is immediately usable by delivery and worker extraction.
**Requirements:** R2, R3, R6. Populate Workspace before approval. Preserve detailed steps,
interfaces, constraints, requirements, acceptance criteria, and tests in one template.
**Acceptance Criteria:**
- Dagi writer and delivery reference one canonical template, with no second embedded schema.
- A rendered example yields pending subtask statuses and the intended worker inputs through
  `parse_subtask_statuses`, `extract_global_sections`, and `extract_subtask`.
- Status updates round-trip without destroying task tests or adjacent sections.
- Existing parser behavior remains unchanged; no new marker or tool API is required.
**Files:**
- Create `.dagi/skills/write-plan/references/plan-template.md`.
- Modify `.dagi/skills/write-plan/SKILL.md` and `.dagi/skills/deliver/SKILL.md`.
- Create `tests/test_workflow_plan_template.py` for template/consumer compatibility;
  the existing parser test file is already 552 lines, above the project's 500-line cap.
**Interfaces:** Consumes existing parser/extraction functions in `tools/_plan_parser.py`.
Produces the canonical Markdown reference copied into the Codex writer package in subtask 4.

#### Tests

Add a test loading the actual reference and filling documented template slots for two
subtasks. Assert both return `pending`; extract the first task and check its actual
requirement/acceptance/test payload is present and the second task's payload is absent.
Round-trip a marker update in a temporary plan and verify preservation of the payload.
This tests the writer-consumer interface, not prose phrasing or heading counts alone.

#### Steps

- [ ] Add the consumer test and run it red against the missing canonical reference.
- [ ] Create the template with header, Global Constraints, Review Focus, Workspace,
  Overall Status, Subtasks, Notes, Open Issues, Attempts and Resolutions, Verification,
  and Next Action. Each task has the fields listed in spec section 7.
- [ ] Replace both embedded formats with an explicit instruction to load the shared
  reference. Specify `in_progress` plus a Notes commit-pending field until verified commit.
- [ ] Run `conda run -n dagi python -m pytest --noconftest -p no:pytest-qt
  tests/test_plan_parser.py tests/test_workflow_plan_template.py -q`; return evidence for review.

### Subtask 2: [ ] Align Dagi lifecycle, approvals, and recovery instructions

**Goal:** Complete reviewed subtasks and commits autonomously under initial approval.
**Requirements:** R1, R3-R6, R9-R11, R13, R15. Keep Dagi's native tools and grill style.
**Acceptance Criteria:**
- Review PASS authorizes an internal acceptance transition, not a new user approval gate.
- `[x]` follows a verified commit or documented no-op; recovery inspects Git history first.
- A commit subject never substitutes for user approval, and document contents are checked.
- Missing wiki bootstrap precedes wiki-query; read-only queries do not request a nod.
- The plan remains associated through final verification and merge/keep/documentation.
- The context skill permits `wiki/tasks/...`, and TDD assigns bounded review to the owner.
**Files:**
- Modify `.dagi/skills/enter-workflow/SKILL.md`, `.dagi/skills/deliver/SKILL.md`,
  `.dagi/skills/write-spec/SKILL.md`, `.dagi/skills/update-project-context/SKILL.md`,
  and the task-owned lines of `.dagi/skills/do-TDD/SKILL.md`.
- Inspect `.dagi/prompts/main/main_system.md`; change only a directly conflicting routing
  line if necessary, preserving its existing uncommitted changes.
- Main agent updates relevant AGENTS/wiki context after verification, not worker agents.
**Interfaces:** Consumes canonical template and existing `_cmd_init` initializer. Uses current
`check_active_plan`, `set_active_plan`, review, worker, and status tools without API changes.

#### Tests

No brittle exact-prose unit tests. Run existing initialization/active-plan/status tests and
perform independent behavioral walkthroughs using the actual revised skill instructions:
(a) commit subject only, no approval; (b) planning-only approval; (c) accepted task with
interrupted successful commit; (d) failed commit; (e) all tasks complete awaiting merge;
(f) bounded task; (g) missing wiki; (h) correction affecting only one approved requirement.
Expected actions: block unauthorized work, preserve valid authority, reconcile history,
avoid rerunning accepted work, and ask only at the relevant gate.

#### Steps

- [ ] Edit owner and delivery instructions together: separate user approval, review
  acceptance, commit evidence, and final branch approval.
- [ ] Define the checkpoint's accepted/commit-pending state in Notes and the post-commit
  update rule, including the final verification-record commit and no-op exception.
- [ ] Add explicit wiki check/initializer entry and remove redundant query approval.
  Define a standalone spec default under the same task-directory convention.
- [ ] Correct context path and bounded-review ownership statements; preserve all other
  existing customization, native tools, and one-question grilling.
- [ ] Run `conda run -n dagi python -m pytest --noconftest -p no:pytest-qt
  tests/test_project_init.py tests/test_active_plan.py tests/test_update_task_status.py -q`.
- [ ] Return changes and scenario outcomes for independent review.

### Subtask 3: [ ] Provide a portable, preserving Codex wiki bootstrap

**Goal:** Codex can initialize a selected project's wiki without importing Dagi.
**Requirements:** R10, R14. Use explicit project root, stdlib, exclusive creation, safe paths.
**Acceptance Criteria:**
- An empty project gains exactly seven linked wiki pages and no unrelated scaffold.
- Repeated runs and partial/empty existing pages preserve every existing byte.
- Invalid root, non-file target, escaping link, or permission failure fails clearly.
- The helper does not modify cwd, Git state, AGENTS, personal memory, or `.dagi`.
**Files:**
- Create `integrations/codex/skills/enter-workflow/scripts/init_wiki.py`.
- Create `tests/test_codex_wiki_bootstrap.py`.
**Interfaces:** CLI `python init_wiki.py --project-root <existing-directory>`; exit 0 on
success, nonzero with path/reason on failure. Importable `initialize_wiki(project_root: Path)`
returns created relative paths. Use the seven wiki filenames from `build_init_files` as
the compatible shape, but embed portable content without Dagi imports or AGENTS generation.

#### Tests

Use temporary directories and load the helper by file location. Core preservation case:

```python
def test_preserves_partial_wiki(tmp_path, bootstrap):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    existing = wiki / "architecture.md"
    existing.write_bytes(b"")
    bootstrap.initialize_wiki(tmp_path)
    assert existing.read_bytes() == b""
    assert (wiki / "index.md").is_file()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".dagi").exists()
```

Also test repeat byte equality, relative-link resolution, invalid root, directory at an
expected file path, outside-link containment, and CLI error exit. Skip OS link-creation
cases only with an explicit platform reason; retain a portable containment check.

#### Steps

- [ ] Write focused failing tests for the contract above.
- [ ] Implement CLI and `initialize_wiki`: resolve/check root, preflight target parents,
  reject unsafe targets, create missing directories and files with exclusive mode,
  report existing/created files and actionable errors. Preserve partial successful output.
- [ ] Run `conda run -n dagi python -m pytest --noconftest -p no:pytest-qt
  tests/test_codex_wiki_bootstrap.py -q`; return evidence for independent review.

### Subtask 4: [ ] Package the Codex workflow and existing-skill adaptations

**Goal:** Produce a self-contained, reviewable Codex skill set using real host capabilities.
**Requirements:** R1-R9, R11-R15; consume bootstrap from subtask 3.
**Acceptance Criteria:**
- Six new skills have valid lowercase names and useful invocation descriptions.
- No instruction attempts to call unavailable Dagi tools or depends on this checkout.
- Owner resumes from the explicit plan path/checkpoint and checks branch/evidence.
- Worker/reviewer references include outcomes, test evidence, scoped access, no nesting,
  no worker commits, and required model/effort settings.
- Existing Codex frontier rounds remain; context path rules match the agreed wiki location.
- Copied plan template equals the canonical reference and passes consumer validation.
**Files:**
- Create `integrations/codex/skills/{enter-workflow,write-spec,write-plan,deliver,do-tdd,
  merging-git-branch}/SKILL.md` (brace notation enumerates six directories).
- Create `integrations/codex/skills/write-plan/references/plan-template.md` by copying subtask 1.
- Create `integrations/codex/skills/deliver/references/worker.md` and `reviewer.md`.
- Create tracked adapted copies `integrations/codex/skills/grill-me/SKILL.md` and
  `integrations/codex/skills/update-project-context/SKILL.md` from the existing global files.
- Create `integrations/codex/global-agents.md` as the exact scoped routing addition.
**Interfaces:** Read skill files by their discovered path; use native collaboration
spawn/followup/wait and native final responses. Use available question facilities only as
permitted by their real contracts, with a plain explicit question as the portable fallback.

#### Tests

Validate each package with the installed skill-creator `scripts/quick_validate.py` using
the dagi interpreter. Check all linked local resources exist. Compare canonical and
packaged templates. Independently evaluate realistic scenarios using the skills and minimal
raw artifacts, without giving the evaluator the expected outcome: normal delivery, recovery
after commit, missing/ambiguous plan, missing wiki, standalone writer, read-only query,
branch override, and missing delegation tools. Evaluators must not mutate the live repo or
global directory; use disposable temporary workspaces and simulated Git approval decisions.

#### Steps

- [ ] Adapt host tool calls and paths; retain the established lifecycle boundaries.
- [ ] Supply worker/reviewer protocols as references and full TDD text in assignments.
  Use fresh agents with `fork_turns="none"`, `gpt-5.6-luna`, and medium reasoning.
- [ ] Preserve the Codex grill body and add its return contract. Correct context wording
  while preserving wiki retry/delegation rules and personal-memory separation.
- [ ] Write global routing for new coding work, continuations, standalone requests, and
  questions. Resolve wiki bootstrap in the owner before query; do not activate for casual chat.
- [ ] Validate, independently review scenarios, fix demonstrated failures, and return the
  package and evidence. Do not install global files from a worker.

### Subtask 5: [ ] Install globally and verify the completed branch

**Goal:** Make the reviewed package globally usable without overwriting unrelated settings.
**Requirements:** R4, R5, R13-R15. Main agent owns installation, documentation, and commits.
**Acceptance Criteria:**
- Six new skills and two scoped updates are installed at the recorded existing skill root.
- Global AGENTS contains the reviewed routing and retains the existing model instruction.
- Destination readback matches the reviewed files; unrelated global files remain unchanged.
- All relevant tests and independent final review pass, or failures are reported as blockers.
- User receives one final branch approval request after all subtasks/verification, not one
  after each commit. No merge, push, deletion, or unrelated change occurs automatically.
**Files:**
- Install only `C:/Users/alexr/.codex/skills/<eight packaged names>/`.
- Apply the scoped addition to `C:/Users/alexr/.codex/AGENTS.md`.
- Main-agent documentation: this plan, AGENTS.md, and selected wiki workflow/decision notes.
**Interfaces:** Ordinary scoped file reads/copies/patches and platform permission mechanisms.
Installed wiki-query/wiki-add are reused; no new global configuration or plugin is required.

#### Tests

Before installing, record existing destination file hashes and preserve replaced versions
outside the discovered skill roots, under a task-specific temporary backup directory whose
exact path is recorded in Verification. Recheck destinations before writes. After installing,
compare relative file inventories and hashes with the source, validate installed skills,
and reread global AGENTS. A fresh catalog/discovery check is separate from file validation;
record if the current session cannot refresh its skill catalog without a restart.

#### Steps

- [ ] Confirm joint approval includes global installation and task-scoped commits, and
  that package review/tests passed. Reinspect live destinations for intervening edits.
- [ ] Preserve replaced files and copy only reviewed package files; apply the routing
  addition surgically. Use required platform permission review for global writes.
- [ ] Verify installed files and linked resources; report partial installation accurately.
- [ ] Run integrated verification listed below, with an independent full-task review.
- [ ] Save selected actual results through wiki-add; update project context as main agent.
  Commit only accepted task changes and final verification records under scoped authority.
- [ ] Present the completed branch and request merge/keep. After the user's decision,
  finish only the chosen action and closure; report post-merge documentation left uncommitted.

## Notes

- Branch approval: user replied `ok` to creation of `dagi/codex-workflow-port` from `main`
  and drafting the shared spec/plan while preserving existing work. Branch creation verified.
- Joint approval: user replied `continue` directly to the request to approve both reviewed
  documents, commit them, implement the plan, install globally, and commit reviewed subtasks
  autonomously. This is the approval evidence; merge/keep remains a later separate choice.
- Independent plan review: PASS, 2026-09-26; no blocking findings. Reviewed scope includes
  artifact consistency, approvals, commit recovery, bootstrap, package, and installation.
- Document approval: granted on 2026-09-26; document commit pending. Global install pending.
- Approval wiki checkpoint: successful readback from `approval_wiki`, 2026-09-26;
  authorization recorded in `wiki/notes/workflow-review-2026-09-20.md`.
- Pre-existing unstaged files: `.dagi/prompts/compact/compact_system.md`,
  `.dagi/prompts/compact/compact_user.md`, `.dagi/prompts/main/main_system.md`,
  `.dagi/skills/do-TDD/SKILL.md`, `.dagi/skills/merging-git-branch/SKILL.md`,
  `.dagi/subagents/compact/prompt.md`, `AGENTS.md`, `README.md`, `agent/_system_prompt.py`,
  `agent/loop.py`, `wiki/index.md`, `wiki/notes/index.md`,
  `wiki/notes/workflow-review-2026-09-20.md`, and `wiki/workflows.md`.
- No staged changes existed at setup. Preserve this baseline; changes to overlapping files
  require hunk-level inspection. Existing source changes must not enter this task's commits.
- Before implementation edits, save the current binary Git diff and an explicit affected-file
  hash inventory outside the repository in a task-specific temporary directory; record its
  actual path here. Use that baseline to separate old and new hunks, not to restore files
  wholesale. An existing edit needed by the committed branch is a dependency to disclose and
  resolve explicitly, not permission to include the edit silently. Report validation that
  depends on the pre-existing working tree separately from committed-branch validation.
- Baseline captured before implementation at
  `C:/Users/alexr/AppData/Local/Temp/codex-workflow-port-20260926-103245/`:
  `baseline.patch`, `inventory.json`, and byte-preserving copies under `files/`.
- The current loop handler retains active-plan association after all tasks resolve.
  Some status-tool descriptions still say complete/auto-finished; do not interpret those as
  approval or closure. Runtime status-message cleanup is outside this skills-focused scope.
- Source packaging and bootstrap helper are proposed here for review, not already implemented.

## Open Issues

Existing uncommitted work may overlap implementation hunks; resolve genuinely inseparable
ownership before commit. Joint spec/plan and implementation/global-install approval is granted.

## Attempts and Resolutions

- Branch creation initially lacked sandbox access to `.git`; the approved elevated retry
  succeeded. No reset, stash, commit, or deletion was performed.

## Verification

Planning verification: branch and parent/starting commit checked; existing source/skill
changes preserved by hash comparison. Local document links resolve; no unfinished draft
placeholders found; Git whitespace check passed. Independent artifact review PASS with no
blockers. No implementation tests or global installation ran during drafting.

Implementation verification command:

```text
conda run -n dagi python -m pytest --noconftest -p no:pytest-qt tests/test_plan_parser.py tests/test_workflow_plan_template.py tests/test_project_init.py tests/test_active_plan.py tests/test_update_task_status.py tests/test_codex_wiki_bootstrap.py -q
```

Also validate packaged/installed skills, template parity, resource links, behavioral
scenarios, destination preservation, and the complete task diff from the recorded starting
commit (plus remaining task-owned working changes). Distinguish pre-existing edits.
Do not substitute a clean working-tree diff for the full branch review.
Tests and installation have not run during planning.

## Next Action

Complete approval wiki checkpoint, commit the approved documents, then implement subtask 1.
Merge approval remains separate at branch completion.
