# The Design of Coding Harnesses

*An examination of the architectural decisions, trade-offs, and unsolved problems in the design of agentic coding tools.*

---

## What a Coding Harness Actually Is

A coding harness is a loop with opinions. At the bottom, every one of them — Claude Code, OpenAI Codex, OpenCode, Driverless AGI, and the dozens of smaller projects converging on the same idea — does the same thing: sends a prompt to a language model, receives tool calls back, executes them, feeds the results in, and repeats. Plan, act, observe, repeat. The loop is trivial. What matters is every decision *around* the loop: how context is managed when it runs long, what tools the model is allowed to call, how side effects are ordered, where trust boundaries are drawn, how state persists, and whether the human is a supervisor or a collaborator. These are the design axes along which coding harnesses genuinely differ, and they reveal fundamentally different philosophies about what an agent should be.

---

## The Context Problem

The defining constraint of every coding harness is the context window. A model can hold 128K, 200K, maybe a million tokens — but a serious coding task produces more. Dozens of file reads, hundreds of tool calls, iterative edit-test-fix cycles. The message history grows without bound. Every harness must answer the same question: *what do you do when the conversation outgrows the model's memory?*

The answers reveal deep architectural commitments.

**Naive truncation** — dropping the oldest messages — is the simplest approach and the worst. Early context often contains the task definition, key architectural decisions, and constraints that shape every subsequent action. Losing them degrades the agent's coherence mid-task, producing the characteristic failure mode where a coding agent starts contradicting its own earlier work.

**Session forking** is the approach OpenCode takes. When token usage approaches 95% of the context window, the harness summarizes the conversation and starts a *new* session with the summary as its opening context. This is clean — no messages are mutated in place — but it introduces a hard discontinuity. The agent on the other side of the fork has a summary, not a memory. Nuance is lost at the boundary.

**Progressive summarization** takes a different approach: identify safe cut points in the message history (boundaries between tool result pairs, standalone assistant messages), summarize the *middle* while preserving both the system prompt and the recent tail verbatim, and re-inject the summary in place. When the history grows again, re-summarize: fold the old summary plus the new material into a cumulative distillation. This is what Driverless AGI calls "Pi-style compaction." The agent never knows it happened — it just keeps working against what appears to be a continuous conversation. The trade-off is implementation complexity: you need to respect message pairing invariants (an assistant message with tool calls must be followed by the corresponding tool result), identify safe cut points, and handle the re-summarization loop without information loss at the seams.

**Retrieval-augmented approaches** — indexing the conversation and pulling relevant fragments back in when needed — are theoretically elegant but practically fragile. The latency of index lookups, the risk of retrieving the wrong context, and the difficulty of determining what's "relevant" in a conversation that's fundamentally sequential make this approach rare in production harnesses.

None of these solutions are *correct*. They're all lossy. The question is which kind of loss is least damaging for the kinds of tasks coding agents actually perform — and that depends on whether you're optimizing for short bursts of focused work or long-running, multi-hour sessions.

---

## The Tool Granularity Problem

Every coding harness gives the model tools. The interesting design question is *how many* and *how coarse*.

At one extreme, you could give the model a single tool: `bash`. Shell out, do anything. This is maximally flexible and minimally safe. It's also what models are often worst at — constructing long, precise shell commands with proper quoting, escaping, and error handling.

At the other extreme, you could build dozens of fine-grained tools: `read_file`, `read_file_range`, `write_file`, `append_to_file`, `create_directory`, `delete_file`, `rename_file`, `search_by_regex`, `search_by_glob`, `search_by_semantic_embedding`, and so on. This gives the harness maximum control — every file operation passes through a function you wrote — but bloats the tool schema that the model must reason about on every turn.

The harnesses that have converged on roughly the same answer are revealing. Claude Code, OpenCode, Codex, and Driverless AGI all land on a similar core set: **read**, **write**, **edit**, **bash**, **grep/search**, and **find/glob**. The edit tool is particularly interesting because every serious harness has independently arrived at the *same* design: provide the old text, provide the new text, replace exactly one occurrence. Not a line-number-based edit (too fragile — line numbers shift as the file changes). Not a full rewrite (too wasteful for surgical changes). An exact-match replacement that errors if the match is absent or ambiguous.

