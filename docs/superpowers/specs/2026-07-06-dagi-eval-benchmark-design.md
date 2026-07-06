# DAGI Eval Benchmark — Design

**Date:** 2026-07-06
**Status:** Approved design, pending implementation plan

## Purpose

A self-contained evaluation benchmark for DAGI. Any (dagi version × model) combination
produces a comparable scorecard row: quality scores vs wall time and token cost. Run it
after each agent improvement or model change to see whether the score-per-cost frontier
moved.

Two subtask families:

1. **Coding** — optimize a working-but-slow system for maximum speedup while preserving
   exact output behavior (5 tasks).
2. **Data science** — maximize held-out ROC-AUC on a frozen synthetic tabular dataset
   (1 task).

No composite score. The scorecard reports separate columns; the "benchmark result" is
the Pareto frontier of score vs cost across runs, judged by the user.

## Decisions log

| Decision | Choice |
|---|---|
| Purpose | General (dagi version × model) scorecard harness |
| Coding scoring | Speedup vs baseline (`baseline_time / agent_time`), correctness as a gate |
| Coding task count | 5 fixed tasks, all run every time, mean speedup |
| DS data source | Synthetic, generated once with a fixed seed, frozen and committed |
| DS labels | Stochastic — `Bernoulli(p(x))`, hard Bayes ceiling, no perfect score possible |
| Scorecard | Separate columns only, no composite / efficiency formula |
| Budgets | `max_iterations` (50) + harness wall-clock timeout (default 20 min/task); cost recorded, not capped |
| Trials | One trial per task per run |
| Architecture | Standalone in-process harness driving `AgentLoop` directly (Harbor-adapter pattern, no Docker) |

## Architecture

```
benchmarks/dagi_eval/
├── run.py                # CLI entry: python -m benchmarks.dagi_eval.run
├── harness.py            # workspace setup, AgentLoop invocation, timeout enforcement
├── scoring.py            # evaluators: correctness gate, timing, held-out metric
├── results.jsonl         # append-only scorecard history (committed to git)
└── tasks/
    ├── coding_01_logpipe/
    │   ├── public/       # spec.md + slow implementation — copied into agent workspace
    │   └── hidden/       # pristine baseline copy, correctness inputs, timing inputs,
    │                     # gold_solution/ (hand-optimized, for harness self-test)
    ├── coding_02_querymini/    # same shape
    ├── coding_03_simgrid/      # same shape
    ├── coding_04_dedup/        # same shape
    ├── coding_05_sheetcalc/    # same shape
    └── ds_01_tabular/
        ├── generator.py  # seeded; run once to freeze the dataset, outputs committed
        ├── public/       # spec.md, train.csv, test_features.csv
        └── hidden/       # test_labels.csv, baseline script, gold_solution/
```

### Run flow (per task)

1. Harness creates a fresh temp workspace and copies the task's `public/` into it.
2. Builds an `AgentLoop` from `benchmarks/config_benchmark.yaml` (pattern lifted from
   `benchmarks/harbor/agent.py`, minus Docker), with `config.project_path` = workspace.
3. Runs the task instruction under the wall-clock timeout. On expiry the loop is stopped
   at the next iteration boundary.
4. Collects `tokens_in / think / out / cost` from `SessionTracker`.
5. `scoring.py` evaluates workspace artifacts against `hidden/` in fresh subprocesses.
6. Appends one row to `results.jsonl`.

### Isolation rule

`hidden/` is never copied into the workspace and its path never appears in the task
instruction. The agent contract is purely file-based: the edited system in the
working directory (coding) or `predictions.csv` (DS). This is a
self-evaluation harness, not an adversarial sandbox — hidden-directory separation plus
the path guard is sufficient.

### Scorecard row schema (`results.jsonl`)

```json
{
  "timestamp": "...",
  "dagi_git_commit": "<sha>",
  "dirty_tree": false,
  "model": "<model id from config>",
  "label": "<free-text note, e.g. 'after prompt rework'>",
  "coding_score": 12.4,
  "coding_tasks": {"coding_01_logpipe": {"speedup": 8.1, "correct": true, "error": null}, "...": {}},
  "ds_score": 1.61,
  "ds_auc": 0.79,
  "wall_time_s": 4210,
  "tokens_in": 0, "tokens_think": 0, "tokens_out": 0,
  "cost_usd": 0.0,
  "iterations": 0,
  "timed_out": [],
  "errors": []
}
```

