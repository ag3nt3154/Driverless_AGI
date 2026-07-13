"""Generate hidden inputs for coding_01_logpipe. Seeded — deterministic."""
import datetime
import random
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[3]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402

SEED = 101
# Calibration knobs — naive timing target 10-40 s. Cost is roughly quadratic
# in total event count (global session-list scan).
N_USERS = 300
EVENTS_PER_USER = 150

EVENTS = ["view", "cart", "checkout", "purchase", "ping"]
BASE_EPOCH = int(datetime.datetime(2026, 1, 1, 0, 0, 0).timestamp())


def _fmt(epoch):
    return datetime.datetime.fromtimestamp(epoch).strftime("%Y-%m-%dT%H:%M:%S")


def _write_log(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _gen_lines(rng, n_users, events_per_user):
    lines = []
    for u in range(n_users):
        user = f"user{u:05d}"
        t = BASE_EPOCH + rng.randint(0, 86400 * 30)
        made = 0
        while made < events_per_user:
            burst = min(rng.randint(3, 8), events_per_user - made)
            for _ in range(burst):
                t += rng.randint(1, 600)
                lines.append(
                    f"{_fmt(t)}|{user}|{rng.choice(EVENTS)}|/p/{rng.randint(1, 50)}")
                made += 1
            t += rng.randint(3600, 86400)  # gap > 1800 s -> new session
    rng.shuffle(lines)
    return lines


def main():
    data = TASK_DIR / "hidden" / "data"
    cor = data / "correctness"

    _write_log(cor / "case_01_empty" / "logs" / "a.log", [])
    _write_log(cor / "case_02_single" / "logs" / "a.log", [
        "2026-01-01T10:00:00|alice|view|/p/1",
        "2026-01-01T10:10:00|alice|purchase|/p/1",
    ])
    # exactly 1800 s -> same session; the third event starts a new session
    _write_log(cor / "case_03_gap_boundary" / "logs" / "a.log", [
        "2026-01-01T10:00:00|bob|view|/p/1",
        "2026-01-01T10:30:00|bob|cart|/p/1",
        "2026-01-01T11:00:01|bob|view|/p/2",
    ])
    _write_log(cor / "case_04_unsorted" / "logs" / "a.log",
               _gen_lines(random.Random(SEED + 1), 5, 20))
    multi = _gen_lines(random.Random(SEED + 2), 8, 25)
    _write_log(cor / "case_05_multifile" / "logs" / "a.log",
               multi[: len(multi) // 2])
    _write_log(cor / "case_05_multifile" / "logs" / "b.log",
               multi[len(multi) // 2:])
    _write_log(cor / "case_06_medium" / "logs" / "a.log",
               _gen_lines(random.Random(SEED + 3), 40, 60))

    timing_lines = _gen_lines(random.Random(SEED), N_USERS, EVENTS_PER_USER)
    n = len(timing_lines) // 3
    _write_log(data / "timing" / "logs" / "a.log", timing_lines[:n])
    _write_log(data / "timing" / "logs" / "b.log", timing_lines[n:2 * n])
    _write_log(data / "timing" / "logs" / "c.log", timing_lines[2 * n:])

    write_expected(TASK_DIR)
    print(f"logpipe data written ({len(timing_lines)} timing lines)")


if __name__ == "__main__":
    main()
