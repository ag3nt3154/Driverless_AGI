---
title: 'Areas to explore: radical architecture proposals from 2026-10 research'
description: 'Seven unapproved proposals (effect journal, context folding/RLM, structured board, playbook learning, harness evolution, rewind, sleep-time) mapped to dagi code and 2026 papers.'
tags: [architecture, effect-journal, durable-execution, context-folding, RLM, PatchBoard, ACE, WikiSkill, AgentRewind, sleep-time-compute]
updated: 2026-10-21
---

Research query of 2026-10-21 at main `ae9eea1a`. These are **proposals only**; nothing is
approved or built. Paper numbers are the authors' own claims from abstracts; most papers are
recent single-group arXiv preprints with no replication.

## Diagnosis

Most of the 25 open findings in `_CODEX_CODE_REVIEW_2026-10-21.md` are one class: no single
owner for "this effect started / finished / stopped" (R4, R16, R18, R21, R25, R26 stop and
ownership; R11–R14, R32–R35 delivery and identity). Each frontend (TUI, PySide, Telegram,
scheduler, board, code mode, RPA) adds its own lifecycle around the threaded `AgentLoop`.
`agent/session_log.py` is already an append-only, write-time-checked log, but it records the
conversation only, not effects.

## Proposals (recommended order: 1, 2, 4, then 3/6 on top of 1, 5 last)

1. **Effect journal / kernel (durable execution).** Every side effect (tool call, board post,
   Telegram send, RPA action, child spawn) goes through prepare → dispatch → settle, journaled
   with idempotency key `(run_id, turn, step, call_id)`. Only the kernel writes
   cancelled/stopped facts; frontends subscribe to the event stream. Smallest version: wrap
   `agent/_tool_dispatch.py`; skip effects that already have a settle record on resume.
   Sources: Stop Means Stop (arXiv 2607.14166: 6/6 frameworks fail cancel/timeout/approval;
   cancellation orphans, timeout zombies, replay double-execution), Agent libOS (2606.03895),
   Temporal/Restate.
2. **Context folding + RLM + cache-aware eviction** in place of middle-summary compaction.
   `branch(goal)` runs in the same prefix-cached context and folds into a self-written summary
   (Context Folding, arXiv 2510.11967; reuse the fork/warm-KV subagent code). Large tool
   outputs stay as REPL variables in the `code` tool with an `llm(prompt, chunk)` sub-call,
   not truncated to `.dagi/temp` (Recursive Language Models, 2512.24601: +26% vs compaction).
   Evict on cache-stable boundaries (TokenPilot, 2606.17016: 56–87% cost cut); matters for
   llama.cpp and DeepSeek prefix caching.
3. **Structured blackboard.** Peers mutate typed shared state (tasks, claims, artifacts,
   status) by schema-validated JSON Patch committed by a deterministic kernel; mentions and
   wake-ups are derived from state changes. Targets the ping-pong class, R34, and atomic
   claims (R16). Source: PatchBoard (2605.29313: 84.6% vs 30.8% LangGraph on ALFWorld, ~8×
   fewer tokens).
4. **Experience → playbook.** Automatic reflector → curator loop writing itemized delta
   bullets with helpful/harmful counters (ACE, 2510.04618); compile the grimoire wiki into
   skills (WikiSkill, 2608.27454: small models + evolved skills beat larger models; skills
   evolved by other models can beat self-evolved, so Claude Code/Codex sessions sharing
   black_grimoire can evolve dagi skills).
5. **Harness evolution with an archive.** Evolve prompts, tool descriptions and skills with a
   frozen model (Hierarchical Self-Improvement, 2608.08466, used DeepSeek-V4-Flash; gains
   vanish beyond base-model ability). Keep a variant archive with shared experience (DGM
   2505.22954; Group-Evolving Agents 2602.04837). Predict per-task outcomes before paying for
   eval (2610.13991). Preconditions: sealed evaluator (Codex S3) and far more than the 6
   `benchmarks/dagi_eval/tasks`.
6. **Rewind.** Aligned checkpoints of context + workspace (git worktree snapshot) so a retry
   rolls back both; today `revise_last_steps`/garbled recovery roll back context only.
   Source: AgentRewind (2608.14380). Builds on 1.
7. **Sleep-time compute.** In idle time (scheduler, idle peers, local llama.cpp): repo digest,
   memory consolidation, KV warm-up, speculative planning of the next TODO; tag every cached
   result with the git hash. Sources: Sleep-time Compute (2504.13171), IdleSpec (2605.22154).