`coding_score` = mean speedup across the 5 tasks. Per-task detail is always recorded so
outlier-driven means are inspectable.

## Coding subtask — "optimize the slow system"

Each task ships a **working, correct, deliberately slow mini-system** in `public/`. The
agent must make it fast while preserving exact output behavior. Slowness is layered
across multiple bottlenecks so a large score requires finding all of them; no single
textbook algorithm is the answer. `spec.md` states: the entry-point contract (identical
outputs required), internal restructuring freely allowed, stdlib + numpy/pandas/scipy
permitted, and that scoring is speed on hidden inputs of the described shape with
correctness as a gate.

### Tasks

1. **`coding_01_logpipe`** — log-analytics pipeline (~300 lines, several modules):
   parse raw logs → sessionize by user with a time-gap rule → funnel/retention
   aggregates → report dict. Layered bottlenecks: regex misuse in parsing, quadratic
   sessionization, repeated full scans in aggregation, redundant datetime parsing.
2. **`coding_02_querymini`** — tiny in-memory query engine over CSV tables executing a
   fixed workload of ~30 queries (filters, joins, group-bys). Naive engine: nested-loop
   joins, full scans per query. Wins are workload-aware: build the right indexes once,
   join reordering, predicate pushdown.
3. **`coding_03_simgrid`** — entity simulation on a 2D world over many timesteps
   (movement, radius-based interactions, state updates) with a final statistics summary.
   Naive: all-pairs interaction checks per step in Python loops. Wins: spatial hashing,
   vectorization, incremental updates, exploiting problem structure (most entities idle).
4. **`coding_04_dedup`** — near-duplicate detector over ~50k short documents: normalize,
   pairwise token-overlap similarity, output sorted clusters. Naive: O(n²) comparison +
   per-pair re-tokenization. Wins require candidate generation (signature buckets /
   inverted index) plus the mundane layers — while preserving the canonical sorted
   output despite a restructured computation order.
5. **`coding_05_sheetcalc`** — **the difficulty jump.** Mini spreadsheet engine: cells
   with values or formulas (arithmetic, ranges like `SUM(A1:C100)`, references,
   conditionals) + a stream of ~100k cell-update events; probe cells are checked at
   checkpoints throughout the stream. Naive engine re-parses and re-evaluates the whole
   sheet after every update. Real speedup requires an architectural rewrite: parse once,
   dependency graph, dirty-subgraph recomputation in topological order, diamond
   dependencies without double-evaluation, efficient range aggregates. Mid-stream probes
   make staleness or wrong invalidation order fail correctness immediately. Expected
   spread: weak combos get ~2× or break correctness; strong ones 100×+.

### Scoring protocol (per task)

1. **Correctness gate** — evaluator runs the agent's edited system in a fresh subprocess
   (own timeout, scratch `cwd`) on ~10 hidden inputs (edge cases + medium sizes; same
   format as public data, different content). Output must exactly match the pristine
   baseline's output (floats within tolerance; outputs deterministic by construction).
   Any mismatch, exception, import failure, or missing artifact → task score **0**,
   error recorded.
2. **Timing** — on hidden large inputs: 1 warmup call, median of 5 runs, per-call
   timeout 120 s (timeout → score 0). The baseline (pristine copy in `hidden/`) is
   timed fresh in the same session on the same machine, so hardware and load cancel out.
3. **Score** = `baseline_time / agent_time`. 1.0 = parity with naive; unbounded upside.

Anti-gaming: timing/correctness inputs are hidden (no output hardcoding); the evaluation
subprocess runs outside the workspace so agent-time precomputation only helps for inputs
the agent has seen, which are not the scored ones.

## Data science subtask — `ds_01_tabular`

### Dataset

Synthetic binary classification, ~30k train / 10k test rows, ~25 features. Generated by
a seeded `generator.py`, run once; outputs committed and frozen.

