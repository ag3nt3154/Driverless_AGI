"""Shared generator helper: store baseline outputs for correctness cases."""
from __future__ import annotations

import json
from pathlib import Path

from benchmarks.dagi_eval import scoring


def write_expected(task_dir: Path) -> None:
    """Run the pristine baseline on every hidden correctness case and store
    the outputs as hidden/data/expected/<case>.json."""
    meta = scoring.load_task_meta(task_dir)
    data = task_dir / "hidden" / "data"
    exp_dir = data / "expected"
    exp_dir.mkdir(parents=True, exist_ok=True)
    for case in sorted((data / "correctness").iterdir()):
        payload = scoring.run_entry(
            task_dir / "hidden" / "baseline", meta["entry_module"],
            meta["entry_func"], case,
            per_call_timeout_s=scoring.BASELINE_CALL_TIMEOUT_S)
        if not payload.get("ok"):
            raise SystemExit(f"{case.name}: baseline failed: {payload.get('error')}")
        (exp_dir / f"{case.name}.json").write_text(
            json.dumps(payload["result"]), encoding="utf-8")
