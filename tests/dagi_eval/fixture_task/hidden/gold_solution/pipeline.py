import json
from pathlib import Path


def run(input_dir):
    numbers = json.loads(Path(input_dir, "numbers.json").read_text(encoding="utf-8"))
    return {"total": sum(numbers), "count": len(numbers)}
