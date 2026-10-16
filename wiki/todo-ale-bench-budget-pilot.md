---
title: 'TODO: Evaluate ALE-Bench as a low-cost dagi harness benchmark'
description: 'Run a controlled budget-capped ALE-Bench pilot to assess feedback use and improvement per token, with Terminal-Bench 4 as broader validation.'
tags: [todo, ALE-Bench, benchmark, harness, tokens, budget, Terminal-Bench, DeepSWE]
updated: 2026-10-16
---

Status: pending. Recorded at the user request on 2026-10-16; implementation and paid runs have not started. No due date set.

## Objective

Determine whether a small ALE-Bench subset gives a useful, repeatable measure of dagi harness improvements while keeping a before/after comparison below US$5. Native Windows execution is no longer a requirement; Linux, WSL2, and Docker are acceptable options to investigate.

ALE-Bench is promising for measuring feedback use, experiment selection, retention of successful candidates, persistence, and search efficiency. Its numerical objectives can expose improvements missed by pass/fail scoring. It is not proven cheaper or more informative per token than DeepSWE or Terminal-Bench 4.

## Work

- [ ] Pin ALE-Bench toolkit/data versions and select a small, fixed subset spanning different problem types. Reserve untouched problems for validation.
- [ ] Connect dagi to the original judge and preserve validity checks, scoring, and public/private separation. Verify reference solutions and grading before paid runs.
- [ ] Fix the model, reasoning settings, initial conditions, machine, and generated-solver CPU/time limits across harness comparisons. Keep dagi's improvement budget separate from the solver's per-case execution limit.
- [ ] Enforce a comparison-wide budget below US$5, split equally between two dagi versions. Reserve the maximum cost of in-flight requests before dispatch; include subagents, compaction, retries, and other model calls. Choose exact per-task caps after establishing request costs.
- [ ] Record input, output, reasoning, and cached-token usage without double-counting provider totals, plus API cost, elapsed time, evaluation count, validity, and code snapshots.
- [ ] Track best valid public score against cumulative tokens and dollars. Select the final program using public feedback, then evaluate it on private cases.
- [ ] Check whether valid solutions and meaningful improvements occur within the cap. If most runs remain invalid or flat, report insufficient signal rather than assuming ALE is suitable.
- [ ] Repeat promising comparisons to assess variability. Do not treat one small score difference as reliable evidence.
- [ ] Use a pinned Terminal-Bench 4 subset for broader tool-use, execution, and recovery validation when budget allows. Use DeepSWE when repository-level engineering is the target capability.
- [ ] Record costs, results, limitations, and a recommendation to adopt, revise, or reject the pilot protocol. Label capped/subset results as a development variant, not an official full-suite score.

## Evidence and cautions

ALE-Bench is not inherently cheap. Its original paper Table 4 reports historical API costs per problem of US$2.12 for GPT-4.1 mini with sequential refinement, US$0.15 with OpenHands, and US$100.33 for the strongest Gemini 2.5 Pro ALE-Agent configuration. These configurations had unequal spend and stopping behavior; they do not establish an equal-budget harness ranking or predict current dagi costs.

DeepSWE focuses on substantial repository changes, while Terminal-Bench covers broader terminal-agent tasks. ALE should initially complement these capabilities rather than stand as evidence of general coding-agent improvement. Numerical feedback is a potential advantage, but its useful signal per token must be established experimentally.

## Sources

- [ALE-Bench paper: scaffolding costs and refinement experiments](https://arxiv.org/html/2506.09050)
- [ALE-Bench toolkit](https://github.com/SakanaAI/ALE-Bench)
- [ALE-Bench session API](https://github.com/SakanaAI/ALE-Bench/blob/main/docs/session_object.md)
- [Terminal-Bench 4 release and resource protocol](https://www.tbench.ai/news/terminal-bench-4-0)
- [DeepSWE benchmark and cost reporting](https://deepswe.datacurve.ai/)
