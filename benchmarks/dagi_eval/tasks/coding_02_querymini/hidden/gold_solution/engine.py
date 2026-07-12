"""Gold solution: load+coerce once, hash-join via prebuilt indexes.

Join iteration order matches the naive engine (per base row, other-table rows
in CSV order), so joined-row sequences — and therefore counts and integer
sums — are identical.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

OPS = {
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


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

    tables = {}

    def get_table(name):
        if name not in tables:
            with open(Path(input_dir, "tables", name + ".csv"), newline="",
                      encoding="utf-8") as f:
                tables[name] = [{f"{name}.{k}": v for k, v in r.items()}
                                for r in csv.DictReader(f)]
        return tables[name]

    indexes = {}

    def get_index(name, col):
        key = (name, col)
        if key not in indexes:
            idx = defaultdict(list)
            for o in get_table(name):
                idx[o[col]].append(o)
            indexes[key] = idx
        return indexes[key]

    out = {}
    for q in workload:
        conds = [tuple(c) for c in q.get("where", [])]
        rows = [r for r in get_table(q["from"]) if matches(r, conds)]
        if "join" in q:
            j = q["join"]
            left = f"{q['from']}.{j['on_left']}"
            idx = get_index(j["table"], f"{j['table']}.{j['on_right']}")
            jconds = [tuple(c) for c in q.get("join_where", [])]
            joined = []
            for r in rows:
                for o in idx.get(r[left], ()):
                    merged = dict(r)
                    merged.update(o)
                    if matches(merged, jconds):
                        joined.append(merged)
            rows = joined
        if "group_by" in q:
            groups = defaultdict(list)
            for r in rows:
                groups[str(r[q["group_by"]])].append(r)
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