**Labels are stochastic:** the generator computes a true probability `p(x)` per row and
draws `y ~ Bernoulli(p(x))`. Even an oracle knowing `p(x)` exactly cannot reach AUC 1.0
— a hard Bayes ceiling keeps the top of the scale discriminative and nothing is
perfectly reverse-engineerable.

**`p(x)` is a complex mixture of regimes**, not one formula: latent segments (driven by
a categorical + a continuous threshold) where *different* feature interactions drive
the target per segment; smooth nonlinearities (products, ratios, a periodic term);
plus:

- a high-cardinality categorical with signal in rare levels
- informative missingness (missingness correlates with target)
- redundant/correlated features and pure-noise columns
- a leaky-looking trap column (spuriously correlates with target in train; the data
  dictionary hints at the mechanism) — rewards validation over blind trust

**Calibration targets** (verified empirically before freezing): oracle AUC ≈ 0.90,
baseline AUC ≈ 0.68 — a wide, noise-capped band. Adjust noise scale and re-generate
until targets hold, then freeze.

### Contract & scoring

`public/`: `train.csv` (labels included), `test_features.csv`, `spec.md` with data
dictionary and contract: *produce `predictions.csv` with columns `id, probability`;
scored by ROC-AUC on held-out labels.* `hidden/`: `test_labels.csv`, baseline script.

**Baseline:** logistic regression with basic preprocessing (median impute, one-hot,
standardize) — deliberately modest so feature engineering, missingness handling, model
choice, and validation all convert into visible lift.

**Score:** `ds_score = (agent_auc − 0.5) / (baseline_auc − 0.5)`. 1.0 = baseline
parity; oracle ≈ 2.2. Missing/malformed `predictions.csv`, wrong row count, or
non-numeric probabilities → 0 with reason recorded.

Agent-side stochasticity (model fitting) is accepted noise under the one-trial policy;
the dataset itself is frozen.

## Harness mechanics

### CLI

```
conda run -n dagi python -m benchmarks.dagi_eval.run \
    --model <id> [--label "note"] [--task coding_05_sheetcalc] [--timeout-min 20]
```

- `--task` runs a subset (useful during task development); default runs all six.
- `--solver gold|naive` replaces the agent with a canned solution (see Testing).

### Agent invocation

- `resolve_model_config` from `benchmarks/config_benchmark.yaml`; a `dagi_eval` section
  overrides settings (`max_iterations: 50`).
- Standard tool set **except `ask_user`**, which is replaced by a stub returning
  "proceed with your best judgment" — runs are unattended.
- Wall-clock timeout enforced by the harness thread; on expiry the loop stops at the
  next iteration boundary and existing artifacts are scored.
- `dagi_git_commit` + dirty-tree flag captured via `git rev-parse HEAD` / `git status`.

### Error handling

| Failure | Handling |
|---|---|
| Agent crash / API death mid-task | Catch, record error, score artifacts as-is (usually 0) |
| Wall-clock timeout | Score artifacts as-is; task listed in `timed_out` |
| Solution won't import / crashes / hangs in eval | Eval subprocess timeout; score 0, stderr snippet recorded |
| Correctness failure | Score 0; failing case ids recorded |
| Malformed `predictions.csv` | ds_score 0, reason recorded |
| One task fails | Remaining tasks still run; row is complete with per-task detail |

All evaluation runs in fresh subprocesses with scratch `cwd` (crash/hang isolation).

## Testing the benchmark itself (no LLM tokens)

- Each task's `hidden/gold_solution/` holds a hand-written optimized solution.
- `--solver naive` runs the pipeline with the unmodified slow code → must pass
  correctness and score ≈ 1.0. `--solver gold` → must pass correctness and show real
  speedup / AUC lift.
- This validates every gate, the timing protocol, and scoring math end-to-end, and is
  the regression test whenever a task is modified.
- Unit tests for `scoring.py`: score formulas, malformed-input handling, timeout paths.

## Documentation

On implementation completion, update `README.md` (new "DAGI Eval Benchmark" subsection
under Running Benchmarks) and `TODO.md`, per project instructions.
