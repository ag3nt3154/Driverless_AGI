---
name: write-spec
description: Write a spec or design document for a new feature, subsystem, or project. The spec is written in the main agent's own words, with the user providing feedback and approval.
---

# Steps
Write a spec or design document based on the format below.

This is a writing stage. Return the artifact path, readiness assessment, and unresolved
decisions to `enter-workflow`; it owns approval and the next stage. Do not invoke
`write-plan` or `deliver`. When invoked standalone, report the spec and readiness only.

# Format

| Section | What it should contain |
|---|---|
| **1. Document status** | Title, owner, reviewers, version/date, and status: draft, in review, approved, or superseded. Links to related documents. |
| **2. Summary and problem** | Who needs this, what currently happens, why that is inadequate, and the proposed outcome. Include enough current-system context for an unfamiliar reader. |
| **3. Goals, scope, and non-goals** | Measurable outcomes, what is included, and plausible adjacent capabilities explicitly excluded. Distinguish current requirements from future possibilities. |
| **4. Requirements and behavior** | User or system workflows, inputs, outputs, business rules, defaults, validation, permissions, and edge cases. Give requirements stable IDs for later reference. |
| **5. Constraints and assumptions** | Existing integrations, compatibility obligations, deployment environment, resource limits, and external dependencies. Separate verified facts from assumptions requiring validation. |
| **6. Proposed architecture** | System boundaries, components and responsibilities, sources of truth, and data/control flow. Include a context diagram and a walkthrough of the main operation. Explain how this fits the existing system. |
| **7. Detailed contracts and state** | Interfaces, data models, units, identifiers, state transitions, invariants, error semantics, and versioning. Address ordering, concurrency, consistency, and idempotency where relevant. |
| **8. Quality and operational requirements** | Concrete expectations for performance, reliability, security, privacy, observability, capacity, and cost. Describe the design mechanisms that support them. |
| **9. Failure and recovery behavior** | What happens when dependencies fail, inputs are invalid, operations are interrupted, or only part of a change succeeds. Define retry, timeout, rollback, recovery, and degraded behavior where applicable. |
| **10. Alternatives and decisions** | Credible alternatives, including extending the existing system or doing nothing. Explain the chosen approach, trade-offs, and conditions that would justify revisiting it. |
| **11. Compatibility and release design** | Migration requirements, coexistence with existing versions, rollout controls, rollback feasibility, and retirement of old behavior. State any irreversible changes. |
| **12. Acceptance and verification** | Observable conditions for correctness and production readiness. Connect requirements to verification methods: examples, integration tests, load tests, recovery exercises, or review evidence. |
| **13. Risks and open questions** | Unresolved decisions, impact, owner, and evidence needed to resolve them. Clearly identify which block approval or implementation planning. |

# Note
1. Ensure that you are clear about the existing context before drafting. You may inspect files, code snippets, and other documentation again to ground descriptions of the current system in actual evidence.
2. Separate requirements, decisions, assumptions, and open questions. Never silently convert a guess into an approved requirement.
3. Resolve consequential ambiguity. Ask about decisions affecting behavior, scope, correctness, security, or architecture.
4. Use examples for difficult semantics. Include normal, boundary, and failure cases.
5. Maintain traceability. Each important requirement should connect to a design mechanism and an acceptance criterion.
6. Scale detail to risk. Mark irrelevant concerns "not applicable" with a brief reason; avoid boilerplate.
7. End with a readiness assessment. Identify unresolved blockers and whether the document is ready for review or implementation planning.
8. Keep the approved design current. Material implementation discoveries should update the document and its decision history.

The most useful quality check is: Could two competent implementers read this document and build systems with materially different behavior? If yes, clarify that behavior before handing it to the implementation planner.

# Saving the spec

Use the artifact directory already created by `enter-workflow`
(`wiki/tasks/YYYY-MM-DD_<task>/`); do not recompute it on resume.
The directory already exists; do not recreate or relocate it.

Save the document as `spec.md` in that directory. Return the artifact path,
a readiness assessment (ready for plan writing, or blocked with reasons), and
any unresolved decisions to the caller.

Do not invoke `write-plan`, `deliver`, or any lifecycle skill. The owner
presents spec and plan together for approval; there is no separate spec
approval gate.

When invoked standalone (no `enter-workflow` caller), save to the supplied or
default path and report the spec and readiness only.
