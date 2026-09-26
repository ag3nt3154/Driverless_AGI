## Coding workflow

- For a new coding task, load `enter-workflow` before implementation. It owns clarification,
  planning, authorization, execution, recovery, and closure. Preserve explicit standalone
  skill scope; writing a spec or plan alone does not authorize implementation.
- Treat answers, corrections, status questions, and resumes as continuations of the current
  stage. Preserve settled decisions and approval. Reread the recorded plan and actual Git
  state after compaction or interruption; ask only about genuinely missing/conflicting state.
- For substantive project questions, use the owner's context-only entry and answer without
  preliminary approval. Ordinary conversation needs no workflow. Classify requested outcomes,
  not keywords such as "can you".
- `enter-workflow` checks the selected project's wiki before querying it and creates missing
  scaffold files while preserving existing content. Use `wiki/tasks/YYYY-MM-DD_<task>/` for
  spec and plan. Keep the explicit plan path and progress checkpoint; no custom sidecar.
- Initial joint spec/plan approval authorizes scoped implementation and reviewed subtask
  commits by the main agent. Do not request approval after each subtask or commit. After all
  subtasks, integrated verification, and final review, ask for the final branch merge/keep
  decision. Preserve separate branch-setup and merge authority; never infer consent from
  silence, status markers, or a matching commit subject.
- Default task branches use `codex/<task>`; honor an explicit project prefix. Workers and
  reviewers never delegate, stage, commit, or edit shared plan progress. Preserve the user's
  existing subagent model policy and the existing `grill-me` interview style.
