"""Generate hidden inputs for coding_03_simgrid. Seeded — deterministic."""
import json
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 303
# Calibration knobs — naive cost ~ steps x n_susceptible x n_entities.
# Recalibrated from the plan's initial N_ENTITIES=1200/STEPS=40 (which gave a
# ~3.4s naive baseline on this machine, well under the 10-40s target) up to
# N_ENTITIES=2500/STEPS=50 to land baseline_time_s in range.
N_ENTITIES = 2500
STEPS = 50


def _world(rng, n, steps, width=1000.0, height=1000.0, radius=12.0,
           recover=8, infected_frac=0.02):
    entities = []
    for _ in range(n):
        entities.append({
            "x": round(rng.uniform(0, width), 4),
            "y": round(rng.uniform(0, height), 4),
            "vx": round(rng.uniform(-4, 4), 4),
            "vy": round(rng.uniform(-4, 4), 4),
            "state": "I" if rng.random() < infected_frac else "S",
        })
    if not any(e["state"] == "I" for e in entities):
        entities[0]["state"] = "I"
    return {"width": width, "height": height, "radius": radius,
            "steps": steps, "recover_steps": recover, "entities": entities}


def _write(path, world):
    path.mkdir(parents=True, exist_ok=True)
    (path / "world.json").write_text(json.dumps(world), encoding="utf-8")


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    # single entity, no interactions, wall bounces
    _write(cor / "case_01_single", {
        "width": 10.0, "height": 10.0, "radius": 2.0, "steps": 12,
        "recover_steps": 3,
        "entities": [{"x": 1.0, "y": 9.5, "vx": -0.7, "vy": 0.9,
                      "state": "I"}]})
    # pair exactly at infection boundary
    _write(cor / "case_02_boundary", {
        "width": 100.0, "height": 100.0, "radius": 5.0, "steps": 3,
        "recover_steps": 10,
        "entities": [{"x": 10.0, "y": 10.0, "vx": 0.0, "vy": 0.0, "state": "I"},
                     {"x": 15.0, "y": 10.0, "vx": 0.0, "vy": 0.0, "state": "S"},
                     {"x": 15.1, "y": 50.0, "vx": 0.0, "vy": 0.0, "state": "S"}]})
    # full recover cycle
    _write(cor / "case_03_recover",
           _world(random.Random(SEED + 3), 30, 25, radius=40.0, recover=4,
                  infected_frac=0.2))
    _write(cor / "case_04_medium",
           _world(random.Random(SEED + 4), 120, 30))

    _write(data / "timing", _world(random.Random(SEED), N_ENTITIES, STEPS))

    write_expected(TASK_DIR)
    print("simgrid data written")


if __name__ == "__main__":
    main()
