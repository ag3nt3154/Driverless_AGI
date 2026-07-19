# Task: optimize the mini query engine

`engine.py` executes a workload of queries over CSV tables. Make
`engine.run(input_dir)` as fast as possible without changing any result.

## Contract
- Entry point: `engine.run(input_dir: str) -> dict` (module name and signature
  fixed; internals free). Allowed: stdlib, numpy, pandas, scipy.
- Results must be exactly identical (floats within 1e-6 relative).

## Input format
- `<input_dir>/tables/<name>.csv` — regular CSVs with a header row. All
  monetary/quantity columns hold integers.
- `<input_dir>/workload.json` — a JSON list of query objects executed in order:

```json
{"id": "q07", "from": "orders",
 "where": [["orders.status", "=", "paid"], ["orders.amount", ">", 500]],
 "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
 "join_where": [["users.country", "=", "DE"]],
 "group_by": "users.country", "agg": "sum", "agg_col": "orders.amount"}
```

- Columns are namespaced `<table>.<column>`. `where` filters the base table,
  `join` is an inner equi-join, `join_where` filters joined rows.
- If the condition value is a JSON number the row value is compared as float;
  if it is a string, as string. Operators: `=`, `!=`, `>`, `<`.
- Without `group_by` the result is the row count (after filters/join).
  With `group_by`: dict of group key (as string) to `count`, `sum`, or `avg`
  of `agg_col` (sum/avg rounded to 6 decimals).
- Output: `{query_id: result, ...}` for every query in the workload.

## Scoring
Hidden tables and workload of the same shape (larger). Score =
baseline_runtime / your_runtime. Any result mismatch = 0.
