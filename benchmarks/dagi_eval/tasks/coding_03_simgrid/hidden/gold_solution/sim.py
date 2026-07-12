"""Gold solution: numpy vectorized movement + spatial-hash neighbor search.

Float semantics match the naive code: identical elementwise position/bounce
arithmetic and identical squared-distance comparisons, so results are equal
within outputs_match tolerance (checksum summation order differs only at
~1e-14 relative).
"""
import json
from pathlib import Path

import numpy as np

S, I, R = 0, 1, 2


def _load_arrays(ents):
    x = np.array([e["x"] for e in ents], dtype=np.float64)
    y = np.array([e["y"] for e in ents], dtype=np.float64)
    vx = np.array([e["vx"] for e in ents], dtype=np.float64)
    vy = np.array([e["vy"] for e in ents], dtype=np.float64)
    state = np.array([I if e["state"] == "I" else S for e in ents],
                      dtype=np.int64)
    return x, y, vx, vy, state


def _move_and_bounce_vec(x, y, vx, vy, bounds):
    w, h = bounds
    x += vx
    y += vy
    m = x < 0
    x[m] = -x[m]
    vx[m] = -vx[m]
    m = x > w
    x[m] = 2 * w - x[m]
    vx[m] = -vx[m]
    m = y < 0
    y[m] = -y[m]
    vy[m] = -vy[m]
    m = y > h
    y[m] = 2 * h - y[m]
    vy[m] = -vy[m]


def _build_cells(inf_idx, pos, radius):
    x, y = pos
    cells = {}
    for j in inf_idx:
        key = (int(x[j] // radius), int(y[j] // radius))
        cells.setdefault(key, []).append(j)
    return cells


def _neighbor_hit(i, pos, cells, r2, cell_xy):
    x, y = pos
    cx, cy = cell_xy
    for dcx in (-1, 0, 1):
        for dcy in (-1, 0, 1):
            for j in cells.get((cx + dcx, cy + dcy), ()):
                dx = x[i] - x[j]
                dy = y[i] - y[j]
                if dx * dx + dy * dy <= r2:
                    return True
    return False


def _find_newly_infected_spatial(sus, inf, pos, radius, r2):
    x, y = pos
    newly = []
    if len(sus) and len(inf):
        cells = _build_cells(inf, pos, radius)
        for i in sus:
            cx, cy = int(x[i] // radius), int(y[i] // radius)
            if _neighbor_hit(i, pos, cells, r2, (cx, cy)):
                newly.append(i)
    return newly


def _advance_recovery_vec(state, infected_for, newly, recover):
    was_I = state == I
    infected_for[was_I] += 1
    state[was_I & (infected_for >= recover)] = R
    for i in newly:
        if state[i] == S:
            state[i] = I
            infected_for[i] = 0


def run(input_dir):
    world = json.loads(Path(input_dir, "world.json").read_text(encoding="utf-8"))
    w, h = world["width"], world["height"]
    radius = world["radius"]
    r2 = radius * radius
    steps = world["steps"]
    recover = world["recover_steps"]
    ents = world["entities"]
    n = len(ents)

    x, y, vx, vy, state = _load_arrays(ents)
    infected_for = np.zeros(n, dtype=np.int64)

    infected_per_step = []
    for _ in range(steps):
        _move_and_bounce_vec(x, y, vx, vy, (w, h))

        sus = np.flatnonzero(state == S)
        inf = np.flatnonzero(state == I)
        newly = _find_newly_infected_spatial(sus, inf, (x, y), radius, r2)

        _advance_recovery_vec(state, infected_for, newly, recover)
        infected_per_step.append(int((state == I).sum()))

    final = {"S": int((state == S).sum()), "I": int((state == I).sum()),
             "R": int((state == R).sum())}
    checksum = float(np.abs(x).sum() + np.abs(y).sum())
    return {"infected_per_step": infected_per_step, "final": final,
            "checksum": checksum}