This convergence suggests that the tool granularity problem has a natural solution for coding: a handful of file primitives, a shell escape hatch, and search. The variation happens at the margins — whether you add LSP integration (OpenCode does, exposing diagnostics to the model), web search (Driverless AGI bundles DuckDuckGo; Claude Code uses MCP), or structured sub-task delegation.

The shell escape hatch deserves special attention. `bash` (or `shell`) is the tool that *every* harness includes and *none* can properly sandbox. You can validate file paths for `read` and `write`. You cannot meaningfully inspect a shell command and determine whether it's safe. `curl` can exfiltrate data. `pip install` can run arbitrary code. `python -c` can do anything. Some harnesses — Codex, OpenCode — put approval workflows in front of shell execution. Others — Driverless AGI — make the pragmatic bet that if you don't trust your model not to run destructive commands, the problem is upstream of the harness. This is a genuine philosophical divide, not a missing feature.

---

## Side Effects and Ordering

A subtle but consequential design decision: should the model be allowed to call multiple tools in parallel?

The OpenAI tool-calling API supports it. The model can return multiple tool calls in a single response, and the harness can execute them concurrently. For read-only operations — searching, reading files, fetching URLs — this is pure upside. For write operations, it's a minefield.

Consider an agent that wants to edit a file and then read it back to verify. If both tool calls fire in parallel, the read may execute before the edit. Consider an agent that writes to two files that import from each other. The ordering matters. Consider an agent that runs a shell command and then reads its output file. Concurrency here produces race conditions that are invisible to the model and unrecoverable by the harness.

The harnesses split on this. Claude Code and Codex generally allow parallel tool calls with provider-level configuration. Driverless AGI hardcodes `parallel_tool_calls=False` — every tool call executes sequentially, every response sees the result of every prior action. OpenCode's Go-based architecture handles this at the provider adapter level.

The trade-off is speed versus correctness. Sequential execution is slower — each tool call requires a full round-trip — but produces deterministic results. Parallel execution is faster but requires the harness (or the model) to reason about dependency ordering, which neither does reliably. For coding tasks specifically — where edit, write, and bash dominate — the sequential approach is arguably the safer default. The speedup from parallelism is small relative to the API latency, and the debugging cost of a race condition is large.

---

## The Trust Boundary

Where should humans intervene in the agent's execution? This is the design axis with the most disagreement and the highest stakes.

**Approval-gated execution** puts a human checkpoint before dangerous operations. Codex formalizes this with configurable approval policies: `Never` (auto-approve everything), `Always` (approve every tool call), `OnHazardous` (approve only shell commands and destructive file operations), `OnNonStandardizedTools` (approve MCP and custom tools). OpenCode has a permission dialog with keyboard shortcuts for allow, allow-for-session, and deny. This model is correct for teams, enterprises, and any environment where a misplaced `rm -rf` is a fireable offense.

**Sandbox-and-trust** draws the boundary differently. Sandbox what you *can* sandbox — file paths for read, write, edit, grep, find — and trust the model on what you *can't* — shell commands. This is Driverless AGI's approach, and it reflects a specific user profile: a solo developer who chose the model, configured the harness, and accepts responsibility for what it does. The absence of an approval workflow isn't negligence; it's a statement that the overhead of confirming every `git commit` and `pytest` outweighs the risk for a single-user, local-execution context.

**Plan mode** is an interesting hybrid. Rather than approving individual operations, some harnesses offer a distinct planning phase where the agent can *read* the codebase but not *modify* it. Driverless AGI implements this explicitly: in plan mode, `bash` is removed entirely, and `write`/`edit` are restricted to the plan document. The agent explores, asks questions, proposes architecture — then the human reviews the plan and switches to execution mode. This front-loads the trust decision: instead of approving each operation, you approve the *strategy*. It's a different model of human oversight — less granular, but arguably more effective, because the human reviews intent rather than implementation details.

