"""Generate fixture data: 2 correctness cases + 1 timing input + expected outputs."""
import json
import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TASK_DIR.parents[2]))  # repo root

from benchmarks.dagi_eval._genutil import write_expected  # noqa: E402


def main() -> None:
    data = TASK_DIR / "hidden" / "data"
    for name, numbers in [("case_01_empty", []), ("case_02_small", [1, 2, 3])]:
        d = data / "correctness" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "numbers.json").write_text(json.dumps(numbers), encoding="utf-8")
    t = data / "timing"
    t.mkdir(parents=True, exist_ok=True)
    (t / "numbers.json").write_text(json.dumps(list(range(3000))), encoding="utf-8")
    write_expected(TASK_DIR)
    print("fixture data written")


if __name__ == "__main__":
    main()
