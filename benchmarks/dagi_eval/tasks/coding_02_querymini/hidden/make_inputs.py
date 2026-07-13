"""Generate hidden inputs for coding_02_querymini. Seeded — deterministic."""
import csv
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 202
# Calibration knobs — naive cost is dominated by nested-loop joins:
# roughly (filtered orders) x N_USERS per join query, plus CSV reload per query.
N_USERS = 1600
N_ORDERS = 25000
N_JOIN_QUERIES = 12
N_SIMPLE_QUERIES = 13

COUNTRIES = ["US", "DE", "JP", "BR", "IN", "FR"]
SEGMENTS = ["free", "pro", "enterprise"]
STATUSES = ["paid", "refunded", "pending"]

# Fixed per-case seed offsets. NOTE: the plan draft used
# `hash(name) % 1000`, but Python's built-in hash() on strings is
# randomized per-process (PYTHONHASHSEED) unless explicitly disabled; this
# repo's conftest.py / pytest config does not set PYTHONHASHSEED, so using
# hash() here would make the correctness fixtures (and their pre-baked
# hidden/data/expected/*.json) non-reproducible across runs. Use a fixed
# mapping instead so re-running make_inputs.py always regenerates byte-
# identical data.
CASE_SEED_OFFSETS = {
    "case_01_tiny": 1,
    "case_02_filters": 2,
    "case_03_joins": 3,
    "case_04_mixed": 4,
}


def _write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _gen_dataset(rng, out_dir, n_users, n_orders):
    users = [[u, rng.choice(COUNTRIES), rng.randint(18, 80),
              rng.choice(SEGMENTS)] for u in range(1, n_users + 1)]
    orders = [[o, rng.randint(1, n_users), rng.randint(1, 2000),
               rng.choice(STATUSES), rng.randint(1, 30)]
              for o in range(1, n_orders + 1)]
    _write_csv(out_dir / "tables" / "users.csv",
               ["id", "country", "age", "segment"], users)
    _write_csv(out_dir / "tables" / "orders.csv",
               ["id", "user_id", "amount", "status", "day"], orders)


def _gen_workload(rng, n_join, n_simple):
    queries = []
    for i in range(n_simple):
        q = {"id": f"s{i:02d}", "from": "orders",
             "where": [["orders.status", "=", rng.choice(STATUSES)],
                       ["orders.amount", rng.choice([">", "<"]),
                        rng.randint(100, 1900)]]}
        if rng.random() < 0.5:
            q["group_by"] = "orders.status"
            q["agg"] = "count"
        queries.append(q)
    for i in range(n_join):
        q = {"id": f"j{i:02d}", "from": "orders",
             "where": [["orders.amount", ">", rng.randint(100, 1000)]],
             "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
             "group_by": "users.country",
             "agg": rng.choice(["sum", "avg", "count"]),
             "agg_col": "orders.amount"}
        if rng.random() < 0.5:
            q["join_where"] = [["users.segment", "=", rng.choice(SEGMENTS)]]
        queries.append(q)
    rng.shuffle(queries)
    return queries


def main():
    rng = random.Random(SEED)
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # small correctness cases with distinct workload shapes
    for name, (nu, no, nj, ns) in {
        "case_01_tiny": (5, 12, 2, 2),
        "case_02_filters": (20, 100, 0, 8),
        "case_03_joins": (20, 100, 8, 0),
        "case_04_mixed": (50, 400, 5, 5),
    }.items():
        crng = random.Random(SEED + CASE_SEED_OFFSETS[name])
        d = cor / name
        _gen_dataset(crng, d, nu, no)
        (d / "workload.json").write_text(
            json.dumps(_gen_workload(crng, nj, ns)), encoding="utf-8")
    # empty-result query edge case
    d = cor / "case_05_empty_result"
    crng = random.Random(SEED + 5)
    _gen_dataset(crng, d, 5, 10)
    (d / "workload.json").write_text(json.dumps([
        {"id": "e0", "from": "orders",
         "where": [["orders.amount", ">", 999999]]},
        {"id": "e1", "from": "orders",
         "where": [["orders.amount", ">", 999999]],
         "join": {"table": "users", "on_left": "user_id", "on_right": "id"},
         "group_by": "users.country", "agg": "sum", "agg_col": "orders.amount"},
    ]), encoding="utf-8")

    t = data / "timing"
    _gen_dataset(rng, t, N_USERS, N_ORDERS)
    (t / "workload.json").write_text(
        json.dumps(_gen_workload(rng, N_JOIN_QUERIES, N_SIMPLE_QUERIES)),
        encoding="utf-8")

    write_expected(TASK_DIR)
    print("querymini data written")


if __name__ == "__main__":
    main()
