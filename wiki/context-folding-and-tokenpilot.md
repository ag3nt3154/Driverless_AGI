---
title: 'Context folding and TokenPilot vs dagi compaction (prefix-cache view)'
description: 'How folding and TokenPilot differ from threshold compaction; dagi cache-breakers found: screenshot elision, AGENTS.md rebuild; fork context already acts as a fold branch.'
tags: [context-folding, TokenPilot, compaction, prefix-cache, KV-cache, elide_old_ui_screenshots, build_fork_context, output_filter, eviction]
updated: 2026-10-21
---

Knowledge note from the 2026-10-21 research. Proposal 2 in
[explore-radical-architecture-proposals-2026-10](explore-radical-architecture-proposals-2026-10.md).

## Cache rule behind both

Prefix cache reuses K/V only up to the first changed byte. Layer 2+ K/V of later tokens
depend on earlier tokens through attention, so after any change at position p every token
after p is re-prefilled. dagi compaction keeps the system message (incl. both AGENTS.md
files) as a hit; the summary sits before the verbatim tail, so the **tail misses**.

## dagi compaction loses information

Trigger is a token threshold (not a task boundary) and a separate `compact` subagent writes
the summary. Mid-subtask it must guess; it tends to drop ruled-out hypotheses and the next
intended action. Repeated compaction summarizes summaries.

## Context folding (arXiv 2510.11967)

Tools `branch(description, prompt)` / `return(message)`. On return the harness removes the
branch's steps and keeps only branch call + return message. It removes the **end**, so the
prefix stays a cache hit; the agent that did the work writes the summary at the subtask
boundary. Trained with RL (FoldGRPO); reported ~10x smaller active context, matching/beating
ReAct on deep-research and SWE. Gains on untrained models (dagi's DeepSeek/free tiers) unproven.

Fold branch ≠ normal subagent: a branch starts from the **full parent context** (shared prefix,
cache hit, full knowledge); a normal subagent starts empty with a lossy brief.
dagi's inherited subagents (`build_fork_context` in `tools/subagent_api.py`) are the branch
type; typed subagents are the normal type. Missing: main agent seldom branches its own
subtasks, branch is a separate process (no ask_user/steering), threshold compaction remains.

## TokenPilot (arXiv 2606.17016)

Core idea: change context bytes only where/when cache cost is paid once or not at all
(cost = alpha·cached + uncached, alpha ≪ 1).
- **Ingestion-aware compaction:** placeholders for volatile fields (byte-identical prefix);
  deterministic cleaning of each tool output once on entry; full payload stored outside with
  a recovery tool. Reduce at ingestion = zero cache cost; pruning later = middle change = miss.
- **Lifecycle-aware eviction:** segment = messages of one sub-task; states
  active → completed (resolution evidence) → evictable (no later dependency). A separate small
  estimator model (Qwen3.5-35B-A3B in the paper), not the main agent, judges in batches every
  B=3 turns. Completed ≠ evictable (e.g. a shared file later tasks still edit). Wrong eviction
  → recovery tool reloads payload and that path is no longer truncated.
- Reported cost cut 56–61% isolated mode, 61–87% continuous mode (authors' claims).

## dagi-specific findings (source-inspected at ae9eea1a)

- `elide_old_ui_screenshots` (`agent/image_assets.py`) keeps the newest 3 computer-use
  screenshots; each new one elides an image in the middle, so RPA sessions re-prefill the
  tail every step (turn-by-turn eviction anti-pattern). Fix idea: reduce at ingestion or batch.
- `output_filter` only reduces results >= `reserve_tokens`; smaller noisy outputs enter raw.
- `_system_prompt.py` rebuilds AGENTS.md on resume: any AGENTS.md edit breaks cache near token 0.
- Deterministic eviction signals already exist: active-plan task status, child `write_handoff`,
  `{turn, step}` coordinates; a later read/write/edit of the same path supersedes an older read.
  Rules first, small local model only for undecided cases.
