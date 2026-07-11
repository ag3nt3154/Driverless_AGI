# DAGI Self-Improvement Moonshots — Far-Fetched Architecture & Process Ideas

**Date:** 2026-07-11
**Status:** Ideation / design sketch (not scheduled work)
**Scope:** Architectural and process-flow changes to make DAGI a self-learning, self-improving agent harness. Deliberately far-fetched — these are chosen for maximum long-run compounding gains, not near-term feasibility.

---

## Context: What DAGI Already Has (the seeds)

These ideas are extensions of infrastructure that already exists in the repo:

- **Session logs** — append-only JSONL per session (`.dagi/logs/`) with full message history, tool calls, token counts, and cost.
- **Memory wiki** — topic-organized persistent wiki (`dagi-memory/wiki/`) with BM25 retrieval and wiki index injection at session start.
- **`review-session` skill** — deep-reads sessions and accumulates findings into a running cross-session review report (`.dagi/self-review/`).
- **`improve-yourself` workflow** — picks a review item, researches prior art, runs baseline/after tests in an isolated snapshot (`snapshots/`), compares metrics, writes a verdict to `TODO.md`.
- **Auto-loaded project tools** — `.dagi/tools/*.py` are discovered and registered at startup.
- **Eval benchmark plans** — DAGI eval benchmark design spec and implementation plan (5 coding + 1 DS task harness) already committed.
- **Subagent architecture** — pipe subagents (`explore_files`, `web_research`, `worker`, `review`, `plan`) with per-subagent prompts and configs.

---

## The Ideas (ordered by expected compounding value)

### 1. Experience Distillation — Sessions as Training Data for Prompts, Not Models

**Concept:** Treat every session JSONL as a trajectory in an offline RL dataset — but the "policy" being optimized is the harness's prompt/skill/tool ecosystem, not model weights.

**Mechanism — a continuous background distillation loop:**

1. Cluster trajectories by task type (bug fix, refactor, research, …).
2. For each cluster, diff high-cost trajectories against low-cost ones for the same task class: what did the fast one know or do that the slow one didn't?
3. Compile that delta into a new or amended skill, prompt fragment, or tool default.
4. **Verify** by *replaying* the slow trajectory's task in a snapshot with the amendment applied.

**Key inversion:** Today `review-session` produces reports for a human. This produces *executable artifacts* (skills, prompt patches) that are validated against replayed history before merging. Session logs become a regression suite for the harness's own prompt engineering.

**Why it compounds:** This is the closest thing to gradient descent achievable without touching weights, and it compounds forever — every session adds data.

---

### 2. The Harness as Its Own Genome — Population-Based Self-Modification

**Concept:** `improve-yourself` currently tests one change in one snapshot. Go full evolutionary.

**Mechanism:**

