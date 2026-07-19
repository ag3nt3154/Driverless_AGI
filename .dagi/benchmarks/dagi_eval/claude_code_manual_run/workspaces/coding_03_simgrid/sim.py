"""Epidemic simulation on a 2D world. Contract: run(input_dir) -> dict."""
import json
from pathlib import Path

import numpy as np

try:
    from scipy.spatial import cKDTree
    _HAVE_SCIPY = True
except ImportError:  # pragma: no cover - scipy is an allowed but optional dep
    _HAVE_SCIPY = False

S, I, R = 0, 1, 2
_STATE_TO_CODE = {"S": S, "I": I, "R": R}
_CODE_TO_STATE = {S: "S", I: "I", R: "R"}


def _bounce(x, y, vx, vy, w, h):
    # Single-branch reflection identical to the scalar `if/elif` semantics:
    # only one wall can flip a coordinate per axis per step, decided by the
    # *post-move, pre-reflection* position (mirrors the original elif
    # short-circuit).
    x = x + vx
    y = y + vy

    lt0 = x < 0
    gtw = (~lt0) & (x > w)
    x = np.where(lt0, -x, np.where(gtw, 2 * w - x, x))
    vx = np.where(lt0 | gtw, -vx, vx)

    lt0y = y < 0
    gth = (~lt0y) & (y > h)
    y = np.where(lt0y, -y, np.where(gth, 2 * h - y, y))
    vy = np.where(lt0y | gth, -vy, vy)
    return x, y, vx, vy


def _find_hits(x, y, state, r2, radius):
    """Return boolean mask: susceptible entities with >=1 infected neighbor
    within radius (using current-step positions/states, before recovery)."""
    n = x.shape[0]
    hit = np.zeros(n, dtype=bool)
    s_mask = state == S
    i_mask = state == I
    n_i = int(i_mask.sum())
    n_s = int(s_mask.sum())
    if n_i == 0 or n_s == 0:
        return hit

    ix, iy = x[i_mask], y[i_mask]
    sx, sy = x[s_mask], y[s_mask]

    if _HAVE_SCIPY and n_i * n_s > 4096:
        tree = cKDTree(np.column_stack((ix, iy)))
        dist, _ = tree.query(np.column_stack((sx, sy)), k=1)
        s_hit = dist <= radius
    else:
        dx = sx[:, None] - ix[None, :]
        dy = sy[:, None] - iy[None, :]
        d2 = dx * dx + dy * dy
        s_hit = (d2 <= r2).any(axis=1)

    hit[s_mask] = s_hit
    return hit


def run(input_dir):
    world = json.loads(Path(input_dir, "world.json").read_text(encoding="utf-8"))
    w, h = world["width"], world["height"]
    radius = world["radius"]
    r2 = radius * radius
    steps = world["steps"]
    recover = world["recover_steps"]
    entities = world["entities"]
    n = len(entities)

    x = np.array([e["x"] for e in entities], dtype=np.float64)
    y = np.array([e["y"] for e in entities], dtype=np.float64)
    vx = np.array([e["vx"] for e in entities], dtype=np.float64)
    vy = np.array([e["vy"] for e in entities], dtype=np.float64)
    state = np.array([_STATE_TO_CODE[e["state"]] for e in entities], dtype=np.int8)
    infected_for = np.zeros(n, dtype=np.int64)

    infected_per_step = []
    for _ in range(steps):
        x, y, vx, vy = _bounce(x, y, vx, vy, w, h)

        hit = _find_hits(x, y, state, r2, radius)

        i_mask = state == I
        infected_for[i_mask] += 1
        recovered = i_mask & (infected_for >= recover)
        state[recovered] = R

        newly_infected = (state == S) & hit
        state[newly_infected] = I
        infected_for[newly_infected] = 0

        infected_per_step.append(int(np.count_nonzero(state == I)))

    final = {"S": int(np.count_nonzero(state == S)),
             "I": int(np.count_nonzero(state == I)),
             "R": int(np.count_nonzero(state == R))}
    checksum = float(np.sum(np.abs(x) + np.abs(y)))

    return {"infected_per_step": infected_per_step, "final": final, "checksum": checksum}
