"""Mini query engine over CSV tables. Contract: run(input_dir) -> dict.

Optimized: tables are loaded once per input_dir (cached), joins use pandas'
hash-based merge instead of a Python nested loop, and row filters / group-by
aggregations are vectorized with numpy/pandas instead of per-row Python
loops. Output is kept byte-for-byte identical to the original reference
implementation (same string-vs-numeric comparison semantics, same rounding,
same key ordering).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

_TABLE_CACHE = {}


def _load_table(input_dir, name):
    key = (input_dir, name)
    df = _TABLE_CACHE.get(key)
    if df is None:
        path = Path(input_dir, "tables", name + ".csv")
        # dtype=str + keep_default_na/na_filter=False keeps every cell as the
        # exact raw string csv.DictReader would have produced (no implicit
        # NaN/type coercion), which the comparison semantics depend on.
        df = pd.read_csv(
            path, dtype=str, keep_default_na=False, na_filter=False
        )
        df.columns = [f"{name}.{c}" for c in df.columns]
        _TABLE_CACHE[key] = df
    return df


def _cond_mask(df, col, op, ref):
    is_numeric_ref = isinstance(ref, (int, float))
    if is_numeric_ref:
        s = pd.to_numeric(df[col], errors="coerce")
        valid = s.notna().to_numpy()
        if op == "=":
            cmp = (s == ref).to_numpy()
        elif op == "!=":
            cmp = (s != ref).to_numpy()
        elif op == ">":
            cmp = (s > ref).to_numpy()
        else:  # "<"
            cmp = (s < ref).to_numpy()
        return cmp & valid
    s = df[col]
    if op == "=":
        return (s == ref).to_numpy()
    if op == "!=":
        return (s != ref).to_numpy()
    if op == ">":
        return (s > ref).to_numpy()
    return (s < ref).to_numpy()  # "<"


def _where_mask(df, conds):
    mask = np.ones(len(df), dtype=bool)
    for col, op, ref in conds:
        mask &= _cond_mask(df, col, op, ref)
    return mask


def _apply_join(df, q, input_dir):
    j = q["join"]
    other = _load_table(input_dir, j["table"])
    left_col = f"{q['from']}.{j['on_left']}"
    right_col = f"{j['table']}.{j['on_right']}"
    merged = df.merge(other, left_on=left_col, right_on=right_col, how="inner")
    jconds = q.get("join_where", [])
    if jconds:
        merged = merged[_where_mask(merged, [tuple(c) for c in jconds])]
    return merged


def _apply_group_by(df, q):
    col = q["group_by"]
    agg = q["agg"]
    agg_col = q.get("agg_col")

    res = {}
    if agg == "count":
        s = df.groupby(col).size()
        res = {str(k): int(v) for k, v in s.items()}
    elif agg in ("sum", "avg"):
        numeric = pd.to_numeric(df[agg_col])
        grouped = numeric.groupby(df[col])
        s = grouped.sum() if agg == "sum" else grouped.mean()
        res = {str(k): round(float(v), 6) for k, v in s.items()}

    return dict(sorted(res.items()))


def run(input_dir):
    input_dir = str(input_dir)
    workload = json.loads(
        Path(input_dir, "workload.json").read_text(encoding="utf-8"))
    out = {}
    for q in workload:
        df = _load_table(input_dir, q["from"])
        conds = q.get("where", [])
        if conds:
            df = df[_where_mask(df, [tuple(c) for c in conds])]
        if "join" in q:
            df = _apply_join(df, q, input_dir)
        if "group_by" in q:
            out[q["id"]] = _apply_group_by(df, q)
        else:
            out[q["id"]] = int(len(df))
    return out