The right answer depends entirely on context. A harness designed for a team of developers working on a shared codebase needs approval workflows. A harness designed for a solo hacker running local experiments does not. The mistake is treating one as universally correct.

---

## State, Memory, and Continuity

A coding task rarely fits in a single session. The model hits its iteration cap, the context window fills, the developer goes to lunch. How does the harness resume?

**Thread-based state** — Codex's approach — treats sessions as first-class API objects with fork, resume, and archive operations. State lives on the server. Resumption is seamless because the provider manages continuity.

**File-based state** — Driverless AGI's approach — writes every event to an append-only JSONL file. The `session_end` record includes the full raw message history. To resume, load the file and reinject the messages. State lives on the filesystem. It's less elegant than threads, but it's greppable, diffable, version-controllable, and portable.

**Database-backed state** — OpenCode's approach — stores sessions and messages in SQLite. This enables features like multi-session management, search across sessions, and file change tracking. It's more structured than JSONL but less portable.

**Instruction-file memory** — Claude Code's `CLAUDE.md` approach — stores persistent behavioral instructions in a file that's prepended to every session's system prompt. This isn't session state; it's *meta-state*. It tells the agent how to behave, not what it did last time. The agent learns across sessions by accumulating instructions in a file that the *user* edits.

These approaches aren't mutually exclusive — a harness could use JSONL for session state, SQLite for cross-session search, and instruction files for behavioral memory — but in practice, each harness picks a primary mechanism, and the choice reveals priorities. Thread-based state optimizes for seamlessness. File-based state optimizes for transparency. Database state optimizes for queryability. Instruction files optimize for behavioral consistency.

---

## Composition: Monolithic vs. Delegated Agents

As coding tasks grow complex, a single agent loop becomes a bottleneck — not computationally, but contextually. An agent researching a topic across ten web pages fills its context with fetched HTML. An agent exploring a large codebase fills its context with file contents. The *useful* information is a fraction of what was retrieved, but the retrieval process consumes the context budget.

The harnesses diverge on how to handle this.

**Monolithic agents** do everything in one loop, one context. Simple. But the context fills with intermediate results that are useful for one step and noise for every subsequent step.

**Sub-agent delegation** — Driverless AGI's model — spins up isolated agent instances with restricted tool sets. An "explore files" sub-agent gets `read`, `grep`, and `find`; it runs for a few iterations, produces a summary, and returns. Its intermediate file reads never touch the main agent's context. The main agent sees only the distilled result. This is architecturally clean but limited: sub-agents can't coordinate with each other, they return a single string, and they're synchronous.

**Multi-agent orchestration** — Codex's model — supports spawning independent agents that communicate via message passing (`spawn_agent`, `send_message`, `wait_agent`). Agents can run in parallel, coordinate, and share results. This enables complex workflows but introduces coordination complexity: deadlocks, message ordering, and the fundamental difficulty of describing a multi-agent workflow to a model that thinks in sequences.

**Plugin-based composition** — Claude Code's model — defines reusable agent configurations (plugins) that can be triggered by name or by pattern matching against the user's request. The "feature-dev" plugin defines a seven-phase workflow; the "Ralph Wiggum" plugin implements deterministic retry loops where the same prompt is fed repeatedly until a completion condition is met. This is the most structured approach — it codifies *workflows*, not just capabilities.

The pattern here is a spectrum from simplicity to power, with the usual inverse relationship to debuggability. A sub-agent that returns a string is easy to reason about. A multi-agent system with message passing is powerful but opaque. A plugin that defines a seven-phase workflow is productive but rigid. Each harness picks its point on this spectrum based on its target user.

---

## The Provider Coupling Spectrum

Should a coding harness be built for one model or many?

**Vertical integration** — building the harness *for* a specific model — enables deep optimization. Claude Code can exploit Anthropic-specific features: extended thinking, model-specific tool formatting, provider-managed context. The harness and the model evolve together. The trade-off is lock-in. If Anthropic changes pricing, deprecates a model, or a competitor produces something dramatically better, switching means switching harnesses.

