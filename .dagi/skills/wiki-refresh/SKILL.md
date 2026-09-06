---
name: wiki-refresh
description: Explicitly requested project wiki maintenance and conflict resolution, performed by the main agent through direct project investigation.
---

# Wiki refresh

Run only when explicitly invoked. The main agent performs the work itself; never dispatch
a refresh subagent. Resolve the selected project's wiki root, never the personal memory root.
A missing wiki needs code-based /init; do not silently create knowledge or migrate documents.

Inspect the wiki for broken relative links, index drift, duplicates, dated conflicted claims,
and stale descriptions. Repair unambiguous navigation directly. For factual issues, investigate
the actual source code, tests, and project evidence yourself. Ask the user when evidence
cannot settle a requirement or choice. Do not routinely require approval for evidenced fixes.

Preserve both accounts until resolved. Record resolution date, evidence and rationale, mark
superseded claims as such, and retain useful historical reasoning. Unresolved issues remain
conflicted with their conflict_detected dates. Do not promote proposed ideas to approved.
Treat source behavior as implemented behavior, and user decisions as intended behavior.

Return changed wiki paths, structural repairs, evidenced resolutions, remaining conflicts,
and any failures. Do not maintain personal todos or USER_STATUS, automatically run refresh
after adds, invent roadmap schemas, or modify AGENTS as a side effect of wiki traversal.
