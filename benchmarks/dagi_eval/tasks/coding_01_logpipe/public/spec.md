# Task: optimize the log-analytics pipeline

`pipeline.py` implements a working but slow log-analytics pipeline. Your job is
to make `pipeline.run(input_dir)` as fast as possible **without changing its
output in any way**.

## Contract
- Entry point: `pipeline.run(input_dir: str) -> dict` must keep its exact
  signature and module name. Internal restructuring is freely allowed (helper
  modules, rewritten functions, different data structures).
- For any valid input directory the returned dict must be exactly identical to
  what the current implementation returns (floats within 1e-6 relative).
- Allowed: Python stdlib, numpy, pandas, scipy.

## Input format
`<input_dir>/logs/*.log` — pipe-delimited lines: `TIMESTAMP|USER|EVENT|PATH`
- TIMESTAMP: `YYYY-MM-DDTHH:MM:SS` (whole seconds)
- EVENT: one of view, cart, checkout, purchase, ping
- Lines may appear in any order across and within files. Blank and malformed
  lines are skipped.

## What it computes
1. Sessions: per user, events sorted by time split where the gap between
   consecutive events exceeds 1800 s (a gap of exactly 1800 s stays in the
   same session).
2. Funnel: for each stage (view, cart, checkout, purchase), the number of
   sessions containing at least one event of that stage.
3. `avg_session_len_s`: mean of (last event time − first event time) per
   session, rounded to 3 decimals.
4. `daily_active`: per calendar day (from the timestamp string), the number of
   distinct users with at least one event that day.

## Scoring
Hidden inputs of this same format (much larger). Score =
baseline_runtime / your_runtime. Correctness failure on any hidden case = 0.
