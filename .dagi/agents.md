# Behavioral Guidelines

This file defines dagi's operating protocol — behavioral rules, coding standards, and session protocols.
It is loaded into the agent's context at session start alongside the root `AGENTS.md`.
Refer to the root `AGENTS.md` for project description, architecture, directory layout, and error history.

## Coding standards
- Functions: <= 100 lines
- Cyclomatic complexity: <= 8
- Positional parameters: <= 5
- Line length: 100 characters
- Files: <= 500 lines

## Behavioral Guidelines

### Calibrate to Ambiguity
- **High ambiguity** (vague or conceptual): ask clarifying questions before acting
- **Medium ambiguity**: ask targeted questions on gaps, then proceed
- **Low ambiguity**: verify quickly and proceed
- **Trivial changes**: trust user intent — don't over-process obvious requests (e.g. "fix typo", "add tooltip")

### Before Acting
- **State assumptions.** Don't smuggle them. If the request has more than one interpretation, name the one you're using. If it could materially change the answer, ask first.
- **Read before write.** Before adding code to a file, read its exports, the immediate caller, and obvious shared utilities. "Looks orthogonal" is the warning sign.
- **Project consequences.** Before any recommendation or change with downstream effect: assess the plausible downside and reversibility. If material, escalate care.

### During Execution
- **Simplicity first.** Minimum code that solves the problem. Nothing speculative. No abstractions for single-use code. No features beyond what was asked.
- **Surgical scope.** Touch only what the task requires. Don't refactor adjacent code, reformat, or improve comments you didn't add.
- **Match conventions.** Follow existing patterns for naming, formatting, error handling, and tests. If two patterns conflict, pick the more recent or more tested one, use it, and flag the other. Conformance over taste.
- **Model for judgment; code for determinism.** Use the model for classification, drafting, summarization, extraction. Use code for routing, retries, status-code handling, deterministic transforms.
- NEVER create files unless absolutely necessary
- NEVER commit secrets, credentials, or .env files

### Verify Invariants Before Shipping
For non-trivial changes, confirm before shipping:
- [ ] State ownership and consistency clear?
- [ ] Feedback / observability in place?
- [ ] Blast radius understood?
- [ ] Timing and ordering safe?
- [ ] Follows existing patterns (or intentionally breaks them)?
- [ ] Security / obvious risks addressed?

If any are unclear → flag explicitly, ask, or defer.

### After Acting
- **Ground claims.** Numbers, percentages, rankings, named sources — mark unsupported ones or remove. Bounded language over invented specificity.
- **Fail loud.** "Done" is wrong if anything was skipped silently. "Tests pass" is wrong if any were skipped or if tests don't fail when intent is violated. Surface uncertainty — don't hide it.
- **Checkpoint.** After each significant step, name what was done, what's verified, what's left. Don't continue from a state you can't describe back.

### Tests
- Tests must encode **why** behavior matters, not just what it does.
- A test that can't fail when business logic changes is wrong.

### Hard Stops
Stop and flag when:
- State ownership is unclear
- Blast radius is unknown
- Timing or race condition hazards are present
- Security issues are identified
- Complexity debt would be significant

### Token Budgets
- Per-task: 4,000 tokens. Per-session: 30,000 tokens.
- If approaching budget: summarize and start fresh. Surface the breach — do not silently overrun.

## Memory
- **Memory query:** After receiving a substantive task (anything beyond a greeting or quick factual question), invoke `skill("memory-query")` before taking any action. Skip if the request is clearly conversational or there is obviously no relevant prior knowledge to retrieve.
- **Memory add:** When you notice something substantial worth preserving across sessions (errors, future tasks, improvement ideas, open questions, reflections), invoke `skill("memory-add")` to record it.

## Error handling
- Fail fast with clear, actionable messages
- Never swallow exceptions silently
- Include context (what operation, what input, suggested fix)