**Horizontal abstraction** — building the harness against a generic API — sacrifices depth for portability. Driverless AGI and OpenCode both target the OpenAI chat completions API, which most providers support (directly or via adapter). You can swap models by changing a configuration key: GPT-4o today, Claude Opus tomorrow, a local Llama next week. The trade-off is that you can't exploit provider-specific features without conditional code paths, and the lowest-common-denominator API constrains what the harness can do.

**Multi-provider with adapters** — OpenCode's approach — supports many providers natively (OpenAI, Anthropic, Google, Groq, AWS Bedrock, Azure, GitHub Copilot) through per-provider SDK adapters. This is the most work to maintain but provides the broadest compatibility without sacrificing provider-specific features.

The choice reflects a bet about the future. Vertical integration bets that one provider will stay dominant. Horizontal abstraction bets that the model layer will commoditize. Multi-provider adapters bet that the market will fragment. All three bets are currently plausible, which is why all three approaches are actively maintained.

---

## Identity: The Persona Question

Most coding harnesses ship with a generic system prompt: "You are a helpful coding assistant." A few make a different choice.

Driverless AGI defines its agent's personality in a separate `SOUL.md` file — a fully realized character with specific speech patterns, behavioral tendencies, and a defined relationship to the user. The agent pushes back on bad ideas, asks pointed questions, and maintains a tone that's collaborative rather than servile.

This seems cosmetic. It isn't.

A generic assistant complies. It does what you ask, in the order you ask it, with minimal friction. This is efficient when your instructions are correct and dangerous when they're not. A character-driven agent *argues*. It introduces friction at the moments where friction is most valuable: before the agent executes a plan that the user hasn't thought through, or when the user's assumptions about the codebase are wrong.

The persona also affects how the *user* interacts with the agent. People communicate differently with a "helpful assistant" than with a character that has opinions. They provide more context, ask better questions, and engage more critically with the agent's responses. The persona is a UX mechanism that shapes the quality of the input, not just the output.

Most harnesses don't do this, and there's a reasonable argument against it: a persona that's wrong for the user is worse than no persona at all. But the underlying insight — that the system prompt shapes the interaction dynamic, not just the response style — is one that every harness designer should consider.

---

## The Unsolved Problems

Despite rapid convergence on basic architecture, several problems remain genuinely unsolved in coding harness design.

**Verification.** How does the harness know the agent actually *solved* the task? Iteration caps are a stopgap. Running tests is better but requires tests to exist. Deterministic completion detection — Claude Code's "Ralph loop" approach, where a stop hook validates completion — works for well-defined tasks but not for open-ended ones. No harness has a reliable answer to "is this done?"

**Cost control.** A long-running agent session can burn through significant API spend. Harnesses track token counts and display costs, but none have robust mechanisms for *limiting* spend. An agent that's stuck in a loop, calling tools that don't resolve the problem, will iterate until the cap — and the cap is set in iterations, not dollars.

**Multi-file coherence.** Agents edit files sequentially. When a change to one file requires coordinated changes to three others, the agent must hold the full dependency graph in context and execute the changes in the right order. As projects grow, this becomes the primary failure mode: not incorrect edits, but *incomplete* edits that leave the codebase in an inconsistent state.

**Recovery from bad edits.** When an agent makes a mistake — and it will — the recovery path is manual. Git provides the safety net (`git diff`, `git checkout`), but no harness integrates recovery into the loop itself. An agent that detects its own mistake, reverts the change, and tries a different approach is the obvious next step, but it requires the agent to reason about its own failure modes, which current models do inconsistently.

---

## Convergence and Divergence

The coding harness space is converging on architecture and diverging on philosophy. The tool sets are nearly identical. The loop structure is universal. Context management, while varied in implementation, addresses the same constraint. The real differences — the ones that will determine which approaches survive — are philosophical: how much you trust the model, how much you trust the user, whether the harness should be a product or a platform, and whether provider coupling is a feature or a liability.

These are not engineering questions. They're design values. And the diversity of current answers is a sign that the field hasn't settled — which means it's still worth building your own.