- Maintain a *population* of 4–8 DAGI variants as branches — different system prompts, compaction strategies, tool descriptions, subagent configs.
- Every night, run the eval benchmark across the population, plus a fitness signal from real sessions (cost per completed task, user-correction rate).
- **Cull** losers; **mutate** winners (an LLM proposes mutations, informed by the distillation loop in #1); **cross over** (take the compaction config from variant A, the planner prompt from variant B).

**Far-fetched part:** Real user sessions are served by the current champion, but the challenger *shadow-runs* the same tasks in a sandbox for outcome comparison — A/B testing of the entire harness with the actual workload as the benchmark.

---

### 3. Reflexive Tool Synthesis with Usage-Driven Lifecycle

**Concept:** The agent compiles its own habits from interpretation to code, the way humans automate motor skills.

**Mechanism:**

- Detect (from logs) when the agent performs the same multi-step `bash`/`grep`/`edit` dance three times across sessions.
- A background agent writes a dedicated tool for it, generates tests, and registers it provisionally in `.dagi/tools/` (already auto-loaded).
- Tools carry usage telemetry. Tools that are never picked or frequently error get **demoted** to skills (guidance instead of code), then garbage-collected.

**End state:** The tool registry becomes a *living cache of proceduralized behavior*. Most routine work becomes one purpose-built tool call instead of ten generic ones.

---

### 4. Predictive Self-Model — A Cost/Success Oracle Over the Agent's Own Behavior

**Concept:** Train (or few-shot from logs) a small model/heuristic that, given a task description, predicts expected iterations, expected cost, probability of needing user correction, and the likeliest failure mode.

**Three uses:**

1. **Routing** — cheap model for tasks the oracle says are easy; expensive model + plan mode for risky ones.
2. **Anomaly detection** — mid-session, if actual iterations blow past prediction 2×, trigger an automatic "step back and re-plan" interrupt (the machine version of noticing you're flailing).
3. **Calibration flywheel** — every finished session is a new labeled example, so the oracle improves as a side effect of normal use.

**Why it matters:** The self-model upgrades all the other loops from "react to failure" to "anticipate failure."

---

### 5. Counterfactual Replay Engine

**Concept:** Because everything is logged, DAGI can do something humans can't: rewind.

**Mechanism:**

- Build a replay harness that takes a completed session, truncates it at iteration N, swaps in a different decision (different model, different skill invoked, an injected hint), and rolls forward in a sandbox.
- Every interesting session becomes a *branching experiment*: "would the failure at iteration 30 have been avoided if memory retrieval had surfaced page X at iteration 5?"
- If yes → direct evidence for changing the retrieval trigger, not a hunch.

**Why it matters:** Counterfactual replay turns self-review from anecdotes into **causal attribution**. It is the substrate that makes ideas #1 and #2 scientifically honest rather than vibes-driven.

---

### 6. Memory with Epistemics — Beliefs That Decay, Fight, and Get Audited

**Concept:** Upgrade the wiki from "notes" to a belief system.

**Mechanism:**

- Every page/claim gets metadata: **confidence**, **provenance** (which session, what evidence), **last-verified date**, and a **contradiction index**.
- A sleeping-hours "dream" process rereads the wiki against the current codebase and recent sessions, flags stale or contradicted beliefs, and re-verifies or retires them.
- When retrieval surfaces a claim, the agent sees its confidence and age. A wrong claim that caused a failed action gets its confidence slashed automatically (the failure is traceable via logs).
- Contradictions aren't errors — they spawn investigation tasks onto the work queue.

**Why it matters:** Most agent-memory systems rot because writes are cheap and audits never happen. Making memory *pay rent* — every belief periodically re-earning its place — is what lets the wiki stay load-bearing at 10,000 pages instead of becoming a landfill at 200.

---

### 7. Self-Generated Curriculum — The Agent Writes Its Own Benchmark

**Concept:** The planned eval benchmark is static — it will saturate. Instead, have DAGI mine its own failures into new eval tasks.

**Mechanism:**

- Every session where the user corrected the agent, or where it exceeded predicted cost, becomes a candidate benchmark item: task prompt + repo snapshot + a checker derived from what "fixed" eventually looked like.
- The benchmark grows *precisely along the frontier of the agent's incompetence* — a curriculum that auto-adjusts difficulty.

**Combined with #2:** The population is always being selected against the things the current champion is worst at — the AlphaZero-style self-play dynamic, applied to a harness.

---

### 8. Economic Self-Awareness — An Internal Budget Market

**Concept:** Compute allocation becomes learned rather than hardcoded. `max_iterations: 20` is central planning; this is a market.

**Mechanism:**

- Every session gets a token/dollar budget; subagents *bid* for it.
- `explore_files` requests 50k tokens with an expected-information-value estimate; the main loop grants or haggles.
- Over time the oracle (#4) learns which subagent spends actually correlate with task success, and starves the ones that don't.

**Observable win:** Cost-per-completed-task trends down without anyone tuning constants.

---

### 9. Shadow Apprentice — Continuous Fine-Tune Distillation of the Harness's Judgment

**Concept:** The most far-off idea. Periodically fine-tune a small local model on accumulated trajectories — not to replace the frontier model, but to grow an organ that has internalized *your* projects, *your* corrections, *your* conventions.

**Three roles for the apprentice:**

1. The **routing oracle** for #4.
2. A **draft-generator** whose outputs the big model only verifies/edits.
3. A **"taste model"** that scores candidate self-modifications in #2 before paying for real eval runs.

**Why it matters:** No frontier model API will ever have this project-specific internalization. When local models get good enough, this is where the moat is.

---

### 10. Constitutional Self-Modification Protocol

**Concept:** If #1–#3 all write to prompts, skills, and tools autonomously, the system needs an immune system or it will drift into degeneracy (self-modifications that game the eval, prompt patches that conflict).

**Mechanism:**

- A **constitution layer**: a small set of invariant files the self-modification loops may never touch.
- A required **amendment record** per change: what changed, what evidence, which replays validated it, and an auto-revert trigger.
- A periodic **constitutional review** session where a fresh agent instance — with no stake in the changes — audits the amendment log for gaming.

**Why it matters:** This sounds like bureaucracy but it's the enabling technology. The other loops can only be made fully autonomous once rollback and audit are structural rather than manual.

---

## Recommendation & Rough Roadmap

**Bet on impressiveness-per-effort:** **#1 (experience distillation)** and **#5 (counterfactual replay)** are the pair to aim at first — replay makes distillation verifiable, and together they turn the existing logs from an archive into a flywheel. **#7 (self-generated curriculum)** keeps the whole thing from plateauing. Everything else layers on top of those three.

Suggested layering:

| Phase | Ideas | Why this order |
|-------|-------|----------------|
| 1 | #5 Counterfactual replay | Substrate — makes every later change verifiable against real history |
| 2 | #1 Experience distillation | First autonomous improvement loop, validated by replay |
| 3 | #7 Self-generated curriculum | Keeps the eval frontier moving as the agent improves |
| 4 | #3 Tool synthesis, #6 Memory epistemics | Proceduralize habits; keep the knowledge base honest |
| 5 | #4 Self-model, #8 Budget market | Anticipatory behavior and learned compute allocation |
| 6 | #2 Population evolution, #10 Constitution | Full autonomy — requires structural rollback/audit first |
| 7 | #9 Shadow apprentice | Long-horizon; waits on local-model capability |
