---
title: 'Benchmark selection for inexpensive Windows optimization runs'
description: 'Research recommendation for dagi: CO-Bench subset, optional circle-packing pilot, native Windows adapter caveats, and a sub-US$5 comparison budget.'
tags: [benchmark, CO-Bench, OPT-BENCH, ALE-Bench, circle-packing, Windows, evaluation]
updated: 2026-10-16
---

## Requirements and status

The user wants a standard benchmark to guide improvements to dagi, under US$5 per comparison run, preferably native Windows Python, with iterative numerical score improvement. This is a research recommendation, not an approved implementation decision. No benchmark execution or paid API calls were performed.

Follow-up: the user relaxed native Windows preference. Main selection criterion is harness capability measurement while minimizing token cost; do not continue ranking benchmarks primarily by native-port effort.

## ALE versus DeepSWE and Terminal-Bench 4

Research judgment: ALE is promising for measuring feedback use, experiment selection, retention of successful candidates, and persistence under a fixed spend budget. Its graded objectives can reveal improvements that do not change a binary pass result. This is not evidence of statistically superior signal per token; no controlled same-model, same-budget cross-benchmark study was identified. Repository engineering and diverse terminal tool use require supplementary evaluation, with TB4 a stronger general agent/harness candidate and DeepSWE stronger for substantial repository changes.

ALE is not inherently cheap. Original paper Table 4 (historical models/prices; 4-hour protocol) reports mean performance / API USD per problem: GPT-4.1 mini sequential 1016 / 2.12 versus OpenHands 618 / 0.15; Gemini 2.5 Pro sequential 1198 / 11.10, OpenHands 903 / 3.25, ALE-Agent base 1167 / 7.64, ALE-Agent + both methods 1879 / 100.33. Unequal spend, stopping behavior, and domain knowledge confound a pure scaffold-efficiency ranking. Paper explicitly notes early OpenHands exits. Do not mix these costs with modern DeepSWE prices to claim an apples-to-apples winner.

