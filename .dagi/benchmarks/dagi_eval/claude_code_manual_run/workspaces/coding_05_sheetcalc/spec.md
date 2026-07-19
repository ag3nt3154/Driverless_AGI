# Task: optimize the mini spreadsheet engine

`sheet.py` implements a spreadsheet engine that processes a stream of cell
updates and answers probes about cell values at checkpoints mid-stream. Make
`sheet.run(input_dir)` as fast as possible without changing its output.

## Contract
- Entry point: `sheet.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Probe values are captured at exact points in the update stream — your
  engine's state after event k must match the current implementation's.

## Input
- `<input_dir>/sheet.json` — initial cells: `{"A1": "5", "B2": "=A1+3", ...}`.
  Values are strings: either a number or a formula starting with `=`.
- `<input_dir>/updates.jsonl` — one JSON object per line, applied in order:
  `{"cell": "A1", "value": "42"}` (value may also be a formula string).
- `<input_dir>/probes.json` — `[{"after_event": k, "cells": [...]}, ...]`
  (ascending k): after applying the k-th update, report those cells' values.

## Formula language
`= expr`; expr supports: numbers, cell references, `+ - * /`, parentheses,
`SUM(C1:C40)` (rectangular range, endpoints inclusive), `IF(cond, a, b)`,
comparisons `> < ==` (result 1.0 / 0.0; IF takes any nonzero as true).
Empty/undefined cells evaluate to 0.0. Inputs are guaranteed acyclic at all
times, and division only ever occurs by nonzero constants.

## Output
`{"probes": [{"after_event": k, "values": {cell: value}}, ...],
  "final_checksum": <sum of every cell's value after all updates>}`

## Scoring
Hidden inputs of the same format (much longer update streams). Score =
baseline_runtime / your_runtime. Any output mismatch = 0.
