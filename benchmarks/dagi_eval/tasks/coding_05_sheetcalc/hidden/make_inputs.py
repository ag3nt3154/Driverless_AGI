"""Generate hidden inputs for coding_05_sheetcalc. Seeded — deterministic.

Acyclicity guarantee: every formula in a cell at row r references only cells
with row < r (single-cell refs and range endpoints alike), for the initial
sheet and for every update. Division only by integer constants 1-4.
"""
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 505
# Calibration knobs — naive cost ~ N_UPDATES x total_cells x formula depth.
N_ROWS = 60
N_UPDATES = 400
PROBE_EVERY = 25

COLS = [chr(ord("A") + i) for i in range(20)]


def _name(rng, max_row, min_row=1):
    return f"{rng.choice(COLS)}{rng.randint(min_row, max_row)}"


def _formula(rng, row):
    mr = row - 1  # only reference strictly lower rows
    kind = rng.random()
    if kind < 0.4:
        return f"={_name(rng, mr)}+{_name(rng, mr)}*{rng.randint(1, 9)}"
    if kind < 0.7:
        col = rng.choice(COLS)
        a = rng.randint(1, max(1, mr - 10))
        b = min(mr, a + rng.randint(5, 25))
        return f"=SUM({col}{a}:{col}{b})/{rng.randint(1, 4)}"
    return (f"=IF({_name(rng, mr)}>{_name(rng, mr)},"
            f"{_name(rng, mr)}+{rng.randint(1, 20)},{rng.randint(0, 50)})")


def _gen_case(rng, n_rows, n_updates, probe_every):
    const_rows = max(2, n_rows // 2)
    cells = {}
    for col in COLS:
        for row in range(1, n_rows + 1):
            if row <= const_rows:
                cells[f"{col}{row}"] = str(rng.randint(0, 100))
            else:
                cells[f"{col}{row}"] = _formula(rng, row)
    updates, probes = [], []
    for i in range(1, n_updates + 1):
        if rng.random() < 0.7:  # constant change low in the sheet
            cell = f"{rng.choice(COLS)}{rng.randint(1, const_rows)}"
            updates.append({"cell": cell, "value": str(rng.randint(0, 100))})
        else:                    # formula replacement high in the sheet
            row = rng.randint(const_rows + 1, n_rows)
            updates.append({"cell": f"{rng.choice(COLS)}{row}",
                            "value": _formula(rng, row)})
        if i % probe_every == 0:
            probes.append({"after_event": i,
                           "cells": sorted({_name(rng, n_rows)
                                            for _ in range(5)})})
    return cells, updates, probes


def _write(path, cells, updates, probes):
    path.mkdir(parents=True, exist_ok=True)
    (path / "sheet.json").write_text(json.dumps(cells), encoding="utf-8")
    (path / "updates.jsonl").write_text(
        "\n".join(json.dumps(u) for u in updates) + "\n", encoding="utf-8")
    (path / "probes.json").write_text(json.dumps(probes), encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # hand-built: chain + diamond + IF boundary flips + probe of an empty cell
    _write(cor / "case_01_chain",
           {"A1": "5", "A2": "=A1*2", "A3": "=A2+A1", "A4": "=IF(A3>10,A2,A1)",
            "A5": "=SUM(A1:A4)"},
           [{"cell": "A1", "value": "1"},
            {"cell": "A1", "value": "20"},
            {"cell": "A2", "value": "=A1+3"}],
           [{"after_event": 1, "cells": ["A4", "A5"]},
            {"after_event": 2, "cells": ["A4", "A5"]},
            {"after_event": 3, "cells": ["A4", "A5", "Z9"]}])
    c2 = _gen_case(random.Random(SEED + 2), 8, 15, 4)
    _write(cor / "case_02_small", *c2)
    c3 = _gen_case(random.Random(SEED + 3), 20, 60, 10)
    _write(cor / "case_03_medium", *c3)

    t = _gen_case(random.Random(SEED), N_ROWS, N_UPDATES, PROBE_EVERY)
    _write(data / "timing", *t)

    write_expected(TASK_DIR)
    print("sheetcalc data written")


if __name__ == "__main__":
    main()