DeepSWE current board reports 30k output tokens / US$4.43 per task for GPT-6-Astra xhigh and 73k / US$0.24 for GLM-5.3-Flash max, both with mini-swe-agent. This illustrates that dollars and token counts differ. TB4 official release sets agent timeouts to 8 hours and reports strongly model-dependent token usage; this is a ceiling, not expected runtime or a low-cost development protocol. [TB4 release](https://www.tbench.ai/news/terminal-bench-4-0).

Proposed feasibility study: fixed small ALE task subset, same model and initial conditions, two dagi versions with identical per-task API caps and separately fixed solver CPU limits. Log input/output/reasoning/cache tokens and all auxiliary-agent costs. Select final code using public feedback; private final checks assess generalization. A best-public-score-versus-spend curve can expose search efficiency, but a private final score is essential. Invalid-at-budget tasks provide little graded signal; pilot must verify scoring and improvement occur before scaling. Repeat promising comparisons and reserve held-out problems to detect development overfitting. Any shortened/capped protocol is a development variant, not an official headline result.

## Recommendation

Use a fixed subset of CO-Bench as the primary external benchmark. It contains 36 combinatorial optimization problems and explicitly supports repeated candidate generation, evaluation, and development-score feedback, with a final test score. Candidate initial problem families: one-dimensional bin packing, graph colouring, multidimensional knapsack, and job-shop scheduling. Exact task IDs, dependencies, and case counts require validation before freezing the subset.

CO-Bench is not turnkey on native Windows: its execution utilities import fcntl and use flock. A Windows process/locking adapter needs investigation and verification; preserve the original problem definitions, validity checks, data splits, scoring, and solver time limits. Report this as a CO-Bench subset with a Windows adapter, not a full official benchmark result. Verify score parity on fixed solutions before relying on comparisons.

An optional smaller pilot is the published circle-packing n=26 task used by ShinkaEvolve: maximize the sum of radii for 26 nonoverlapping circles inside a unit square. The geometric check is amenable to native Python/NumPy, but the complete upstream runner was not verified on Windows. Use the published task and verifier rather than installing another agent as dagi. A single public mathematical task is narrow and susceptible to known-solution recall; it is insufficient evidence of general agent improvement.

## Alternatives

- OPT-BENCH explicitly measures iterative self-optimization across 20 ML and 10 NP tasks. Promising second candidate, especially CPU tabular ML; the published requirements include a large ML stack with Triton/CUDA dependencies. Native Windows compatibility is unverified and minimal task-specific dependencies would need work.
- ALE-Bench matches iterative heuristic optimization well. Its official setup requires Docker and uses shell build scripts, so it is less aligned with native Windows Python.
- SWE-bench Lite has 300 test tasks and 23 development tasks. Good for bug-fixing, but individual-task scoring is pass/fail rather than a progressively improvable objective.
- DeepSWE targets long-horizon engineering. At research time its v1.1 board lists 113 tasks; its cheapest displayed configuration averages US$0.24/task (about US$27.12 for one full pass, excluding compute). This is an observation from another agent/model, not a dagi cost prediction.
- Current Terminal-Bench documentation includes GPU and multi-container tasks and recommends cloud sandbox providers. Its exact 4.0 release contents were not verified. Do not assume an unpinned latest dataset stays fixed.

## Native Windows port feasibility follow-up

Source inspection supports a moderate adapter effort for selected CO-Bench tasks, moderate and task-dependent work for OPT-BENCH, and substantially more work for a fully native ALE-Bench judge. These are engineering judgments, not implementation estimates or demonstrated Windows compatibility.

- CO-Bench: replace fcntl locking; audit multiprocessing under Windows spawn (including cloudpickle use), output capture, and process-tree timeout cleanup. Preserve original score functions and instance splits. Avoid carrying over its reference search agents: dagi should perform the search.
- OPT-BENCH: its interpreter sends SIGINT using os.kill and has a SIGKILL fallback, so interruption and cleanup must be adapted. Reduce dependencies to those required by selected tasks; the published requirements include Triton and Linux-oriented CUDA packages. CPU tabular tasks are the first candidates. This does not mean the benchmark intrinsically requires a GPU. Validate metrics and data access task by task; NP-hard does not imply every task has a smooth objective.
- ALE-Bench: Python is a supported submission language, but code_run and evaluation use language-specific Docker images. Native execution would require replacing the container runner, building the needed generators/checkers (including Rust tools where used), configuring native compiler/runtime profiles, and implementing time/memory enforcement. Evaluation documentation uses GNU /usr/bin/time and warns of sensitivity near time limits. Keep native results separate from published Linux results. A Windows machine using WSL2/Linux containers is a substantially smaller adaptation than a native port, but was not tested here.

For all three, keep task specifications, validity/scoring rules, and splits unchanged when possible, and compare fixed valid/invalid solutions against the original evaluator. Changed compute budgets or runtimes must be disclosed. Distinguish generated-solver runtime from dagi's own optimization budget. A dollar budget bounds spending but does not guarantee useful optimization progress.

Additional sources: [OPT-BENCH interpreter](https://github.com/OliverLeeXZ/OPT-BENCH/blob/main/OPTAgent/interpreter.py), [ALE-Bench session API](https://github.com/SakanaAI/ALE-Bench/blob/main/docs/session_object.md), [ALE-Bench evaluation documentation](https://github.com/SakanaAI/ALE-Bench/blob/main/docs/evaluation.md).

## Measurement and budget proposal

For a before/after comparison, provision US$2 of model calls per dagi version, reserving the remainder below US$5 for bounded in-flight requests. Across four tasks this gives US$0.50/task/version. These are proposed spending limits, not measured costs or evidence that this budget provides enough optimization steps. Start with a small pilot to establish useful signal per dollar.

Record best valid development score against cumulative USD, elapsed time, and evaluation count; select the final candidate using development feedback and evaluate on withheld tests. Keep task-level scores and final mean official normalized score; optional area under the best-score-versus-spend curve measures improvement efficiency. Keep model, reasoning settings, data, machine, solver limits, and initial conditions fixed. Account for subagents and compaction calls and reserve each request before dispatch so a final API call cannot overshoot the budget. Run repeated seeds when validating promising changes; one budgeted comparison can be noisy.

Dagi already has benchmarks/dagi_eval with five coding-speedup tasks and one tabular ROC-AUC task. It invokes AgentLoop headlessly and records tokens/costs, so it offers an integration starting point. It is a custom scorecard, not an external standard. The inspected timeout acts at iteration boundaries and is not a hard monetary cap; cost collection alone does not enforce a budget.

## Published model and harness results (research 2026-10-16)

No verified stock Claude Code, Codex CLI, or pi coding-agent results were found for CO-Bench or OPT-BENCH in the searches performed. This is a search finding, not proof that none exist.

- CO-Bench paper Figure 3: o3-mini-medium with adapted research harnesses, 64 candidate steps: FunSearch 0.842, EoH 0.840, Greedy Refine 0.840, BestOfN 0.774, ReEvo 0.774, AIDE 0.753. Scores are means of normalized objectives, not pass rates. Classical solver baseline 0.797. [Paper](https://arxiv.org/pdf/2504.04310).
- OPT-BENCH paper Table 1, ML, 20 steps, OPT-Agent: GPT-4o IR=1.89 / EG=0.61; GPT-4.1 IR=2.15 / EG=0.58; o3-mini IR=1.35 / EG=0.65; Claude 3.7 Sonnet IR=1.35 / EG=0.53. IR compares to memory-less rollout; EG measures normalized progress from initial solution toward expert reference. These are model-with-OPT-Agent results, not Claude Code or Codex runs. The paper says NP solutions are directly constructed rather than generated as solver programs, another comparability caveat for dagi. [Paper](https://arxiv.org/html/2605.08904).
- AgentTime reports Sakana ALE-Bench on a 10-task subset, 3 requested durations per task: GPT 6 Astra + Codex 3067 (28/30 graded); GPT 5.6 Sol + Codex 2518 (30 runs); Claude Fable 5.1 + Claude Code 2398 (30 runs). Values are mean performance ratings over graded runs. Durations range from 10 to 250 minutes; not equal-dollar or full-suite results. [Primary experiment page](https://agenttimebench.com/benchmarks/sakana-ale-bench/).
- OpenRSI is a custom harness built on pi AgentSession, not stock pi. Its community reports include GPT-5.6-Sol low + OpenRSI 1544.8 on its Lite subset and Opus + OpenRSI 1625.5 on its Lite subset. Its detailed Full report identifies Opus 4.8 and reports 1432.9 across its 40-problem snapshot after selective retries, about US$135. Benchmark log separately says 1399.7 for full40, so disclose the inconsistent summaries and do not treat this as independently reproduced or a controlled comparison with AgentTime. [Log](https://github.com/AlexWortega/OpenRsi/blob/main/benchmark.md), [Full report](https://github.com/AlexWortega/OpenRsi/blob/main/full40_RESULTS.md).

ALE-Bench (Sakana/AtCoder) is different from Agents Last Exam, which some aggregators also call ALE-Bench. Exclude those pass-rate tables. A GPT model with Codex in its name evaluated through a research harness is not a Codex CLI result.

## ALE-Bench hardware and task details

The original release has 40 AHC optimization problems and a curated 10-problem Lite subset. Lite reduces public evaluation to five cases (versus 50 in Full) and reduces private cases for long contests; it is not necessarily an easier problem selection. Pin the dataset/toolkit version rather than assuming current and original counts remain identical.

ALE-Bench executes generated solutions locally in CPU-based Docker judges; the model can be an external API. No local GPU is required in that setup. The original paper used c6i.32xlarge machines with 128 vCPUs / 256 GiB RAM and explicitly no GPUs; these were parallel experimental machines, not minimum hardware. The AWS guide also lists c6i.xlarge (4 vCPU / 8 GiB, up to 2 evaluation workers), c6i.2xlarge (8 / 16, up to 4 workers), and c6i.4xlarge (16 / 32, up to 8 workers). It recommends limiting workers to physical cores and leaving capacity for visualization.

For a Windows desktop, a planning recommendation is a modern x86-64 CPU, 16 GB system RAM for low-concurrency trials, preferably 32 GB, and SSD storage. These are recommendations, not validated minimums. Root-volume provisioning defaults to 100 GB upstream, not a statement that the benchmark itself occupies 100 GB. Actual image/data usage needs measuring after selecting toolchains and tasks.

Official judging remains Docker/Linux oriented, so Windows + WSL2/Linux containers is the practical compatibility path; native Windows Python alone does not run the original judge. CPU speed and contention influence score because solutions have execution limits; local hardware is useful for within-machine dagi comparisons, but direct published-rating comparison requires matching environment and budget. Distinguish dagi's solve/improvement budget from the generated program's per-case time limit. Final private evaluation can contain hundreds or thousands of cases even after cheap public iteration.

Sources: [paper](https://arxiv.org/html/2506.09050), [AWS sizing guide](https://github.com/SakanaAI/ALE-Bench/blob/main/docs/aws_evaluation.md), [cloud defaults](https://github.com/SakanaAI/ALE-Bench/blob/main/cloud/variables.tf), [session controls](https://github.com/SakanaAI/ALE-Bench/blob/main/docs/session_object.md). No installation or execution performed.

## Reference URLs

- [CO-Bench repository and evaluation loop](https://github.com/sunnweiwei/CO-Bench)
- [CO-Bench execution utilities](https://github.com/sunnweiwei/CO-Bench/blob/main/evaluation/utils.py)
- [OPT-BENCH](https://github.com/OliverLeeXZ/OPT-BENCH)
- [OPT-BENCH requirements](https://github.com/OliverLeeXZ/OPT-BENCH/blob/main/requirements.txt)
- [ALE-Bench setup](https://github.com/SakanaAI/ALE-Bench)
- [ShinkaEvolve circle-packing verifier](https://github.com/SakanaAI/ShinkaEvolve/blob/main/examples/circle_packing/evaluate.py)
- [SWE-bench Lite](https://www.swebench.com/lite.html)
- [DeepSWE costs](https://deepswe.datacurve.ai/)
- [Terminal-Bench current dataset](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/latest)
