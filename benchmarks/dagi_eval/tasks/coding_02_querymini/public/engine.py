"""Mini query engine over CSV tables. Contract: run(input_dir) -> dict."""
import csv
import json
from pathlib import Path

OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def load_table(input_dir, name):
    rows = []
    with open(Path(input_dir, "tables", name + ".csv"), newline="",
              encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            rows.append({f"{name}.{k}": v for k, v in raw.items()})
    return rows


def matches(row, conds):
    for col, op, ref in conds:
        v = row[col]
        if isinstance(ref, (int, float)):
            try:
                v = float(v)
            except ValueError:
                return False
        if not OPS[op](v, ref):
            return False
    return True


def run(input_dir):
    workload = json.loads(
        Path(input_dir, "workload.json").read_text(encoding="utf-8"))
    out = {}
    for q in workload:
        rows = load_table(input_dir, q["from"])          # reloads CSV per query
        conds = [tuple(c) for c in q.get("where", [])]
        rows = [r for r in rows if matches(r, conds)]
        if "join" in q:
            j = q["join"]
            other = load_table(input_dir, j["table"])     # reloads CSV per query
            left = f"{q['from']}.{j['on_left']}"
            right = f"{j['table']}.{j['on_right']}"
            joined = []
            for r in rows:
                for o in other:                           # nested-loop join
                    if r[left] == o[right]:
                        merged = dict(r)
                        merged.update(o)
                        joined.append(merged)
            jconds = [tuple(c) for c in q.get("join_where", [])]
            rows = [r for r in joined if matches(r, jconds)]
        if "group_by" in q:
            groups = {}
            for r in rows:
                groups.setdefault(str(r[q["group_by"]]), []).append(r)
            agg, col = q["agg"], q.get("agg_col")
            res = {}
            for key in sorted(groups):
                grp = groups[key]
                if agg == "count":
                    res[key] = len(grp)
                elif agg == "sum":
                    res[key] = round(sum(float(r[col]) for r in grp), 6)
                elif agg == "avg":
                    res[key] = round(sum(float(r[col]) for r in grp) / len(grp), 6)
            out[q["id"]] = res
        else:
            out[q["id"]] = len(rows)
    return out
