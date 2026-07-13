"""Epidemic simulation on a 2D world. Contract: run(input_dir) -> dict."""
import json
from pathlib import Path


def _bounce_one(e, w, h):
    e["x"] += e["vx"]
    e["y"] += e["vy"]
    if e["x"] < 0:
        e["x"] = -e["x"]
        e["vx"] = -e["vx"]
    elif e["x"] > w:
        e["x"] = 2 * w - e["x"]
        e["vx"] = -e["vx"]
    if e["y"] < 0:
        e["y"] = -e["y"]
        e["vy"] = -e["vy"]
    elif e["y"] > h:
        e["y"] = 2 * h - e["y"]
        e["vy"] = -e["vy"]


def _move_and_bounce(ents, w, h):
    for e in ents:
        _bounce_one(e, w, h)


def _is_infected_neighbor(e, ents, i, r2):
    for k, o in enumerate(ents):          # all-pairs scan
        if o["state"] == "I" and k != i:
            dx = e["x"] - o["x"]
            dy = e["y"] - o["y"]
            if dx * dx + dy * dy <= r2:
                return True
    return False


def _find_newly_infected(ents, r2):
    newly = []
    for i, e in enumerate(ents):
        hit = False
        if e["state"] == "S":
            hit = _is_infected_neighbor(e, ents, i, r2)
        newly.append(hit)
    return newly


def _advance_recovery(ents, newly, recover):
    for e, hit in zip(ents, newly):
        if e["state"] == "I":
            e["infected_for"] += 1
            if e["infected_for"] >= recover:
                e["state"] = "R"
        elif hit and e["state"] == "S":
            e["state"] = "I"
            e["infected_for"] = 0


def _count_infected(ents):
    return sum(1 for e in ents if e["state"] == "I")


def _final_counts(ents):
    final = {"S": 0, "I": 0, "R": 0}
    for e in ents:
        final[e["state"]] += 1
    return final


def _checksum(ents):
    return sum(abs(e["x"]) + abs(e["y"]) for e in ents)


def run(input_dir):
    world = json.loads(Path(input_dir, "world.json").read_text(encoding="utf-8"))
    w, h = world["width"], world["height"]
    radius = world["radius"]
    r2 = radius * radius
    steps = world["steps"]
    recover = world["recover_steps"]
    ents = [dict(e) for e in world["entities"]]
    for e in ents:
        e["infected_for"] = 0

    infected_per_step = []
    for _ in range(steps):
        _move_and_bounce(ents, w, h)
        newly = _find_newly_infected(ents, r2)
        _advance_recovery(ents, newly, recover)
        infected_per_step.append(_count_infected(ents))

    return {"infected_per_step": infected_per_step, "final": _final_counts(ents),
            "checksum": _checksum(ents)}
