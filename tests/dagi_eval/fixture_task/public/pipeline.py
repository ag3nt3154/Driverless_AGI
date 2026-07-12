import json
from pathlib import Path


def run(input_dir):
    numbers = json.loads(Path(input_dir, "numbers.json").read_text(encoding="utf-8"))
    total = 0
    for n in numbers:
        for _ in range(2000):  # deliberate busywork
            pass
        total += n
    return {"total": total, "count": len(numbers)}
